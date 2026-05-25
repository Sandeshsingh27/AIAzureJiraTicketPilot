"""Support ticket analyzer for hotel-unavailable investigations.

Flow:
1) Read Jira ticket details.
2) Extract investigation keys (museId, hrCode, hKey, dates, booking source, customer key).
3) Query New Relic logs for correlated events.
4) Build a singleavail payload from log/Jira values.
5) Optionally call the EC2 singleavail endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests
from dotenv import load_dotenv


DEFAULT_SINGLEAVAIL_URL = "http://iut1-crsng-tester-backend.iec.hrs.cc/crsng/singleavail"
DEFAULT_NEW_RELIC_GRAPHQL_URL = "https://api.newrelic.com/graphql"
MAX_JIRA_COMMENT_CHARS = 25000
DEFAULT_AVAILABILITY_KEYWORDS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "ticket_analysis_keywords.json")
)
DEFAULT_AVAILABILITY_KEYWORDS = [
    "hotel not available",
    "hotel unavailable",
    "hotel not bookable",
]


def _adf_to_text(node: Any) -> str:
    """Flatten Jira Atlassian Document Format (ADF) to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_adf_to_text(item) for item in node if item is not None)
    if isinstance(node, dict):
        parts: List[str] = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        for key in ("content", "attrs"):
            if key in node:
                parts.append(_adf_to_text(node[key]))
        return " ".join(p for p in parts if p)
    return str(node)


