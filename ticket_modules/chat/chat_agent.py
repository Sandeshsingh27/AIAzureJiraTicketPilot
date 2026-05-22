"""
Copilot-style chat agent that uses Jira MCP tools via OpenAI function-calling.
Backed by GitHub Models (gpt-4o-mini).
"""
import os
import json
import re
import requests
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from ticket_modules.support_ticket_analyzer import run as run_support_ticket_analysis

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")
JIRA_PAT = os.getenv("JIRA_PAT", "")
JIRA_HEADERS = {
    "Authorization": f"Bearer {JIRA_PAT}",
    "Content-Type":  "application/json",
    "Accept":        "application/json",
}

_client = OpenAI(
    base_url=os.getenv("AI_BASE_URL", "https://models.inference.ai.azure.com"),
    api_key=os.getenv("GITHUB_TOKEN"),
)
_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

# Projects this chat agent is allowed to operate on
ALLOWED_PROJECTS = ["CRSUP", "SWPSUP"]
_PROJECT_CLAUSE = "project in ({})".format(", ".join(ALLOWED_PROJECTS))

# Per-project terminal-status exclusions (do NOT return these)
EXCLUDED_STATUSES = {
    "CRSUP":  ["Closed"],
    "SWPSUP": ["Resolved"],
}
# Build: NOT ((project=CRSUP AND status in (Closed)) OR (project=SWPSUP AND status in (Resolved)))
def _build_status_exclusion_clause():
    parts = []
    for proj, statuses in EXCLUDED_STATUSES.items():
        if not statuses:
            continue
        s = ", ".join('"{}"'.format(st) for st in statuses)
        parts.append('(project = "{}" AND status in ({}))'.format(proj, s))
    if not parts:
        return ""
    return "NOT (" + " OR ".join(parts) + ")"

_STATUS_CLAUSE = _build_status_exclusion_clause()
_SCOPE_CLAUSE  = _PROJECT_CLAUSE + (" AND " + _STATUS_CLAUSE if _STATUS_CLAUSE else "")

KEYWORDS_FILE = Path(__file__).resolve().parents[2] / "ticket_analysis_keywords.json"