def _safe_get(dct: Dict[str, Any], dotted: str) -> Any:
    cur: Any = dct
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _extract_first(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    m = re.search(pattern, text, flags)
    if not m:
        return None
    value = m.group(1).strip()
    return value if value else None


def _strip_outer_braces(value: Optional[Any]) -> Optional[str]:
    """Trim surrounding braces/brackets/quotes often present in copied log values."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    pairs = [("{", "}"), ("[", "]"), ("(", ")"), ('"', '"'), ("'", "'")]
    changed = True
    while changed and text:
        changed = False
        for left, right in pairs:
            if text.startswith(left) and text.endswith(right) and len(text) >= 2:
                text = text[1:-1].strip()
                changed = True
    return text or None


def _normalize_identifier_value(value: Optional[Any]) -> Optional[str]:
    """Normalize identifier values copied from logs/tickets.

    Examples:
      "[1641]" -> "1641"
      "[\"287238\"]" -> "287238"
      "{ABC}" -> "ABC"
    """
    text = _strip_outer_braces(value)
    if text is None:
        return None

    # Try JSON first for bracket-wrapped strings/lists.
    parsed = _parse_json_maybe(text)
    if isinstance(parsed, list):
        first = parsed[0] if parsed else None
        return _normalize_identifier_value(first)
    if isinstance(parsed, (str, int, float)):
        text = str(parsed).strip()

    # Unwrap one more layer if value still includes wrappers.
    text = _strip_outer_braces(text) or text
    return text.strip() or None


def _unescape_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    # Convert escaped quote/backslash sequences from copied JSON snippets.
    text = text.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    return text.strip() or None


def _extract_key_from_blob(blob: str, key: str) -> Optional[str]:
    """Extract key values from mixed free text / JSON-like ticket content.

    Handles common ticket formats:
      "hrCode": "[\"287238\"]"   -> 287238   (backslash-escaped inner quotes)
      "hrCode": "[\"287238\"]"   -> 287238   (literal inner quotes, no backslash)
      "hrCode": "[1641]"         -> 1641     (plain brackets)
      "hrCode": "287238"         -> 287238   (simple string)
    """
    ek = re.escape(key)
    patterns = [
        # Highest priority: JSON array-string with optional escaped/literal inner quotes
        # Matches: "key": "[\"val\"]"  or  "key": "[val]"  or  "key": "['val']"
        rf'"{ek}"\s*:\s*"\[\s*(?:\\?["\']?)([A-Za-z0-9._/\-]+)(?:\\?["\']?)\s*(?:,\s*(?:\\?["\']?)[A-Za-z0-9._/\-]+(?:\\?["\']?)\s*)*\]"',
        # Standard quoted JSON value (handles backslash-escaped chars inside)
        rf'"{ek}"\s*:\s*"((?:\\.|[^"\\])*)"',
        # Unquoted JSON value (number or bare word)
        rf'"{ek}"\s*:\s*([^,\r\n"{{}}]+)',
        # Key=value or key: value (non-JSON)
        rf'\b{ek}\b\s*[:=]\s*([^,\r\n]+)',
    ]
    for pattern in patterns:
        val = _extract_first(pattern, blob, flags=re.IGNORECASE)
        if val:
            unescaped = _unescape_text(val)
            # Skip partial bracket values like "[" or "[\" which indicate failed extraction
            if unescaped and len(unescaped) > 1 or (unescaped and unescaped not in ("[", "[\\")):
                return unescaped
    return None


def _extract_rate_access_codes(text: str) -> List[str]:
    match = re.search(r"(?:rate\s*access\s*codes?|RAC_LIST)\s*[:=]\s*([A-Z0-9,;\s-]+)", text, re.IGNORECASE)
    if not match:
        return []
    raw = match.group(1)
    codes = [x.strip().upper() for x in re.split(r"[,;\s]+", raw) if x.strip()]
    seen: List[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    return seen


def _load_availability_keywords() -> List[str]:
    file_path = os.getenv("TICKET_ANALYSIS_KEYWORDS_FILE", "").strip() or DEFAULT_AVAILABILITY_KEYWORDS_FILE
    try:
        with open(file_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception:
        payload = {}

    raw_keywords = payload.get("availabilityKeywords") if isinstance(payload, dict) else None
    if not isinstance(raw_keywords, list):
        raw_keywords = DEFAULT_AVAILABILITY_KEYWORDS

    keywords: List[str] = []
    for item in raw_keywords:
        text = str(item or "").strip().lower()
        if text and text not in keywords:
            keywords.append(text)
    return keywords or list(DEFAULT_AVAILABILITY_KEYWORDS)


def _extract_availability_keyword_hits(text: str, keywords: List[str]) -> List[str]:
    if not text:
        return []
    normalized_text = re.sub(r"\s+", " ", text.lower())
    hits: List[str] = []
    for keyword in keywords:
        phrase = re.sub(r"\s+", " ", str(keyword or "").strip().lower())
        if phrase and phrase in normalized_text and phrase not in hits:
            hits.append(phrase)
    return hits


def _extract_list_literal_from_blob(blob: str, key: str) -> Optional[str]:
    """Extract a list-like value for a key from mixed JSON/free-text blobs."""
    ek = re.escape(key)
    patterns = [
        # Key contains a quoted list-string, e.g. "companyKey": "[32485,16120]"
        rf'"{ek}"\s*:\s*"((?:\\.|[^"\\])*)"',
        # Key contains a JSON list, e.g. "rateAccessCodeIn": ["FAT","IVE"]
        rf'"{ek}"\s*:\s*(\[[^\]]*\])',
        # Non-JSON key/value form, e.g. companyKey=[32485,16120]
        rf'\b{ek}\b\s*[:=]\s*(\[[^\]]*\])',
    ]
    for pattern in patterns:
        raw = _extract_first(pattern, blob, flags=re.IGNORECASE)
        if raw:
            return _unescape_text(raw)
    return None


def _parse_listish(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)

    text = str(value).strip()
    if not text:
        return []

    parsed = _parse_json_maybe(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, str):
        nested = _parse_json_maybe(parsed)
        if isinstance(nested, list):
            return nested

    stripped = _strip_outer_braces(text)
    if stripped and "," in stripped:
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return [stripped] if stripped else []


def _parse_string_list(value: Any) -> List[str]:
    items = _parse_listish(value)
    result: List[str] = []
    for item in items:
        text = _strip_outer_braces(item)
        if text:
            result.append(str(text).upper())
    # keep order, remove duplicates
    seen: List[str] = []
    for item in result:
        if item not in seen:
            seen.append(item)
    return seen


def _parse_int_list(value: Any) -> List[int]:
    items = _parse_listish(value)
    result: List[int] = []
    for item in items:
        text = _strip_outer_braces(item)
        if text and str(text).isdigit():
            result.append(int(str(text)))
    # keep order, remove duplicates
    seen: List[int] = []
    for item in result:
        if item not in seen:
            seen.append(item)
    return seen


def _normalize_compare_token(value: Any) -> Optional[str]:
    token = _strip_outer_braces(value)
    if token is None:
        return None
    normalized = str(token).strip().upper()
    return normalized or None


def _collect_compare_tokens(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        tokens: List[str] = []
        for nested in value.values():
            tokens.extend(_collect_compare_tokens(nested))
        return tokens
    if isinstance(value, list):
        tokens: List[str] = []
        for nested in value:
            tokens.extend(_collect_compare_tokens(nested))
        return tokens
    if isinstance(value, str):
        parsed = _parse_json_maybe(value)
        if parsed is not None and parsed is not value:
            return _collect_compare_tokens(parsed)
        text = value.strip()
        if not text:
            return []
        # Support list-like scalar strings such as "A;B;C" or "A,B,C".
        if ";" in text or "," in text:
            tokens: List[str] = []
            for part in re.split(r"[;,]", text):
                normalized = _normalize_compare_token(part)
                if normalized:
                    tokens.append(normalized)
            return tokens
    normalized = _normalize_compare_token(value)
    return [normalized] if normalized else []


def _is_hr_code_ci_whitelisted(hr_code: Optional[Any], whitelist_value: Any) -> bool:
    hr_tokens = _collect_compare_tokens(hr_code)
    if not hr_tokens:
        return False
    whitelist_tokens = set(_collect_compare_tokens(whitelist_value))
    if not whitelist_tokens:
        return False
    return any(token in whitelist_tokens for token in hr_tokens)


def _parse_json_maybe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _recursive_find(obj: Any, target_keys: set[str], out: Dict[str, Any]) -> None:
    if not isinstance(obj, (dict, list)):
        return
    if isinstance(obj, list):
        for item in obj:
            _recursive_find(item, target_keys, out)
        return
    for key, val in obj.items():
        key_norm = str(key).strip()
        if key_norm in target_keys and out.get(key_norm) in (None, "", []):
            out[key_norm] = val
        # Some logs embed rich JSON in string fields (e.g. content/request/response body)
        nested = _parse_json_maybe(val)
        if nested is not None:
            _recursive_find(nested, target_keys, out)
        _recursive_find(val, target_keys, out)


def _extract_log_fields(log: Dict[str, Any]) -> Dict[str, Any]:
    """Extract normalized investigation fields from New Relic log records.

    Supports direct fields, nested objects, and JSON embedded as strings.
    """
    field_keys = {
        "museId",
        "hrCode",
        "hKey",
        "chainId",
        "bookingSource",
        "customerKey",
        "kKey",
        "companyKey",
        "fKey",
        "arrivalDate",
        "departureDate",
        "rateAccessCodes",
        "hotelIdsForCIWhiteList",
    }
    found: Dict[str, Any] = {k: None for k in field_keys}

    # direct lookup first
    for key in field_keys:
        if key in log:
            found[key] = log.get(key)

    # nested lookup in whole object + parseable JSON strings
    _recursive_find(log, field_keys, found)

    msg = str(log.get("message") or "")
    if found.get("museId") in (None, ""):
        found["museId"] = _extract_first(r"muse\s*id\s*[:=]\s*([A-Z0-9_-]+)", msg)
    if found.get("hrCode") in (None, ""):
        found["hrCode"] = _extract_first(r"hr\s*code\s*[:=]\s*([A-Za-z0-9;_{}-]+)", msg)
    if found.get("hKey") in (None, ""):
        found["hKey"] = _extract_first(r"h\s*key\s*[:=]\s*([A-Za-z0-9_{}-]+)", msg)
    if found.get("chainId") in (None, ""):
        found["chainId"] = _extract_first(r"chain\s*id\s*[:=]\s*([A-Za-z0-9_-]+)", msg)
    if found.get("bookingSource") in (None, ""):
        found["bookingSource"] = _extract_first(r"booking\s*source(?:\s*id)?\s*[:=]\s*([0-9]+)", msg)
    if found.get("customerKey") in (None, ""):
        found["customerKey"] = _extract_first(r"customer\s*key\s*[:=]\s*([0-9]+)", msg)
    if found.get("kKey") in (None, ""):
        found["kKey"] = _extract_first(r"k\s*key\s*[:=]\s*([A-Za-z0-9_{}-]+)", msg)
    if found.get("companyKey") in (None, ""):
        found["companyKey"] = _extract_first(r"company\s*key\s*[:=]\s*([0-9]+)", msg)
    if found.get("fKey") in (None, ""):
        found["fKey"] = _extract_first(r"f\s*key\s*[:=]\s*([A-Za-z0-9_{}-]+)", msg)
    if found.get("arrivalDate") in (None, ""):
        found["arrivalDate"] = _extract_first(r"arrival\s*date\s*[:=]\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})", msg)
    if found.get("departureDate") in (None, ""):
        found["departureDate"] = _extract_first(r"departure\s*date\s*[:=]\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})", msg)
    if not found.get("rateAccessCodes"):
        found["rateAccessCodes"] = _extract_rate_access_codes(msg)

    # Normalize aliases and wrapped values.
    found["hrCode"] = _normalize_identifier_value(found.get("hrCode"))
    found["hKey"] = _normalize_identifier_value(found.get("hKey"))
    found["chainId"] = _normalize_identifier_value(found.get("chainId"))
    found["fKey"] = _normalize_identifier_value(found.get("fKey"))
    found["companyKey"] = _normalize_identifier_value(found.get("companyKey"))
    found["customerKey"] = _normalize_identifier_value(found.get("customerKey"))
    found["kKey"] = _normalize_identifier_value(found.get("kKey"))

    # fKey and companyKey are equivalent in your domain.
    if not found.get("fKey") and found.get("companyKey"):
        found["fKey"] = found["companyKey"]
    if not found.get("companyKey") and found.get("fKey"):
        found["companyKey"] = found["fKey"]

    # customerKey and kKey are equivalent in your domain.
    if not found.get("customerKey") and found.get("kKey"):
        found["customerKey"] = found["kKey"]
    if not found.get("kKey") and found.get("customerKey"):
        found["kKey"] = found["customerKey"]

    return found


def _parse_date_to_iso_utc(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    val = date_str.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def resolve_new_relic_graphql_url(graphql_url: Optional[str], log_api_url: Optional[str]) -> str:
    """Resolve NerdGraph endpoint, optionally deriving it from a regional log API URL.

    Example mapping:
      https://log-api.eu.newrelic.com/log/v1 -> https://api.eu.newrelic.com/graphql
    """
    if graphql_url and graphql_url.strip():
        return graphql_url.strip()

    if log_api_url and log_api_url.strip():
        parsed = urlparse(log_api_url.strip())
        host = parsed.netloc or ""
        if host.startswith("log-api."):
            graphql_host = host.replace("log-api.", "api.", 1)
            return f"{parsed.scheme or 'https'}://{graphql_host}/graphql"

    return DEFAULT_NEW_RELIC_GRAPHQL_URL


def _env_flag(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_tls_verify(ca_bundle: Optional[str], insecure: Optional[str]) -> Any:
    """Return requests `verify` value: True, False, or CA bundle path."""
    if _env_flag(insecure):
        return False
    if ca_bundle and ca_bundle.strip():
        return ca_bundle.strip()
    return True


def parse_ticket_indicators(issue: Dict[str, Any]) -> Dict[str, Any]:
    fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
    summary = fields.get("summary", "") or ""
    description = _adf_to_text(fields.get("description"))

    comments = []
    comment_values = _safe_get(fields, "comment.comments") or []
    if isinstance(comment_values, list):
        for c in comment_values:
            comments.append(_adf_to_text(c.get("body") if isinstance(c, dict) else c))

    blob = "\n".join([summary, description] + comments)
    availability_keywords = _load_availability_keywords()
    availability_keyword_hits = _extract_availability_keyword_hits(blob, availability_keywords)

    ticket_rate_access_codes = _parse_string_list(
        _extract_list_literal_from_blob(blob, "rateAccessCodeIn")
        or _extract_list_literal_from_blob(blob, "rateAccessCodes")
    )
    ticket_company_ids = _parse_int_list(_extract_list_literal_from_blob(blob, "companyKey"))

    indicators = {
        "issueKey": issue.get("key"),
        "summary": summary,
        "museId": _extract_key_from_blob(blob, "museId") or _extract_first(r"muse\s*id\s*[:=]\s*([A-Z0-9_-]+)", blob),
        "hrCode": _extract_key_from_blob(blob, "hrCode") or _extract_first(r"hr\s*code\s*[:=]\s*([A-Za-z0-9;_{}\[\]\"-]+)", blob),
        "hKey": _extract_key_from_blob(blob, "hKey") or _extract_first(r"h\s*key\s*[:=]\s*([A-Za-z0-9_{}\[\]\"-]+)", blob),
        "chainId": _extract_key_from_blob(blob, "chainId") or _extract_first(r"chain\s*id\s*[:=]\s*([A-Za-z0-9_-]+)", blob),
        "bookingSource": _extract_key_from_blob(blob, "bookingSource") or _extract_first(r"booking\s*source(?:\s*id)?\s*[:=]\s*([0-9]+)", blob),
        "customerKey": _extract_key_from_blob(blob, "customerKey") or _extract_first(r"customer\s*key\s*[:=]\s*([0-9]+)", blob),
        "kKey": _extract_key_from_blob(blob, "kKey") or _extract_first(r"k\s*key\s*[:=]\s*([A-Za-z0-9_{}\[\]\"-]+)", blob),
        "companyKey": _extract_key_from_blob(blob, "companyKey") or _extract_first(r"company\s*key\s*[:=]\s*([0-9]+)", blob),
        "fKey": _extract_key_from_blob(blob, "fKey") or _extract_first(r"f\s*key\s*[:=]\s*([A-Za-z0-9_{}\[\]\"-]+)", blob),
        "arrivalDate": _extract_key_from_blob(blob, "arrivalDate") or _extract_first(r"arrival\s*date\s*[:=]\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})", blob),
        "departureDate": _extract_key_from_blob(blob, "departureDate") or _extract_first(r"departure\s*date\s*[:=]\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})", blob),
        "messageType": _extract_key_from_blob(blob, "message") or _extract_first(r"\bmessage\b\s*[:=]\s*([A-Za-z0-9_-]+)", blob),
        "rateAccessCodes": ticket_rate_access_codes or _extract_rate_access_codes(blob),
        "companyIds": ticket_company_ids,
        "availabilityKeywords": availability_keywords,
        "ticketAvailabilityKeywordHits": availability_keyword_hits,
        "ticketHasAvailabilityIndicator": bool(availability_keyword_hits),
        "rawText": blob,
    }

    indicators["hrCode"] = _normalize_identifier_value(indicators.get("hrCode"))
    indicators["hKey"] = _normalize_identifier_value(indicators.get("hKey"))
    indicators["chainId"] = _normalize_identifier_value(indicators.get("chainId"))
    indicators["fKey"] = _normalize_identifier_value(indicators.get("fKey"))
    indicators["companyKey"] = _normalize_identifier_value(indicators.get("companyKey"))
    indicators["customerKey"] = _normalize_identifier_value(indicators.get("customerKey"))
    indicators["kKey"] = _normalize_identifier_value(indicators.get("kKey"))

    if not indicators.get("fKey") and indicators.get("companyKey"):
        indicators["fKey"] = indicators["companyKey"]
    if not indicators.get("companyKey") and indicators.get("fKey"):
        indicators["companyKey"] = indicators["fKey"]

    if not indicators.get("customerKey") and indicators.get("kKey"):
        indicators["customerKey"] = indicators["kKey"]
    if not indicators.get("kKey") and indicators.get("customerKey"):
        indicators["kKey"] = indicators["customerKey"]

    return indicators


def fetch_jira_issue(issue_key: str, jira_url: str, jira_pat: str) -> Dict[str, Any]:
    url = f"{jira_url.rstrip('/')}/rest/api/2/issue/{issue_key}"
    headers = {
        "Authorization": f"Bearer {jira_pat}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def _nrql_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


DEFAULT_NR_LOG_TABLES = ["Log", "Log_IDD_PROD", "Log_IDD_PROD_Single_Multi"]


def build_nrql(
    indicators: Dict[str, Any],
    since_hours: int,
    log_tables: Optional[List[str]] = None,
) -> str:
    """Build a NRQL query from extracted ticket indicators.

    Query strategy (matching observed working queries):
      - FROM covers Log, Log_IDD_PROD and Log_IDD_PROD_Single_Multi by default.
      - message IN ('SINGLEAVAIL') to target the specific log category.
      - museId exact match via IN().
      - String identifiers (hKey, hrCode, chainId, companyKey) use LIKE '%value%'
        so bracket-wrapped stored values are still matched.
      - customerKey uses numeric equality when the value is all-digits.
    """
    tables = log_tables or DEFAULT_NR_LOG_TABLES
    from_clause = ", ".join(tables)
    where_parts = _build_nrql_filters(indicators)

    where_clause = " AND ".join(where_parts)
    raw = (
        "SELECT timestamp, message, statusCode, responseStatus, level, "
        "museId, hrCode, hKey, chainId, bookingSource, customerKey, arrivalDate, departureDate "
        f"FROM {from_clause} "
        f"WHERE {where_clause} "
        f"SINCE {int(since_hours)} hours ago LIMIT 200"
    )
    # Collapse any embedded newlines/carriage-returns so the query is always a
    # single flat line — NRQL sent over HTTP must not contain literal \n characters.
    return re.sub(r"[\r\n]+", " ", raw).strip()


def _build_nrql_filters(indicators: Dict[str, Any]) -> List[str]:
    where_parts: List[str] = []

    muse_id = str(indicators.get("museId") or "").strip()
    if muse_id:
        where_parts.append(f"museId IN ('{_nrql_escape(muse_id)}')")

    if indicators.get("ticketHasAvailabilityIndicator"):
        where_parts.append("(message IN ('SINGLEAVAIL') OR message LIKE '%NOT BOOKABLE%' OR message LIKE '%HOTEL NOT BOOKABLE%')")
    else:
        where_parts.append("message IN ('SINGLEAVAIL')")

    h_key = str(indicators.get("hKey") or "").strip()
    if h_key:
        where_parts.append(f"hKey LIKE '%{_nrql_escape(h_key)}%'")

    hr_code = str(indicators.get("hrCode") or "").strip()
    if hr_code:
        where_parts.append(f"hrCode LIKE '%{_nrql_escape(hr_code)}%'")

    customer_key = str(indicators.get("customerKey") or indicators.get("kKey") or "").strip()
    if customer_key:
        if customer_key.isdigit():
            where_parts.append(f"customerKey = {customer_key}")
        else:
            where_parts.append(f"customerKey LIKE '%{_nrql_escape(customer_key)}%'")

    company_key = str(indicators.get("companyKey") or indicators.get("fKey") or "").strip()
    if company_key:
        where_parts.append(f"companyKey LIKE '%{_nrql_escape(company_key)}%'")

    chain_id = str(indicators.get("chainId") or "").strip()
    if chain_id:
        where_parts.append(f"chainId LIKE '%{_nrql_escape(chain_id)}%'")

    if len(where_parts) <= 1:
        booking_source = str(indicators.get("bookingSource") or "").strip()
        if booking_source:
            where_parts.append(
                f"(bookingSource = '{_nrql_escape(booking_source)}' "
                f"OR message LIKE '%{_nrql_escape(booking_source)}%')"
            )

    return where_parts


def _extract_nrql_count(results: List[Dict[str, Any]]) -> int:
    if not results:
        return 0
    row = results[0] if isinstance(results[0], dict) else {}
    if not isinstance(row, dict):
        return 0
    for key in ("count", "count(*)"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return int(float(value))
        except Exception:
            continue
    for value in row.values():
        try:
            return int(float(value))
        except Exception:
            continue
    return 0


def build_nrql_diagnostics(
    indicators: Dict[str, Any],
    since_hours: int,
    account_id: int,
    api_key: str,
    graphql_url: str,
    tls_verify: Any,
    log_tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    tables = log_tables or DEFAULT_NR_LOG_TABLES
    from_clause = ", ".join(tables)
    filters = _build_nrql_filters(indicators)
    steps: List[Dict[str, Any]] = []
    active_filters: List[str] = []

    for index, predicate in enumerate(filters, start=1):
        active_filters.append(predicate)
        where_clause = " AND ".join(active_filters)
        nrql = (
            f"SELECT count(*) FROM {from_clause} "
            f"WHERE {where_clause} SINCE {int(since_hours)} hours ago"
        )
        try:
            results = query_new_relic_logs(
                account_id=account_id,
                api_key=api_key,
                nrql=nrql,
                graphql_url=graphql_url,
                tls_verify=tls_verify,
            )
            count = _extract_nrql_count(results)
            steps.append({
                "step": index,
                "filter": predicate,
                "count": count,
                "nrql": nrql,
            })
        except Exception as exc:
            steps.append({
                "step": index,
                "filter": predicate,
                "error": str(exc),
                "nrql": nrql,
            })
            break

    return {
        "from": tables,
        "steps": steps,
    }


def query_new_relic_logs(account_id: int, api_key: str, nrql: str, graphql_url: str, tls_verify: Any) -> List[Dict[str, Any]]:
    # Ensure the NRQL is a single flat line – New Relic rejects queries with
    # embedded newline characters even when they are valid JSON escapes (\n).
    nrql = re.sub(r"[\r\n]+", " ", nrql).strip()
    query = (
        "query($accountId:Int!, $nrql:Nrql!) {"
        " actor {"
        "  account(id: $accountId) {"
        "   nrql(query: $nrql) { results }"
        "  }"
        " }"
        "}"
    )
    payload = {
        "query": query,
        "variables": {
            "accountId": int(account_id),
            "nrql": nrql,
        },
    }
    headers = {
        "API-Key": api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(graphql_url, headers=headers, json=payload, timeout=45, verify=tls_verify)
    except requests.exceptions.SSLError as exc:
        raise RuntimeError(
            "TLS/SSL validation failed when connecting to New Relic. "
            "Set NEW_RELIC_CA_BUNDLE to your corporate CA bundle path, "
            "or as a last resort set NEW_RELIC_INSECURE=true for testing. "
            f"Original error: {exc}"
        ) from exc
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        if response.status_code == 401:
            raise RuntimeError(
                "New Relic returned 401 Unauthorized. Verify NEW_RELIC_API_KEY is a valid NerdGraph/User key "
                "(commonly starts with 'NRAK-') and NEW_RELIC_ACCOUNT_ID is correct for this key."
            ) from exc
        raise
    body = response.json()
    errors = body.get("errors")
    if errors:
        raise RuntimeError(f"New Relic query failed: {errors}")
    account_node = _safe_get(body, "data.actor.account")
    if account_node is None:
        raise RuntimeError(
            "New Relic returned no account data for the configured NEW_RELIC_ACCOUNT_ID. "
            f"accountId={account_id}. Verify the account id matches the one used in the New Relic UI and "
            "that the API key has access to that account."
        )
    return _safe_get(account_node, "nrql.results") or []


def _first_non_empty(values: Iterable[Any]) -> Optional[Any]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def summarize_new_relic(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not logs:
        return {
            "matched": 0,
            "successful": False,
            "successCount": 0,
            "failureCount": 0,
            "latest": {},
            "derived": {},
        }

    def _is_success(log: Dict[str, Any]) -> bool:
        status_candidates = [
            log.get("statusCode"),
            log.get("responseStatus"),
            log.get("status"),
        ]
        for status in status_candidates:
            if status is None:
                continue
            try:
                if int(status) == 200:
                    return True
            except Exception:
                if str(status).strip().upper() in {"OK", "SUCCESS", "200"}:
                    return True
        msg = str(log.get("message") or "").lower()
        return "success" in msg or "availableforsale" in msg

    sorted_logs = sorted(logs, key=lambda x: x.get("timestamp", 0), reverse=True)
    success_count = sum(1 for item in sorted_logs if _is_success(item))

    latest = sorted_logs[0]
    extracted = [_extract_log_fields(item) for item in sorted_logs]
    derived = {
        "museId": _first_non_empty(item.get("museId") for item in extracted),
        "hrCode": _first_non_empty(item.get("hrCode") for item in extracted),
        "hKey": _first_non_empty(item.get("hKey") for item in extracted),
        "chainId": _first_non_empty(item.get("chainId") for item in extracted),
        "bookingSource": _first_non_empty(item.get("bookingSource") for item in extracted),
        "customerKey": _first_non_empty(item.get("customerKey") for item in extracted),
        "kKey": _first_non_empty(item.get("kKey") for item in extracted),
        "companyKey": _first_non_empty(item.get("companyKey") for item in extracted),
        "fKey": _first_non_empty(item.get("fKey") for item in extracted),
        "arrivalDate": _first_non_empty(item.get("arrivalDate") for item in extracted),
        "departureDate": _first_non_empty(item.get("departureDate") for item in extracted),
        "rateAccessCodes": _first_non_empty(item.get("rateAccessCodes") for item in extracted),
        "hotelIdsForCIWhiteList": _first_non_empty(item.get("hotelIdsForCIWhiteList") for item in extracted),
    }

    if not derived.get("fKey") and derived.get("companyKey"):
        derived["fKey"] = derived["companyKey"]
    if not derived.get("companyKey") and derived.get("fKey"):
        derived["companyKey"] = derived["fKey"]
    if not derived.get("customerKey") and derived.get("kKey"):
        derived["customerKey"] = derived["kKey"]
    if not derived.get("kKey") and derived.get("customerKey"):
        derived["kKey"] = derived["customerKey"]

    return {
        "matched": len(sorted_logs),
        "successful": success_count > 0,
        "successCount": success_count,
        "failureCount": len(sorted_logs) - success_count,
        "latest": latest,
        "derived": derived,
    }


def build_singleavail_payload(indicators: Dict[str, Any], nr_summary: Dict[str, Any]) -> Dict[str, Any]:
    derived = nr_summary.get("derived", {})

    muse_id = str(_first_non_empty([derived.get("museId"), indicators.get("museId"), "AMADEUS"]))
    hr_code = _first_non_empty([derived.get("hrCode"), indicators.get("hrCode")])
    hr_code = _strip_outer_braces(hr_code)
    h_key = _first_non_empty([derived.get("hKey"), indicators.get("hKey")])
    chain_id = str(_first_non_empty([derived.get("chainId"), indicators.get("chainId"), "123"]))
    booking_source = str(_first_non_empty([derived.get("bookingSource"), indicators.get("bookingSource"), "13"]))
    customer_key = str(_first_non_empty([
        derived.get("customerKey"),
        derived.get("kKey"),
        derived.get("companyKey"),
        indicators.get("customerKey"),
        indicators.get("kKey"),
        indicators.get("companyKey"),
        "29908",
    ]))

    arrival_iso = _parse_date_to_iso_utc(_first_non_empty([derived.get("arrivalDate"), indicators.get("arrivalDate")]))
    departure_iso = _parse_date_to_iso_utc(_first_non_empty([derived.get("departureDate"), indicators.get("departureDate")]))

    if not arrival_iso:
        arrival_iso = (datetime.now(timezone.utc) + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    if not departure_iso:
        departure_iso = (datetime.now(timezone.utc) + timedelta(days=8)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")

    rate_access_codes = _first_non_empty([
        derived.get("rateAccessCodes"),
        indicators.get("rateAccessCodes"),
        ["HRQ", "SIE"],
    ])

    ci_whitelisted = _is_hr_code_ci_whitelisted(hr_code=hr_code, whitelist_value=derived.get("hotelIdsForCIWhiteList"))

    indicator_company_ids = indicators.get("companyIds") if isinstance(indicators.get("companyIds"), list) else []
    company_ids = [int(x) for x in indicator_company_ids if str(x).isdigit()]
    if not company_ids:
        company_ids = [int(customer_key)] if customer_key.isdigit() else [29908]

    hotels = [{
        "hrCode": hr_code,
        "hKey": h_key,
        "priority": None,
        "multisource": False,
        "chainId": chain_id,
        "ciWhitelisted": ci_whitelisted,
    }]

    return {
        "environment": "PROD",
        "museId": muse_id,
        "hotels": hotels,
        "arrivalDate": arrival_iso,
        "departureDate": departure_iso,
        "singleRooms": 1,
        "doubleRooms": 0,
        "adults": 1,
        "children": 0,
        "rateAccessCodes": rate_access_codes,
        "companyIds": company_ids,
        "corporateDiscountFlag": False,
        "bookingSource": booking_source,
        "customerKey": customer_key,
    }


def call_singleavail_api(url: str, payload: Dict[str, Any], bearer_token: Optional[str]) -> Dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if bearer_token:
        token = bearer_token.strip()
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    content_type = response.headers.get("Content-Type", "")
    body: Any
    if "application/json" in content_type:
        try:
            body = response.json()
        except Exception:
            body = response.text
    else:
        body = response.text

    return {
        "statusCode": response.status_code,
        "ok": response.ok,
        "headers": dict(response.headers),
        "body": body,
    }


def add_jira_comment(issue_key: str, jira_url: str, jira_pat: str, comment: str) -> Dict[str, Any]:
    url = f"{jira_url.rstrip('/')}/rest/api/2/issue/{issue_key}/comment"
    headers = {
        "Authorization": f"Bearer {jira_pat}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json={"body": comment}, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail: Any
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(
            f"Jira comment POST failed with status {response.status_code}: {detail}"
        ) from exc
    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = response.text
    return {
        "attempted": True,
        "posted": True,
        "statusCode": response.status_code,
        "commentLength": len(comment),
        "comment": comment,
        "response": payload,
    }


def upload_jira_attachment(
    issue_key: str,
    jira_url: str,
    jira_pat: str,
    file_path: str,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload file as Jira issue attachment."""
    url = f"{jira_url.rstrip('/')}/rest/api/2/issue/{issue_key}/attachments"
    headers = {
        "Authorization": f"Bearer {jira_pat}",
        "Accept": "application/json",
        "X-Atlassian-Token": "no-check",
    }
    actual_name = filename or os.path.basename(file_path)
    with open(file_path, "rb") as fh:
        files = {"file": (actual_name, fh, "application/json")}
        response = requests.post(url, headers=headers, files=files, timeout=60)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail: Any
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(
            f"Jira attachment upload failed with status {response.status_code}: {detail}"
        ) from exc

    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = response.text
    attachment_count = len(payload) if isinstance(payload, list) else None
    return {
        "attempted": True,
        "uploaded": True,
        "statusCode": response.status_code,
        "filename": actual_name,
        "attachmentCountFromResponse": attachment_count,
        "response": payload,
    }


def _normalize_comment_text(value: Any) -> str:
    text = _adf_to_text(value).strip().lower()
    return re.sub(r"\s+", " ", text)


def jira_comment_exists(issue: Dict[str, Any], needle: str) -> bool:
    if not needle:
        return False
    comments = _safe_get(issue, "fields.comment.comments") or []
    if not isinstance(comments, list):
        return False
    target = _normalize_comment_text(needle)
    for item in comments:
        if not isinstance(item, dict):
            continue
        raw = item.get("body")
        text = _normalize_comment_text(raw)
        if text == target or target in text:
            return True
    return False


def verify_jira_comment(issue_key: str, jira_url: str, jira_pat: str, comment: str) -> Dict[str, Any]:
    refreshed_issue = fetch_jira_issue(issue_key=issue_key, jira_url=jira_url, jira_pat=jira_pat)
    exists = jira_comment_exists(refreshed_issue, comment)
    comments = _safe_get(refreshed_issue, "fields.comment.comments") or []
    return {
        "verifiedOnRefresh": bool(exists),
        "commentCount": len(comments) if isinstance(comments, list) else None,
    }


def jira_attachment_exists(issue: Dict[str, Any], filename: str) -> bool:
    if not filename:
        return False
    attachments = _safe_get(issue, "fields.attachment") or []
    if not isinstance(attachments, list):
        return False
    target = str(filename).strip().lower()
    for item in attachments:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filename") or "").strip().lower()
        if name == target:
            return True
    return False


def verify_jira_attachment(issue_key: str, jira_url: str, jira_pat: str, filename: str) -> Dict[str, Any]:
    refreshed_issue = fetch_jira_issue(issue_key=issue_key, jira_url=jira_url, jira_pat=jira_pat)
    attachments = _safe_get(refreshed_issue, "fields.attachment") or []
    return {
        "verifiedOnRefresh": jira_attachment_exists(refreshed_issue, filename),
        "attachmentCount": len(attachments) if isinstance(attachments, list) else None,
    }


def _normalize_jsonish_for_comment(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = _parse_json_maybe(value)
        if parsed is not None and parsed is not value:
            return _normalize_jsonish_for_comment(parsed)
        return value
    if isinstance(value, list):
        return [_normalize_jsonish_for_comment(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_jsonish_for_comment(val) for key, val in value.items()}
    return value


def _serialize_for_comment(value: Any) -> str:
    normalized = _normalize_jsonish_for_comment(value)
    if normalized is None:
        return "null"
    if isinstance(normalized, str):
        return normalized
    try:
        return json.dumps(normalized, indent=2, ensure_ascii=False)
    except Exception:
        return str(normalized)


def _jira_attachment_link(filename: str, label: Optional[str] = None) -> str:
    """Return Jira wiki markup for an issue attachment link."""
    name = str(filename or "").strip()
    if not name:
        return ""
    text = str(label or "").strip()
    if text:
        return f"[{text}|^{name}]"
    return f"[^{name}]"


def _split_text_into_chunks(text: str, max_length: int) -> List[str]:
    if max_length <= 0:
        raise ValueError("max_length must be greater than zero")
    if not text:
        return [""]

    remaining = text
    chunks: List[str] = []
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, max_length + 1)
        if split_at <= 0:
            split_at = max_length
            chunk = remaining[:split_at]
            remaining = remaining[split_at:]
        else:
            chunk = remaining[:split_at]
            remaining = remaining[split_at + 1 :]

        chunks.append(chunk)

    return chunks


def build_open_status_jira_comments(
    payload: Dict[str, Any],
    attachment_note: Optional[str] = None,
) -> List[str]:
    payload_json = _serialize_for_comment({"singleAvailPayload": payload})
    note = attachment_note or "SingleAvail response JSON is attached to this ticket as a file."

    comment = (
        "Hi Team,\n\n"
        "SingleAvail response indicates status OPEN for this request. The hotel is available/bookable.\n\n"
        "{code:json}\n"
        f"{payload_json}\n"
        "{code}\n\n"
        "Tester UI: http://crsui.pec.hrs.cc:4202/tester\n"
        "Use the above request payload to see the response.\n"
        f"{note}\n\n"
        "Regards,\n"
        "JiraAzureCopilot"
    )

    if len(comment) > MAX_JIRA_COMMENT_CHARS:
        # Keep one tidy comment by trimming payload block when Jira size limits are exceeded.
        payload_json = _serialize_for_comment(
            {"singleAvailPayload": "[truncated: payload exceeds Jira comment limit]"}
        )
        comment = (
            "Hi Team,\n\n"
            "SingleAvail response indicates status OPEN for this request. The hotel is available/bookable.\n\n"
            "{code:json}\n"
            f"{payload_json}\n"
            "{code}\n\n"
            "Tester UI: http://crsui.pec.hrs.cc:4202/tester\n"
            "Use the above request payload to see the response.\n"
            f"{note}\n\n"
            "Regards,\n"
            "JiraAzureCopilot"
        )

    return [comment]


def post_jira_comments(
    issue_key: str,
    jira_url: str,
    jira_pat: str,
    issue: Dict[str, Any],
    comments: List[str],
) -> Dict[str, Any]:
    comment_results: List[Dict[str, Any]] = []
    refreshed_issue = issue

    comments_node = _safe_get(refreshed_issue, "fields.comment.comments")
    if not isinstance(comments_node, list):
        fields = refreshed_issue.setdefault("fields", {}) if isinstance(refreshed_issue, dict) else {}
        comment_field = fields.setdefault("comment", {}) if isinstance(fields, dict) else {}
        comments_node = comment_field.setdefault("comments", []) if isinstance(comment_field, dict) else []

    for index, comment in enumerate(comments, start=1):
        if jira_comment_exists(refreshed_issue, comment):
            comment_results.append(
                {
                    "index": index,
                    "attempted": False,
                    "posted": False,
                    "duplicate": True,
                    "commentLength": len(comment),
                    "reason": "matching Jira comment already exists",
                    "comment": comment,
                }
            )
            continue

        try:
            post_result = add_jira_comment(
                issue_key=issue_key,
                jira_url=jira_url,
                jira_pat=jira_pat,
                comment=comment,
            )
            if isinstance(comments_node, list):
                comments_node.append({"body": comment})
            post_result.update({"index": index, "verifiedOnRefresh": None})
            comment_results.append(post_result)
        except Exception as exc:
            comment_results.append(
                {
                    "index": index,
                    "attempted": True,
                    "posted": False,
                    "duplicate": False,
                    "commentLength": len(comment),
                    "error": str(exc),
                    "comment": comment,
                }
            )

    refresh_attempted = False
    refresh_succeeded = False
    refresh_error: Optional[str] = None
    try:
        refresh_attempted = True
        refreshed_issue = fetch_jira_issue(issue_key=issue_key, jira_url=jira_url, jira_pat=jira_pat)
        refresh_succeeded = True
        for item in comment_results:
            if item.get("posted"):
                item["verifiedOnRefresh"] = jira_comment_exists(refreshed_issue, item.get("comment", ""))
    except Exception as exc:
        refresh_error = str(exc)

    attempted = any(item.get("attempted") for item in comment_results)
    posted_count = sum(1 for item in comment_results if item.get("posted"))
    duplicate_count = sum(1 for item in comment_results if item.get("duplicate"))
    failed_items = [item for item in comment_results if item.get("attempted") and not item.get("posted")]
    posted_items = [item for item in comment_results if item.get("posted")]
    if refresh_succeeded:
        verified_on_refresh: Optional[bool] = all(item.get("verifiedOnRefresh") for item in posted_items)
    else:
        verified_on_refresh = None

    return {
        "attempted": attempted,
        "posted": not failed_items and bool(comment_results),
        "commentPlanCount": len(comments),
        "commentPostedCount": posted_count,
        "commentDuplicateCount": duplicate_count,
        "comments": comment_results,
        "verifiedOnRefresh": verified_on_refresh,
        "refreshAttempted": refresh_attempted,
        "refreshSucceeded": refresh_succeeded,
        "refreshError": refresh_error,
        "commentCount": len(_safe_get(refreshed_issue, "fields.comment.comments") or [])
        if isinstance(_safe_get(refreshed_issue, "fields.comment.comments"), list)
        else None,
    }


def _singleavail_has_open_status(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        status_node = value.get("status")
        if isinstance(status_node, dict):
            if str(status_node.get("name") or "").strip().upper() == "OPEN":
                return True
        for nested in value.values():
            if _singleavail_has_open_status(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_singleavail_has_open_status(item) for item in value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        parsed = _parse_json_maybe(text)
        if parsed is not None and parsed is not value:
            return _singleavail_has_open_status(parsed)
        compact = re.sub(r"\s+", "", text).replace('\\"', '"').lower()
        return '"status":{"name":"open"' in compact
    return False


def _missing_core_filter_groups(indicators: Dict[str, Any]) -> List[str]:
    """Return missing core identifiers required for reliable NRQL filtering.

    Notes:
      - arrival/departure/museId/bookingSource are intentionally not treated as
        sufficient by themselves.
      - Alias pairs are accepted (customerKey|kKey, companyKey|fKey).
    """
    groups = [
        ("hrCode", "hrCode"),
        ("hKey", "hKey"),
        ("chainId", "chainId"),
        ("customerKey/kKey", "customerKey", "kKey"),
        ("companyKey/fKey", "companyKey", "fKey"),
    ]

    missing: List[str] = []
    for group in groups:
        label, *keys = group
        present = False
        for key in keys:
            value = indicators.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            present = True
            break
        if not present:
            missing.append(label)
    return missing


def _build_missing_fields_jira_comment(missing_core_fields: List[str]) -> str:
    missing_lines = "\n".join(f"- {item}" for item in missing_core_fields)
    return (
        "Hi Team,\n\n"
        "JiraAzureCopilot could not run reliable New Relic analysis because core filtering fields are missing.\n\n"
        "Please update the ticket description/comments with these fields:\n"
        f"{missing_lines}\n\n"
        "(arrivalDate/departureDate/museId/bookingSource alone are not sufficient for this workflow.)\n\n"
        "Once added, re-run analysis.\n\n"
        "Regards,\n"
        "JiraAzureCopilot"
    )


def run(
    issue_key: str,
    since_hours: int,
    execute_api: bool,
    output_path: Optional[str],
    comment_jira: bool = True,
    preview_jira_comment: bool = True,
) -> Dict[str, Any]:
    load_dotenv()

    jira_url = os.getenv("JIRA_URL", "").strip()
    jira_pat = os.getenv("JIRA_PAT", "").strip()
    nr_api_key = os.getenv("NEW_RELIC_API_KEY", "").strip()
    nr_account_id = os.getenv("NEW_RELIC_ACCOUNT_ID", "").strip()
    nr_graphql_url = resolve_new_relic_graphql_url(
        graphql_url=os.getenv("NEW_RELIC_GRAPHQL_URL", "").strip(),
        log_api_url=os.getenv("NEW_RELIC_LOG_API_URL", "").strip(),
    )
    nr_tls_verify = resolve_tls_verify(
        ca_bundle=os.getenv("NEW_RELIC_CA_BUNDLE", "").strip(),
        insecure=os.getenv("NEW_RELIC_INSECURE", "").strip(),
    )

    # Configurable log table list (comma-separated env var)
    nr_log_tables_raw = os.getenv("NEW_RELIC_LOG_TABLES", "").strip()
    nr_log_tables: Optional[List[str]] = (
        [t.strip() for t in nr_log_tables_raw.split(",") if t.strip()]
        if nr_log_tables_raw
        else None
    )

    if not jira_url or not jira_pat:
        raise RuntimeError("Missing JIRA_URL or JIRA_PAT in environment")
    if not nr_api_key or not nr_account_id:
        raise RuntimeError("Missing NEW_RELIC_API_KEY or NEW_RELIC_ACCOUNT_ID in environment")

    issue = fetch_jira_issue(issue_key=issue_key, jira_url=jira_url, jira_pat=jira_pat)
    indicators = parse_ticket_indicators(issue)

    missing_core_fields = _missing_core_filter_groups(indicators)
    missing_filter_inputs = len(missing_core_fields) == 5

    jira_comment_result: Optional[Dict[str, Any]] = {
        "attempted": False,
        "posted": False,
        "reason": "Jira comment skipped because EC2 API call was not requested",
    }

    if missing_filter_inputs:
        missing_fields_comment = _build_missing_fields_jira_comment(missing_core_fields)
        if comment_jira:
            if jira_comment_exists(issue, missing_fields_comment):
                jira_comment_result = {
                    "attempted": False,
                    "posted": False,
                    "reason": "missing-fields guidance comment already exists",
                    "comment": missing_fields_comment,
                }
            else:
                try:
                    jira_comment_result = add_jira_comment(
                        issue_key=issue_key,
                        jira_url=jira_url,
                        jira_pat=jira_pat,
                        comment=missing_fields_comment,
                    )
                except Exception as exc:
                    jira_comment_result = {
                        "attempted": True,
                        "posted": False,
                        "error": str(exc),
                        "comment": missing_fields_comment,
                    }
        elif preview_jira_comment:
            jira_comment_result = {
                "attempted": False,
                "posted": False,
                "dryRun": True,
                "reason": "Jira comment posting disabled for this run",
                "commentPlanCount": 1,
                "comments": [missing_fields_comment],
            }
        else:
            jira_comment_result = {
                "attempted": False,
                "posted": False,
                "dryRun": True,
                "reason": "Jira comment flow disabled for this run",
            }

        nr_summary = {
            "matched": 0,
            "successful": False,
            "successCount": 0,
            "failureCount": 0,
            "latest": {},
            "derived": {},
            "skipped": True,
            "skipReason": "Missing investigation fields in ticket; NRQL query skipped to avoid broad fallback search.",
            "missingCoreFilterFields": missing_core_fields,
        }
        singleavail_execution = {
            "requested": bool(execute_api),
            "performed": False,
            "reason": "EC2 API call skipped because required ticket fields are missing",
        }
        result = {
            "ticket": {
                "key": issue.get("key"),
                "summary": _safe_get(issue, "fields.summary"),
                "url": f"{jira_url.rstrip('/')}/browse/{issue.get('key')}",
            },
            "indicators": indicators,
            "newRelic": {
                "accountId": int(nr_account_id),
                "graphqlUrl": nr_graphql_url,
                "tlsVerify": nr_tls_verify,
                "nrql": None,
                "summary": nr_summary,
                "diagnostics": None,
                "sampleCount": 0,
                "sample": [],
            },
            "singleAvailPayload": None,
            "singleAvailExecution": singleavail_execution,
            "singleAvailResponse": None,
            "jiraComment": jira_comment_result,
        }
        if output_path:
            with open(output_path, "w", encoding="utf-8") as fp:
                json.dump(result, fp, indent=2)
        return result

    nrql = build_nrql(indicators, since_hours=since_hours, log_tables=nr_log_tables)
    logs = query_new_relic_logs(
        account_id=int(nr_account_id),
        api_key=nr_api_key,
        nrql=nrql,
        graphql_url=nr_graphql_url,
        tls_verify=nr_tls_verify,
    )
    nr_summary = summarize_new_relic(logs)
    nr_diagnostics: Optional[Dict[str, Any]] = None
    if not logs:
        nr_diagnostics = build_nrql_diagnostics(
            indicators=indicators,
            since_hours=since_hours,
            account_id=int(nr_account_id),
            api_key=nr_api_key,
            graphql_url=nr_graphql_url,
            tls_verify=nr_tls_verify,
            log_tables=nr_log_tables,
        )

    payload = build_singleavail_payload(indicators=indicators, nr_summary=nr_summary)

    api_result = None
    singleavail_execution: Dict[str, Any] = {
        "requested": bool(execute_api),
        "performed": False,
        "reason": "EC2 API call not requested (--execute-api not provided)",
    }
    if execute_api:
        api_url = os.getenv("EC2_SINGLEAVAIL_URL", DEFAULT_SINGLEAVAIL_URL).strip()
        bearer = os.getenv("EC2_BEARER_TOKEN", "").strip() or None
        api_result = call_singleavail_api(url=api_url, payload=payload, bearer_token=bearer)
        singleavail_execution = {
            "requested": True,
            "performed": True,
            "reason": None,
        }
        if api_result.get("ok") and _singleavail_has_open_status(api_result.get("body")):
            if not comment_jira:
                if preview_jira_comment:
                    comments = build_open_status_jira_comments(
                        payload=payload,
                        attachment_note="SingleAvail response JSON will be attached when Jira comment posting is enabled.",
                    )
                    jira_comment_result = {
                        "attempted": False,
                        "posted": False,
                        "dryRun": True,
                        "reason": "Jira comment posting disabled for this run",
                        "commentPlanCount": len(comments),
                        "comments": comments,
                    }
                else:
                    jira_comment_result = {
                        "attempted": False,
                        "posted": False,
                        "dryRun": True,
                        "reason": "Jira comment flow disabled for this run",
                    }
            else:
                attachment_result: Dict[str, Any] = {
                    "attempted": False,
                    "uploaded": False,
                    "reason": "response attachment upload not attempted",
                }
                attachment_note = "SingleAvail response JSON upload is pending for this ticket."

                # Store response to temp JSON and upload as Jira attachment.
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                attachment_filename = f"singleavail-response-{issue_key}-{timestamp}.json"
                response_attachment_payload = {
                    "singleAvailResponse": {
                        "statusCode": api_result.get("statusCode"),
                        "ok": api_result.get("ok"),
                        "body": _normalize_jsonish_for_comment(api_result.get("body")),
                    }
                }
                temp_path: Optional[str] = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", suffix=".json", delete=False
                    ) as tmp:
                        temp_path = tmp.name
                        tmp.write(_serialize_for_comment(response_attachment_payload))
                    attachment_result = upload_jira_attachment(
                        issue_key=issue_key,
                        jira_url=jira_url,
                        jira_pat=jira_pat,
                        file_path=temp_path,
                        filename=attachment_filename,
                    )
                    try:
                        verification = verify_jira_attachment(
                            issue_key=issue_key,
                            jira_url=jira_url,
                            jira_pat=jira_pat,
                            filename=attachment_filename,
                        )
                    except Exception as verify_exc:
                        verification = {
                            "verifiedOnRefresh": False,
                            "verificationError": str(verify_exc),
                        }
                    attachment_result["verification"] = verification
                    if verification.get("verifiedOnRefresh"):
                        attachment_link = _jira_attachment_link(
                            attachment_filename,
                            label="SingleAvailResponse.json",
                        )
                        attachment_note = (
                            f"SingleAvail response JSON is attached to this ticket. {attachment_link}"
                        )
                    else:
                        attachment_result["uploaded"] = False
                        attachment_result["reason"] = "attachment upload could not be verified on Jira refresh"
                        attachment_note = (
                            f"SingleAvail response attachment upload was attempted for `{attachment_filename}`, "
                            "but Jira did not confirm the file on refresh."
                        )
                except Exception as exc:
                    attachment_result = {
                        "attempted": True,
                        "uploaded": False,
                        "error": str(exc),
                        "filename": attachment_filename,
                    }
                    attachment_note = (
                        "SingleAvail response attachment upload failed in this run. "
                        "Please re-run to upload response JSON."
                    )
                finally:
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

                comments = build_open_status_jira_comments(payload=payload, attachment_note=attachment_note)
                if len(comments) == 1 and jira_comment_exists(issue, comments[0]):
                    jira_comment_result = {
                        "attempted": False,
                        "posted": False,
                        "reason": "duplicate OPEN-status EC2 response comment already exists",
                        "comment": comments[0],
                        "attachment": attachment_result,
                    }
                else:
                    try:
                        jira_comment_result = post_jira_comments(
                            issue_key=issue_key,
                            jira_url=jira_url,
                            jira_pat=jira_pat,
                            issue=issue,
                            comments=comments,
                        )
                        jira_comment_result["attachment"] = attachment_result
                    except Exception as exc:
                        jira_comment_result = {
                            "attempted": True,
                            "posted": False,
                            "error": str(exc),
                            "comments": comments,
                            "attachment": attachment_result,
                        }
        elif execute_api:
            jira_comment_result = {
                "attempted": False,
                "posted": False,
                "reason": "singleavail response does not contain status.name=OPEN",
            }

    result = {
        "ticket": {
            "key": issue.get("key"),
            "summary": _safe_get(issue, "fields.summary"),
            "url": f"{jira_url.rstrip('/')}/browse/{issue.get('key')}",
        },
        "indicators": indicators,
        "newRelic": {
            "accountId": int(nr_account_id),
            "graphqlUrl": nr_graphql_url,
            "tlsVerify": nr_tls_verify,
            "nrql": nrql,
            "summary": nr_summary,
            "diagnostics": nr_diagnostics,
            "sampleCount": len(logs),
            "sample": logs[:5],
        },
        "singleAvailPayload": payload,
        "singleAvailExecution": singleavail_execution,
        "singleAvailResponse": api_result,
        "jiraComment": jira_comment_result,
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as fp:
            json.dump(result, fp, indent=2)

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze hotel-unavailable support tickets with Jira + New Relic")
    parser.add_argument("--issue-key", required=True, help="Jira issue key, e.g. CRSUP-4421")
    parser.add_argument("--since-hours", type=int, default=24, help="New Relic lookback window in hours")
    parser.add_argument("--execute-api", action="store_true", help="Call EC2 singleavail endpoint with derived payload")
    parser.add_argument("--output", help="Optional JSON file path for full analysis output")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    result = run(
        issue_key=args.issue_key,
        since_hours=args.since_hours,
        execute_api=args.execute_api,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