def _load_availability_keywords() -> list[str]:
    defaults = ["hotel not available", "hotel unavailable", "hotel not bookable"]
    try:
        payload = json.loads(KEYWORDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    raw = payload.get("availabilityKeywords") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return defaults
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text.lower() not in [x.lower() for x in out]:
            out.append(text)
    return out or defaults

SYSTEM_PROMPT = (
    "You are JiraCopilot — a helpful assistant scoped to the Jira projects "
    f"{', '.join(ALLOWED_PROJECTS)} only. "
    "Use the provided tools to search, fetch, create, comment on, and link Jira issues. "
    f"All JQL searches MUST include `{_PROJECT_CLAUSE}` (the backend also enforces this). "
    "The backend ALSO excludes terminal-status tickets: CRSUP tickets with status 'Closed' "
    "and SWPSUP tickets with status 'Resolved' are filtered out automatically. "
    "All created issues MUST use one of these project keys. "
    "When the user asks for 'similar issues', 'related tickets', or any natural-language "
    "topic (e.g. 'duplicate bookings', 'hotel unavailability', 'price mismatch', "
    "'payment failure', 'wrong rate', 'no rooms available') — ALWAYS use the "
    "`search_concept` tool, NOT `search_issues`. "
    "You yourself must generate 4–10 phrase variants and pass them as the `phrases` list. "
    "Cover singular/plural, synonyms, morphological forms, and natural word-order swaps. "
    "Examples of good variant sets:\n"
    "  • 'duplicate bookings' → ['duplicate booking', 'duplicate bookings', "
    "    'duplicated booking', 'duplicate reservation', 'duplicate reservations', "
    "    'double booking', 'double bookings', 'booked twice']\n"
    "  • 'hotel unavailability' → ['hotel unavailable', 'hotel unavailability', "
    "    'hotel not available', 'unavailable hotel', 'no hotel available', "
    "    'property unavailable']\n"
    "  • 'price mismatch' → ['price mismatch', 'rate mismatch', 'price discrepancy', "
    "    'wrong price', 'wrong rate', 'incorrect price', 'incorrect rate', 'price difference']\n"
    "  • 'payment failure' → ['payment failure', 'payment failed', 'payment error', "
    "    'payment declined', 'payment unsuccessful', 'failed payment', 'payment issue']\n"
    "  • 'cancellation issue' → ['cancellation failed', 'cancel failed', 'unable to cancel', "
    "    'cancellation not working', 'cancellation error', 'cancel not working']\n"
    "  • 'room category' → ['room category', 'room type', 'wrong room category', "
    "    'incorrect room type', 'room category mismatch']\n"
    "General synonym hints you may use anywhere:\n"
    "  booking↔reservation, hotel↔property, price↔rate, duplicate↔double↔duplicated, "
    "  missing↔not found, failure↔failed↔error, unable to X↔cannot X↔X not working, "
    "  wrong↔incorrect↔invalid, unavailable↔not available↔out of stock\n"
    "Always include the user's original phrasing in the list. "
    "Use raw `search_issues` ONLY when the user explicitly gives you JQL, or asks for things "
    "like 'all open P1 tickets' that don't need phrase matching. "
    "For end-to-end hotel-unavailable or hotel-not-bookable investigations (Jira context + New Relic checks + singleavail payload), "
    "use the `analyze_support_ticket` tool. "
    "\n"
    "When you DO use raw `search_issues` with text/summary searches, the same rules apply: "
    "use the escaped-quote exact-phrase form `text ~ \"\\\"hotel unavailable\\\"\"`. "
    "The backend auto-rewrites loose multi-word values into the exact-phrase form and will "
    "even retry with morphological variants on a zero-result single-phrase query — but "
    "`search_concept` is always the better first choice for topical queries. "
    "When asked to 'create a main ticket and link them' (or 'consolidated ticket', 'parent ticket', etc.), "
    "follow these steps STRICTLY:\n"
    "  1. Search for matching tickets.\n"
    "  2. Confirm matches with the user if needed.\n"
    "  3. Call `create_issue` EXACTLY ONCE. Store the key returned (e.g. CRSUP-XXXX). "
    "     NEVER call `create_issue` a second time — if you see a key was already created in "
    "     the tool result history, use THAT key. Calling `create_issue` twice creates "
    "     unwanted duplicate tickets.\n"
    "  3b. If the user specified an assignee (e.g. 'assign to nsh50'), pass the `assignee` "
    "     parameter directly in `create_issue`. If the user mentions assigning AFTER creation, "
    "     call `assign_issue` with the created key and the username.\n"
    "  4. Description should describe the theme only — "
    "     do NOT embed sub-ticket keys or URLs in the description.\n"
    "  5. For EVERY sub-ticket, call `link_issues` with inwardIssue=<consolidated key from step 3>, "
    "     outwardIssue=<sub-ticket key>, linkType='Relates'.\n"
    "  6. The relationship MUST be recorded exclusively via `link_issues` so it appears "
    "     under 'Issue Links → Relates to' in Jira, NOT as plain text in the description.\n"
    "  7. After all links are created, summarise which keys were linked.\n"
    "If the user asks about a ticket key from a different project, politely refuse and explain "
    f"that you only operate on {', '.join(ALLOWED_PROJECTS)}. "
    "Be concise. Show ticket keys as plain text (e.g. CRSUP-1234) — the UI will linkify them. "
    "After every action, briefly summarize what you did and list affected keys."
)

# ─── Tool implementations ─────────────────────────────────────────────────────

def _jira_get(path):
    r = requests.get(f"{JIRA_URL}{path}", headers=JIRA_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()

def _jira_post(path, payload):
    r = requests.post(f"{JIRA_URL}{path}", headers=JIRA_HEADERS, json=payload, timeout=20)
    r.raise_for_status()
    return r.json() if r.text else {}


def _key_is_allowed(key: str) -> bool:
    if not key or "-" not in key:
        return False
    proj = key.split("-", 1)[0].upper()
    return proj in ALLOWED_PROJECTS


def _rewrite_multiword_text(jql: str) -> str:
    """
    Convert loose multi-word text searches into EXACT-PHRASE form so the words
    must appear consecutively (not just both present anywhere in the ticket).

    Examples:
      text ~ "hotel unavailable"      ->  text ~ "\\"hotel unavailable\\""
      summary ~ "wrong hotel rate"    ->  summary ~ "\\"wrong hotel rate\\""
      text ~ "\\"hotel unavailable\\""->  unchanged (already exact-phrase)
      text ~ "hotel"                  ->  unchanged (single word)

    Why: with bare `text ~ "hotel unavailable"`, Jira tokenizes and effectively
    ORs the words. Even AND-joining each word ('hotel' AND 'unavailable') can
    still match tickets like 'service unavailable' that also mention 'hotel'
    elsewhere. The escaped-quote form forces an exact phrase match.
    """
    if not jql:
        return jql

    pattern = re.compile(
        r'(\b(?:text|summary|description|comment)\b)\s*~\s*"([^"]+)"',
        re.IGNORECASE,
    )

    def _repl(m):
        field = m.group(1)
        value = m.group(2).strip()
        # already an exact-phrase search (escaped quotes inside): leave as-is
        if value.startswith('\\"') and value.endswith('\\"'):
            return m.group(0)
        words = [w for w in re.split(r'\s+', value) if w]
        if len(words) <= 1:
            return m.group(0)
        phrase = " ".join(words)
        # Build: field ~ "\"hotel unavailable\""
        return f'{field} ~ "\\"{phrase}\\""'

    return pattern.sub(_repl, jql)


def _enforce_jql_scope(jql: str) -> str:
    """Wrap the user's JQL so it can only return issues from ALLOWED_PROJECTS,
    excludes terminal-status tickets (CRSUP=Closed, SWPSUP=Resolved),
    and rewrites multi-word text searches into exact-phrase form."""
    jql = _rewrite_multiword_text((jql or "").strip())
    if not jql:
        return _SCOPE_CLAUSE
    if "order by" in jql.lower():
        idx = jql.lower().rfind("order by")
        head, tail = jql[:idx].strip(), jql[idx:].strip()
        return f"({head}) AND {_SCOPE_CLAUSE} {tail}"
    return f"({jql}) AND {_SCOPE_CLAUSE}"


def tool_search_issues(jql: str, maxResults: int = 10):
    """Raw JQL search. For concept/topic searches use tool_search_concept instead."""
    safe_jql = _enforce_jql_scope(jql)
    payload = {"jql": safe_jql, "maxResults": int(maxResults),
               "fields": ["summary", "status", "priority", "assignee"]}
    data = _jira_post("/rest/api/2/search", payload)
    out = []
    for i in data.get("issues", []):
        f = i.get("fields", {})
        out.append({
            "key":      i.get("key"),
            "summary":  f.get("summary"),
            "status":   (f.get("status") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "assignee": (f.get("assignee") or {}).get("displayName"),
        })
    return {"count": len(out), "issues": out, "effective_jql": safe_jql}

def tool_get_issue(issueKey: str):
    if not _key_is_allowed(issueKey):
        return {"error": f"Refused: {issueKey} is outside allowed projects {ALLOWED_PROJECTS}."}
    data = _jira_get(f"/rest/api/2/issue/{issueKey}")
    f = data.get("fields", {})
    status_name = (f.get("status") or {}).get("name")
    proj_key = (issueKey.split("-", 1)[0]).upper()
    if status_name in EXCLUDED_STATUSES.get(proj_key, []):
        return {"error": f"Refused: {issueKey} has terminal status '{status_name}' "
                          f"which is excluded for project {proj_key}."}
    return {
        "key": data.get("key"),
        "summary": f.get("summary"),
        "description": (f.get("description") or "")[:1500],
        "status": status_name,
        "priority": (f.get("priority") or {}).get("name"),
        "assignee": (f.get("assignee") or {}).get("displayName"),
        "reporter": (f.get("reporter") or {}).get("displayName"),
    }

def tool_create_issue(project: str, summary: str, issueType: str = "Task",
                      description: str = "", assignee: str = ""):
    if (project or "").upper() not in ALLOWED_PROJECTS:
        return {"error": f"Refused: project '{project}' not in allowed list {ALLOWED_PROJECTS}."}
    payload = {"fields": {
        "project":   {"key": project.upper()},
        "summary":   summary,
        "issuetype": {"name": issueType},
    }}
    if description:
        payload["fields"]["description"] = description
    if assignee:
        payload["fields"]["assignee"] = {"name": assignee}
    data = _jira_post("/rest/api/2/issue", payload)
    key = data.get("key")
    return {"created": key, "url": f"{JIRA_URL}/browse/{key}", "assignee": assignee or None}

def tool_add_comment(issueKey: str, comment: str):
    if not _key_is_allowed(issueKey):
        return {"error": f"Refused: {issueKey} is outside allowed projects {ALLOWED_PROJECTS}."}
    data = _jira_post(f"/rest/api/2/issue/{issueKey}/comment", {"body": comment})
    return {"id": data.get("id"), "issueKey": issueKey, "status": "added"}

def tool_assign_issue(issueKey: str, assignee: str):
    """Assign (or re-assign) a Jira issue to a user by their Jira username."""
    if not _key_is_allowed(issueKey):
        return {"error": f"Refused: {issueKey} is outside allowed projects {ALLOWED_PROJECTS}."}
    import requests as _req
    r = _req.put(
        f"{JIRA_URL}/rest/api/2/issue/{issueKey}/assignee",
        headers=JIRA_HEADERS,
        json={"name": assignee},
        timeout=20,
    )
    r.raise_for_status()
    return {"issueKey": issueKey, "assignee": assignee, "status": "assigned"}

def tool_link_issues(inwardIssue: str, outwardIssue: str, linkType: str = "Relates"):
    """Create a Jira issue link. linkType examples: 'Relates', 'Blocks', 'Duplicate'."""
    if not _key_is_allowed(inwardIssue) or not _key_is_allowed(outwardIssue):
        return {"error": f"Refused: both keys must belong to {ALLOWED_PROJECTS}."}
    payload = {
        "type":         {"name": linkType},
        "inwardIssue":  {"key": inwardIssue},
        "outwardIssue": {"key": outwardIssue},
    }
    r = requests.post(f"{JIRA_URL}/rest/api/2/issueLink",
                      headers=JIRA_HEADERS, json=payload, timeout=20)
    r.raise_for_status()
    return {"linked": True, "from": inwardIssue, "to": outwardIssue, "type": linkType}


def tool_search_concept(phrases: list, field: str = "text",
                        extraJql: str = "", maxResults: int = 20):
    """
    Concept-based search: caller supplies a list of phrase variants describing
    the SAME concept (e.g. duplicate bookings -> ['duplicate booking',
    'duplicate bookings', 'duplicated reservation', 'double booking']).
    Backend ORs them all as EXACT-PHRASE matches against `field` (text|summary|
    description|comment), then ANDs the project scope clause and any extraJql.

    Example call (from the LLM):
      search_concept(
        phrases=["duplicate booking","duplicate bookings","double booking",
                 "duplicated reservation","duplicate reservation"],
        field="text", extraJql="resolution = Unresolved", maxResults=20
      )
    """
    if not phrases or not isinstance(phrases, list):
        return {"error": "phrases must be a non-empty list of strings"}
    field = (field or "text").lower()
    if field not in ("text", "summary", "description", "comment"):
        return {"error": f"unsupported field '{field}'"}

    # de-dup + lowercase
    seen, clean = set(), []
    for p in phrases:
        p = (p or "").strip()
        k = p.lower()
        if p and k not in seen:
            seen.add(k); clean.append(p)
    if not clean:
        return {"error": "no usable phrases"}

    or_block = " OR ".join(f'{field} ~ "\\"{p}\\""' for p in clean)
    jql = f"({or_block})"
    if extraJql.strip():
        jql += f" AND ({extraJql.strip()})"

    safe_jql = _enforce_jql_scope(jql)
    payload = {"jql": safe_jql, "maxResults": int(maxResults),
               "fields": ["summary", "status", "priority", "assignee"]}
    data = _jira_post("/rest/api/2/search", payload)
    out = []
    for i in data.get("issues", []):
        f = i.get("fields", {})
        out.append({
            "key":      i.get("key"),
            "summary":  f.get("summary"),
            "status":   (f.get("status") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "assignee": (f.get("assignee") or {}).get("displayName"),
        })
    return {
        "count":         len(out),
        "issues":        out,
        "phrases_used":  clean,
        "effective_jql": safe_jql,
    }


def tool_analyze_support_ticket(issueKey: str, sinceHours: int = 24, executeApi: bool = False):
    """Run support-ticket analyzer for hotel unavailable/not-bookable investigations."""
    if not _key_is_allowed(issueKey):
        return {"error": f"Refused: {issueKey} is outside allowed projects {ALLOWED_PROJECTS}."}
    try:
        result = run_support_ticket_analysis(
            issue_key=issueKey,
            since_hours=int(sinceHours),
            execute_api=bool(executeApi),
            output_path=None,
        )
        return result
    except Exception as e:
        return {"error": str(e)}


def tool_analyze_bulk_dry_run(
    sinceHours: int = 24,
    sampleSize: int = 3,
    extraKeywords: list | None = None,
    executeApi: bool = False,
    enableJiraComment: bool = False,
):
    """Run CRSUP-only bulk keyword analysis in dry-run mode with optional API/comment toggles."""
    keywords = _load_availability_keywords()
    extras: list[str] = []
    for item in (extraKeywords or []):
        text = str(item or "").strip()
        if text and text.lower() not in [x.lower() for x in extras]:
            extras.append(text)

    combined: list[str] = []
    for item in keywords + extras:
        if item.lower() not in [x.lower() for x in combined]:
            combined.append(item)
    if not combined:
        return {"error": "No keywords available for bulk analysis."}

    size = max(1, min(int(sampleSize), 10))
    phrase_clause = " OR ".join([f'text ~ "\\"{kw}\\""' for kw in combined])
    jql = (
        f'(project = "CRSUP" AND statusCategory != Done AND ({phrase_clause})) '
        f"AND {_SCOPE_CLAUSE} ORDER BY updated DESC"
    )

    search = tool_search_issues(jql=jql, maxResults=size)
    if search.get("error"):
        return search

    issues = search.get("issues") or []
    picked_tickets = [
        {"issueKey": i.get("key"), "summary": i.get("summary")}
        for i in issues
        if i.get("key")
    ]
    results = []
    for issue in issues:
        key = issue.get("key")
        if not key:
            continue
        try:
            analysis = run_support_ticket_analysis(
                issue_key=key,
                since_hours=int(sinceHours),
                execute_api=bool(executeApi),
                output_path=None,
                comment_jira=bool(enableJiraComment),
                preview_jira_comment=True,
            )
            results.append({
                "issueKey": key,
                "summary": issue.get("summary"),
                "analyzed": True,
                "dryRun": True,
                "executeApi": bool(executeApi),
                "jiraCommentPostingEnabled": bool(enableJiraComment),
                "jiraComment": analysis.get("jiraComment"),
                "wouldCommentPreview": (
                    ((analysis.get("jiraComment") or {}).get("comments") or [None])[0]
                    or (analysis.get("jiraComment") or {}).get("comment")
                ),
                "singleAvailExecution": analysis.get("singleAvailExecution"),
                "singleAvailResponseStatus": (analysis.get("singleAvailResponse") or {}).get("statusCode"),
                "newRelicSampleCount": (analysis.get("newRelic") or {}).get("sampleCount"),
            })
        except Exception as exc:
            results.append({
                "issueKey": key,
                "summary": issue.get("summary"),
                "analyzed": False,
                "dryRun": True,
                "error": str(exc),
            })

    return {
        "mode": "bulk-keyword-analysis-dry-run",
        "project": "CRSUP",
        "dryRun": True,
        "sampleSizeRequested": size,
        "sampleSizeMeaning": "Number of latest matching CRSUP tickets analyzed in this run.",
        "keywordsFromConfig": keywords,
        "keywordsFromInput": extras,
        "keywordsUsed": combined,
        "executeApi": bool(executeApi),
        "jiraCommentPreviewEnabled": True,
        "jiraCommentPostingEnabled": bool(enableJiraComment),
        "effective_jql": search.get("effective_jql") or jql,
        "ticketsMatched": len(issues),
        "pickedTickets": picked_tickets,
        "results": results,
        "note": "Dry-run utility for CRSUP. Keep enableJiraComment=false for safe testing.",
    }


def _build_bulk_dry_run_reply(result: dict, args: dict) -> str:
    if result.get("error"):
        return f"Bulk dry-run failed: {result.get('error')}"

    picked = result.get("pickedTickets") or []
    lines: list[str] = [
        "Ran CRSUP bulk dry-run directly (bypassing LLM parsing to avoid content-filter false positives).",
        f"Matched {result.get('ticketsMatched', 0)} ticket(s).",
        f"Picked (sample): {', '.join([p.get('issueKey', '?') for p in picked]) if picked else 'none'}",
        f"executeApi={bool(args.get('executeApi'))}, enableJiraComment={bool(args.get('enableJiraComment'))}",
        "",
        "Dry-run log:",
    ]

    for item in result.get("results") or []:
        key = item.get("issueKey") or "?"
        status = "ok" if item.get("analyzed") else "error"
        nr_count = item.get("newRelicSampleCount")
        api_status = item.get("singleAvailResponseStatus")
        lines.append(
            f"- {key}: analyzed={status}, newRelicSampleCount={nr_count}, singleAvailResponseStatus={api_status}"
        )
        preview = item.get("wouldCommentPreview")
        if preview:
            preview_text = str(preview).strip().replace("\n", " ")
            if len(preview_text) > 220:
                preview_text = preview_text[:220] + "..."
            lines.append(f"  would-be Jira comment: {preview_text}")

    return "\n".join(lines)


TOOL_FNS = {
    "search_issues":  tool_search_issues,
    "search_concept": tool_search_concept,
    "analyze_support_ticket": tool_analyze_support_ticket,
    "analyze_bulk_dry_run": tool_analyze_bulk_dry_run,
    "get_issue":      tool_get_issue,
    "create_issue":   tool_create_issue,
    "add_comment":    tool_add_comment,
    "assign_issue":   tool_assign_issue,
    "link_issues":    tool_link_issues,
}


def _parse_bool_token(value: str, default: bool) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _extract_bulk_dry_run_args(user_message: str) -> dict | None:
    text = (user_message or "").strip()
    lower = text.lower()

    is_bulk_natural = "bulk dry-run" in lower and "crsup" in lower
    is_bulk_slash = lower.startswith("/bulk-dry-run")
    if not (is_bulk_natural or is_bulk_slash):
        return None

    args = {
        "sinceHours": 24,
        "sampleSize": 3,
        "extraKeywords": [],
        "executeApi": False,
        "enableJiraComment": False,
    }

    # Parse key=value tokens for slash-command style.
    for key, val in re.findall(r"\b(sinceHours|sampleSize|executeApi|enableJiraComment)\s*=\s*([^,;\s]+)", text, flags=re.IGNORECASE):
        k = key.lower()
        if k == "sincehours" and str(val).isdigit():
            args["sinceHours"] = int(val)
        elif k == "samplesize" and str(val).isdigit():
            args["sampleSize"] = int(val)
        elif k == "executeapi":
            args["executeApi"] = _parse_bool_token(val, args["executeApi"])
        elif k == "enablejiracomment":
            args["enableJiraComment"] = _parse_bool_token(val, args["enableJiraComment"])

    # Parse natural-language variants.
    m = re.search(r"sample\s*size\s*(\d+)", lower)
    if m:
        args["sampleSize"] = int(m.group(1))
    m = re.search(r"last\s*(\d+)\s*hours?", lower)
    if m:
        args["sinceHours"] = int(m.group(1))
    m = re.search(r"executeapi\s*(true|false|yes|no|on|off|1|0)", lower)
    if m:
        args["executeApi"] = _parse_bool_token(m.group(1), args["executeApi"])
    m = re.search(r"enablejiracomment\s*(true|false|yes|no|on|off|1|0)", lower)
    if m:
        args["enableJiraComment"] = _parse_bool_token(m.group(1), args["enableJiraComment"])

    # Parse "extra keywords: ..." list.
    extra_match = re.search(r"extra\s*keywords\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if extra_match:
        raw = extra_match.group(1).strip()
        parts = [p.strip() for p in re.split(r"[,;|]", raw) if p.strip()]
        args["extraKeywords"] = parts

    return args

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_issues",
            "description": "Search Jira issues using a raw JQL query. Use this only when you "
                           "already know exact JQL. For concept/keyword searches with synonyms "
                           "and morphological variants, prefer `search_concept` instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "jql":        {"type": "string", "description": "JQL query, e.g. project=CRSUP AND status=Open"},
                    "maxResults": {"type": "integer", "default": 10},
                },
                "required": ["jql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_concept",
            "description": (
                "Search Jira for tickets matching a CONCEPT by passing a list of phrase "
                "variants. The backend will OR them all as exact-phrase matches so the "
                "words must appear consecutively in the ticket text. "
                "Use this for any natural-language topic search (e.g. 'duplicate bookings', "
                "'hotel unavailability', 'price mismatch', 'payment failed', 'wrong rate', "
                "'no rooms available', etc.). "
                "YOU must generate 4–10 high-quality variants yourself covering: "
                "(a) the literal phrase the user typed, "
                "(b) singular AND plural (booking/bookings), "
                "(c) common synonyms (booking↔reservation, hotel↔property, price↔rate, "
                "    duplicate↔double↔duplicated, missing↔not found, failure↔failed), "
                "(d) morphological forms (-able/-ability, -ed/-ing/-ion), "
                "(e) natural word-order swaps when meaningful. "
                "Always include the original user phrasing as one of the variants."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "4–10 phrase variants of the same concept",
                    },
                    "field": {
                        "type": "string",
                        "enum": ["text", "summary", "description", "comment"],
                        "default": "text",
                        "description": "Which Jira text field to match against",
                    },
                    "extraJql": {
                        "type": "string",
                        "description": "Optional extra JQL ANDed onto the search "
                                       "(e.g. 'resolution = Unresolved' or 'priority in (P1,P2)')",
                    },
                    "maxResults": {"type": "integer", "default": 20},
                },
                "required": ["phrases"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_support_ticket",
            "description": (
                "Run end-to-end support ticket analysis for 'hotel unavailable' issues: "
                "(also applicable to 'hotel not bookable' issues) "
                "extract context from Jira issue text, query New Relic logs, and build singleavail payload. "
                "Optionally execute EC2 singleavail call when executeApi=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issueKey":   {"type": "string", "description": "Jira issue key e.g. CRSUP-4421"},
                    "sinceHours": {"type": "integer", "default": 24, "description": "Lookback window in hours"},
                    "executeApi": {"type": "boolean", "default": False, "description": "Whether to call EC2 singleavail endpoint"},
                },
                "required": ["issueKey"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_bulk_dry_run",
            "description": (
                "Run CRSUP-only bulk dry-run analysis for availability keywords across a sample of tickets. "
                "Supports executeApi toggle and optional Jira comment posting toggle. "
                "Preview is included for testing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sinceHours": {"type": "integer", "default": 24, "description": "Lookback window in hours"},
                    "sampleSize": {"type": "integer", "default": 3, "description": "Number of latest matching CRSUP tickets to analyze (1-10)"},
                    "extraKeywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional additional keyword phrases"
                    },
                    "executeApi": {"type": "boolean", "default": False, "description": "Whether to execute EC2 singleavail API"},
                    "enableJiraComment": {"type": "boolean", "default": False, "description": "Whether to post Jira comments on analyzed tickets"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_issue",
            "description": "Fetch full details for a single Jira issue by its key.",
            "parameters": {
                "type": "object",
                "properties": {"issueKey": {"type": "string"}},
                "required": ["issueKey"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_issue",
            "description": "Create a new Jira issue in the given project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project":     {"type": "string", "description": "Project key e.g. CRSUP"},
                    "summary":     {"type": "string"},
                    "issueType":   {"type": "string", "default": "Task"},
                    "description": {"type": "string"},
                    "assignee":    {"type": "string", "description": "Jira username to assign the issue to, e.g. nsh50"},
                },
                "required": ["project", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_issue",
            "description": "Assign or re-assign an existing Jira issue to a user by their Jira username. "
                           "Use this when the user asks to assign a ticket (including a just-created master ticket) to someone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string", "description": "Jira issue key e.g. CRSUP-4427"},
                    "assignee": {"type": "string", "description": "Jira username e.g. nsh50"},
                },
                "required": ["issueKey", "assignee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_comment",
            "description": "Add a comment to an existing Jira issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "comment":  {"type": "string"},
                },
                "required": ["issueKey", "comment"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_issues",
            "description": (
                "Create a formal Jira Issue Link between two issues. "
                "This is the ONLY way to make a link appear under 'Issue Links → Relates to' "
                "in the Jira UI. Use linkType 'Relates' for consolidated/parent tickets. "
                "NEVER substitute this with putting ticket keys in the description text. "
                "Call this once per sub-ticket whenever you create a consolidated ticket."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inwardIssue":  {"type": "string", "description": "Source issue key"},
                    "outwardIssue": {"type": "string", "description": "Target issue key"},
                    "linkType":     {"type": "string", "default": "Relates"},
                },
                "required": ["inwardIssue", "outwardIssue"],
            },
        },
    },
]


def run_chat(history: list, user_message: str, max_steps: int = 8):
    """
    Execute one turn of the agent loop.
    history = list of OpenAI-format messages from prior turns.
    Returns: { reply: str, history: [...], tool_trace: [...] }
    """
    direct_bulk_args = _extract_bulk_dry_run_args(user_message)
    if direct_bulk_args is not None:
        result = tool_analyze_bulk_dry_run(**direct_bulk_args)
        reply = _build_bulk_dry_run_reply(result, direct_bulk_args)
        direct_history = (history or []) + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        return {
            "reply": reply,
            "history": direct_history,
            "tool_trace": [{"tool": "analyze_bulk_dry_run", "args": direct_bulk_args, "result": result}],
        }

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + (history or []) + [
        {"role": "user", "content": user_message}
    ]
    tool_trace = []
    # Guard: track keys created this turn so create_issue is never called twice
    _created_this_turn: list = []

    for _ in range(max_steps):
        resp = _client.chat.completions.create(
            model=_MODEL,
            temperature=0.2,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        # Convert message to dict for storage
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in (msg.tool_calls or [])
            ] if msg.tool_calls else None,
        })

        if not msg.tool_calls:
            # final assistant reply
            return {
                "reply":      msg.content or "(no response)",
                "history":    [m for m in messages if m["role"] != "system"],
                "tool_trace": tool_trace,
            }

        # execute each tool call
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            fn = TOOL_FNS.get(name)
            if not fn:
                result = {"error": f"unknown tool: {name}"}
            else:
                # Prevent duplicate consolidated ticket creation in one turn
                if name == "create_issue" and _created_this_turn:
                    result = {
                        "error": "Refused: create_issue was already called this turn. "
                                 f"Use the existing ticket {_created_this_turn[0]} instead.",
                        "existing_key": _created_this_turn[0],
                    }
                else:
                    try:
                        result = fn(**args)
                    except Exception as e:
                        result = {"error": str(e)}
                    # Track successfully created tickets
                    if name == "create_issue" and result.get("created"):
                        _created_this_turn.append(result["created"])
            tool_trace.append({"tool": name, "args": args, "result": result})
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "name":         name,
                "content":      json.dumps(result)[:6000],
            })

    return {
        "reply":      "Reached max steps without completing. Please rephrase or break the task into smaller steps.",
        "history":    [m for m in messages if m["role"] != "system"],
        "tool_trace": tool_trace,
    }

