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


def _int_env(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _opt_int_env(name: str, *, minimum: int | None = None, maximum: int | None = None) -> int | None:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except Exception:
        return None
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


BULK_DRY_RUN_SINCE_HOURS = _opt_int_env("BULK_DRY_RUN_SINCE_HOURS", minimum=1, maximum=720)
BULK_DRY_RUN_SAMPLE_SIZE = _int_env("BULK_DRY_RUN_SAMPLE_SIZE", 3, minimum=1, maximum=10)
SINGLE_ANALYZE_SINCE_HOURS = _opt_int_env("SINGLE_ANALYZE_SINCE_HOURS", minimum=1, maximum=720)

# Keep model input below gpt-4o-mini request-body limits.
CHAT_HISTORY_WINDOW = _int_env("CHAT_HISTORY_WINDOW", 18, minimum=4, maximum=40)
CHAT_HISTORY_WINDOW_TIGHT = _int_env("CHAT_HISTORY_WINDOW_TIGHT", 8, minimum=2, maximum=20)
CHAT_MSG_CHAR_LIMIT = _int_env("CHAT_MSG_CHAR_LIMIT", 1400, minimum=300, maximum=6000)
CHAT_TOOL_CHAR_LIMIT = _int_env("CHAT_TOOL_CHAR_LIMIT", 2000, minimum=300, maximum=8000)
CHAT_TOOL_CHAR_LIMIT_TIGHT = _int_env("CHAT_TOOL_CHAR_LIMIT_TIGHT", 900, minimum=200, maximum=4000)
CHAT_CLIENT_HISTORY_WINDOW = _int_env("CHAT_CLIENT_HISTORY_WINDOW", 20, minimum=6, maximum=50)
# 0 means no truncation in bulk reply previews.
BULK_REPLY_COMMENT_PREVIEW_MAX_CHARS = _int_env("BULK_REPLY_COMMENT_PREVIEW_MAX_CHARS", 0, minimum=0, maximum=200000)


def _clip_text(value, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _compact_history_for_model(history: list, *, tight: bool = False) -> list:
    """Keep only useful, bounded messages before sending to the model."""
    if not isinstance(history, list):
        return []

    window = CHAT_HISTORY_WINDOW_TIGHT if tight else CHAT_HISTORY_WINDOW
    char_limit = max(300, CHAT_MSG_CHAR_LIMIT // (2 if tight else 1))
    cleaned = []

    for raw in history[-window:]:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue

        cleaned.append({
            "role": role,
            "content": _clip_text(raw.get("content", ""), char_limit),
        })

    return cleaned


def _history_for_client(messages: list) -> list:
    """Return compact user/assistant history to prevent unbounded growth across turns."""
    out = []
    for m in messages:
        role = m.get("role")
        if role not in {"user", "assistant"}:
            continue
        if role == "assistant" and not str(m.get("content") or "").strip():
            # Skip assistant tool-call placeholders (empty text) in persisted history.
            continue
        out.append({
            "role": role,
            "content": _clip_text(m.get("content", ""), CHAT_MSG_CHAR_LIMIT),
        })
    return out[-CHAT_CLIENT_HISTORY_WINDOW:]


def _is_token_limit_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "tokens_limit_reached" in text or ("request body too large" in text and "token" in text)


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
    "You are JiraAzureCopilot — a helpful assistant scoped to the Jira projects "
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
    "If the user asks for bulk operations over previously listed tickets (e.g. 'for these tickets hit API', "
    "'run for all above tickets', 'do not comment on Jira'), use `analyze_bulk_dry_run` and keep comment posting aligned with user intent. "
    "In particular: 'do not comment' / 'no comment' / 'without comment' means enableJiraComment=false. "
    "Conversely: 'comment on the ticket' / 'comment on jira' / 'add a comment' / 'post a comment' / "
    "'comment on the jira ticket' means enableJiraComment=true. "
    "Always honour the user's explicit comment intent — if they asked to comment, set enableJiraComment=true. "
    "IMPORTANT: If user asks to post Jira comments containing request/response payloads or API output, "
    "DO NOT draft free-form comment text and DO NOT use placeholders like '{...}'. "
    "Always call `analyze_support_ticket` with enableJiraComment=true (or `post_analysis_comment`) so backend posts the standard structured comment format used by MCP single/bulk analysis. "
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
    lower = str(comment or "").lower()
    # Guard against placeholder-style comments; use analyzer-backed commenting for payload/response posts.
    if "{...}" in str(comment or "") or ("request payload" in lower and "response" in lower):
        return {
            "error": (
                "Refused placeholder analysis comment. Use analyze_support_ticket(issueKey, "
                "executeApi=true/false, enableJiraComment=true) or post_analysis_comment so Jira gets "
                "the standard formatted request/response comment."
            )
        }
    data = _jira_post(f"/rest/api/2/issue/{issueKey}/comment", {"body": comment})
    return {"id": data.get("id"), "issueKey": issueKey, "status": "added"}


def tool_post_analysis_comment(issueKey: str, executeApi: bool = True):
    """Post the standard analyzer-formatted Jira comment (payload + response) for a single ticket."""
    if not _key_is_allowed(issueKey):
        return {"error": f"Refused: {issueKey} is outside allowed projects {ALLOWED_PROJECTS}."}
    try:
        result = run_support_ticket_analysis(
            issue_key=issueKey,
            since_hours=SINGLE_ANALYZE_SINCE_HOURS,
            execute_api=bool(executeApi),
            output_path=None,
            comment_jira=True,
            preview_jira_comment=True,
        )
        return {
            "issueKey": issueKey,
            "executeApi": bool(executeApi),
            "jiraComment": result.get("jiraComment"),
            "singleAvailExecution": result.get("singleAvailExecution"),
            "singleAvailResponse": result.get("singleAvailResponse"),
            "note": "Comment posted via support analyzer formatter (same style as single/bulk MCP analysis).",
        }
    except Exception as e:
        return {"error": str(e)}

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


def tool_analyze_support_ticket(issueKey: str, executeApi: bool = False, enableJiraComment: bool = False):
    """Run support-ticket analyzer for hotel unavailable/not-bookable investigations."""
    if not _key_is_allowed(issueKey):
        return {"error": f"Refused: {issueKey} is outside allowed projects {ALLOWED_PROJECTS}."}
    try:
        # Chat policy: always execute API for analysis; analyzer itself skips only when required fields are missing.
        result = run_support_ticket_analysis(
            issue_key=issueKey,
            since_hours=SINGLE_ANALYZE_SINCE_HOURS,
            execute_api=True,
            output_path=None,
            comment_jira=bool(enableJiraComment),
            preview_jira_comment=True,
        )
        result["executeApiForcedByChatPolicy"] = True
        return result
    except Exception as e:
        return {"error": str(e)}


def tool_analyze_bulk_dry_run(extraKeywords: list | None = None, executeApi: bool = False, enableJiraComment: bool = False):
    """Run CRSUP-only bulk keyword analysis in dry-run mode with env-configured since/sample defaults."""
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

    size = BULK_DRY_RUN_SAMPLE_SIZE
    since_hours = BULK_DRY_RUN_SINCE_HOURS
    phrase_clause = " OR ".join([f'text ~ "\\"{kw}\\""' for kw in combined])
    # Note: do NOT include _SCOPE_CLAUSE here — tool_search_issues calls
    # _enforce_jql_scope() which appends it automatically, so including it
    # explicitly would produce a duplicate project/status filter in the JQL.
    jql = (
        f'project = "CRSUP" AND statusCategory != Done AND ({phrase_clause}) '
        "ORDER BY updated DESC"
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
                since_hours=since_hours,
                # Chat policy: always execute API for analysis; analyzer skips only when required fields are missing.
                execute_api=True,
                output_path=None,
                comment_jira=bool(enableJiraComment),
                preview_jira_comment=True,
            )
            nr_summary = ((analysis.get("newRelic") or {}).get("summary") or {})
            results.append({
                "issueKey": key,
                "summary": issue.get("summary"),
                "analyzed": True,
                "dryRun": True,
                "executeApi": True,
                "jiraCommentPostingEnabled": bool(enableJiraComment),
                "jiraComment": analysis.get("jiraComment"),
                "wouldCommentPreview": (
                    ((analysis.get("jiraComment") or {}).get("comments") or [None])[0]
                    or (analysis.get("jiraComment") or {}).get("comment")
                ),
                "singleAvailExecution": analysis.get("singleAvailExecution"),
                "singleAvailResponseStatus": (analysis.get("singleAvailResponse") or {}).get("statusCode"),
                "newRelicSampleCount": (analysis.get("newRelic") or {}).get("sampleCount"),
                "newRelicSkipReason": nr_summary.get("skipReason"),
                "missingCoreFilterFields": nr_summary.get("missingCoreFilterFields") or [],
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
        "sinceHoursConfigured": since_hours,
        "sampleSizeConfigured": size,
        "sampleSizeMeaning": "Number of latest matching CRSUP tickets analyzed in this run.",
        "keywordsFromConfig": keywords,
        "keywordsFromInput": extras,
        "keywordsUsed": combined,
        "executeApi": True,
        "executeApiForcedByChatPolicy": True,
        "jiraCommentPreviewEnabled": True,
        "jiraCommentPostingEnabled": bool(enableJiraComment),
        "effective_jql": search.get("effective_jql") or jql,
        "ticketsMatched": len(issues),
        "pickedTickets": picked_tickets,
        "results": results,
        "note": "Dry-run utility for CRSUP. API execution is always enabled in AI chat mode; analyzer skips only when required fields are missing.",
    }


def _bulk_action_label(item: dict) -> str:
    """Derive a concise action string for a single bulk result item."""
    analyzed = bool(item.get("analyzed"))
    exec_info = item.get("singleAvailExecution") or {}
    api_status = item.get("singleAvailResponseStatus")
    missing = item.get("missingCoreFilterFields") or []
    skip_reason = item.get("newRelicSkipReason") or exec_info.get("reason") or "-"

    if not analyzed:
        return f"❌ Analyzer error — {item.get('error') or '-'}"
    if missing:
        return f"⚠️ Missing fields: {', '.join(missing)}"
    if exec_info.get("requested") and not exec_info.get("performed"):
        return f"⚠️ API skipped — {exec_info.get('reason') or skip_reason}"
    if exec_info.get("performed") and api_status is not None and int(api_status) >= 200 and int(api_status) < 300:
        jira_comment_info = item.get("jiraComment") or {}
        comment_posted = bool(jira_comment_info.get("posted"))
        comment_enabled = bool(item.get("jiraCommentPostingEnabled"))
        if comment_posted:
            return "✅ Complete — Jira comment posted"
        elif comment_enabled:
            return f"✅ Complete — comment not posted ({jira_comment_info.get('reason') or 'unknown reason'})"
        else:
            return "✅ Complete — Jira comment not requested"
    if exec_info.get("performed"):
        return f"🔴 API error (HTTP {api_status}) — check inputs and retry"
    return "✅ Complete — enable API for runtime validation"


def _build_bulk_dry_run_reply(result: dict, args: dict) -> str:
    if result.get("error"):
        return f"Bulk dry-run failed: {result.get('error')}"

    picked = result.get("pickedTickets") or []
    rows = result.get("results") or []
    api_success = 0
    api_skipped = 0
    needs_fields = 0
    comment_posted_count = 0
    for item in rows:
        exec_info = item.get("singleAvailExecution") or {}
        if exec_info.get("requested") and exec_info.get("performed"):
            api_success += 1
        elif exec_info.get("requested") and not exec_info.get("performed"):
            api_skipped += 1
        if item.get("missingCoreFilterFields"):
            needs_fields += 1
        if bool((item.get("jiraComment") or {}).get("posted")):
            comment_posted_count += 1

    jira_comment_enabled = bool(args.get("enableJiraComment"))

    # Split into completed-vs-remaining buckets for clearer reporting.
    completed_with_comment: list[dict] = []
    remaining_rows: list[dict] = []
    field_issues: list[dict] = []
    for item in rows:
        exec_info = item.get("singleAvailExecution") or {}
        api_status = item.get("singleAvailResponseStatus")
        comment_posted = bool((item.get("jiraComment") or {}).get("posted"))
        is_success_http = api_status is not None and int(api_status) >= 200 and int(api_status) < 300
        is_completed = bool(item.get("analyzed")) and exec_info.get("performed") and is_success_http and comment_posted
        if item.get("missingCoreFilterFields"):
            field_issues.append(item)
        elif is_completed:
            completed_with_comment.append(item)
        else:
            remaining_rows.append(item)

    # ── Header ────────────────────────────────────────────────────────────────
    lines: list[str] = [
        "### 🔍 CRSUP Bulk Analysis — Results",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| Tickets matched | {result.get('ticketsMatched', 0)} |",
        f"| Sample picked | {len(rows)} |",
        f"| Since hours | {result.get('sinceHoursConfigured')} |",
        f"| Sample size configured | {result.get('sampleSizeConfigured')} |",
        f"| Execute API | {'✅ Yes' if result.get('executeApi') else '❌ No'} |",
        f"| Jira comment posting | {'✅ Enabled' if jira_comment_enabled else '⬜ Disabled'} |",
        "",
        "#### 📊 Outcome Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| ✅ API executed successfully | {api_success} |",
        f"| ⚠️ API skipped (missing fields) | {api_skipped} |",
        f"| 💬 Jira comments posted | {comment_posted_count} |",
        f"| 📝 Tickets needing field updates | {needs_fields} |",
        "",
    ]

    def _append_ticket_table(title: str, table_rows: list[dict]) -> None:
        if not table_rows:
            return
        lines.extend([
            "",
            title,
            "",
            "| Ticket | Summary | Analyzed | NR Logs | API | HTTP | Jira Comment | Action |",
            "|--------|---------|----------|---------|-----|------|--------------|--------|",
        ])
        for item in table_rows:
            key = item.get("issueKey") or "?"
            summary = (item.get("summary") or "-")
            # Truncate long summaries for table readability
            if len(summary) > 45:
                summary = summary[:42] + "…"
            analyzed = "✅" if item.get("analyzed") else "❌"
            nr_count = item.get("newRelicSampleCount")
            nr_cell = f"{nr_count}" if nr_count is not None else "-"
            exec_info = item.get("singleAvailExecution") or {}
            api_cell = "✅" if exec_info.get("performed") else ("⚠️ Skip" if exec_info.get("requested") else "—")
            api_status = item.get("singleAvailResponseStatus")
            http_cell = str(api_status) if api_status is not None else "—"
            jira_comment_info = item.get("jiraComment") or {}
            comment_posted = bool(jira_comment_info.get("posted"))
            comment_cell = "Posted" if comment_posted else ("Not posted" if jira_comment_enabled else "-")
            action = _bulk_action_label(item)
            lines.append(f"| **{key}** | {summary} | {analyzed} | {nr_cell} | {api_cell} | {http_cell} | {comment_cell} | {action} |")

    _append_ticket_table("#### ✅ Tickets Completed (Jira Comment Posted)", completed_with_comment)
    _append_ticket_table("#### 🎫 Remaining Tickets", remaining_rows)

    # ── Detail rows for tickets needing field updates ─────────────────────────
    if field_issues:
        lines.extend([
            "",
            "#### ⚠️ Tickets Requiring Field Updates",
            "",
            "| Ticket | Missing Fields | Skip Reason |",
            "|--------|---------------|-------------|",
        ])
        for item in field_issues:
            key = item.get("issueKey") or "?"
            missing = ", ".join(item.get("missingCoreFilterFields") or [])
            exec_info = item.get("singleAvailExecution") or {}
            reason = item.get("newRelicSkipReason") or exec_info.get("reason") or "-"
            lines.append(f"| **{key}** | {missing} | {reason} |")

    return "\n".join(lines)


def _build_support_ticket_reply(result: dict, args: dict) -> str:
    """Generate a factual, table-formatted response for analyze_support_ticket."""
    if not isinstance(result, dict):
        return "Support ticket analysis finished, but returned an unexpected payload shape."
    if result.get("error"):
        return f"Support ticket analysis failed: {result.get('error')}"

    ticket = result.get("ticket") or {}
    key = ticket.get("key") or args.get("issueKey") or "(unknown ticket)"
    summary = ticket.get("summary") or "-"
    nr = ((result.get("newRelic") or {}).get("summary") or {})
    nr_sample_count = (result.get("newRelic") or {}).get("sampleCount")
    execution = result.get("singleAvailExecution") or {}
    jira_comment = result.get("jiraComment") or {}
    api = result.get("singleAvailResponse") or {}
    indicators = result.get("indicators") or {}
    comment_enabled = bool(args.get("enableJiraComment"))
    comment_posted = bool(jira_comment.get("posted"))

    # ── Header card ───────────────────────────────────────────────────────────
    lines: list[str] = [
        f"### 🎫 Single Ticket Analysis — {key}",
        f"> **{summary}**",
        "",
        "#### 📋 Analysis Overview",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Ticket | **{key}** |",
        f"| Analyzed | ✅ Yes |",
        "",
        "#### 🔭 New Relic Logs",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Log samples matched | {nr.get('matched') if nr.get('matched') is not None else '—'} |",
        f"| Successful events | {nr.get('successful') if nr.get('successful') is not None else '—'} |",
        f"| Sample count | {nr_sample_count if nr_sample_count is not None else '—'} |",
    ]
    if nr.get("skipReason"):
        lines.append(f"| Skip reason | ⚠️ {nr.get('skipReason')} |")
    if nr.get("missingCoreFilterFields"):
        lines.append(f"| Missing fields | `{'`, `'.join(nr.get('missingCoreFilterFields'))}` |")

    # ── SingleAvail execution ─────────────────────────────────────────────────
    api_status = api.get("statusCode") if api else None
    api_icon = "✅" if api_status and int(api_status) >= 200 and int(api_status) < 300 else ("🔴" if api_status else "—")
    lines.extend([
        "",
        "#### ⚙️ SingleAvail API Execution",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Requested | {'✅ Yes' if execution.get('requested') else '❌ No'} |",
        f"| Performed | {'✅ Yes' if execution.get('performed') else '⚠️ No'} |",
        f"| Reason | {execution.get('reason') or 'n/a'} |",
    ])
    if api_status is not None:
        lines.append(f"| HTTP Response | {api_icon} {api_status} |")

    # ── Jira comment ──────────────────────────────────────────────────────────
    if comment_posted:
        comment_status = "✅ Posted successfully"
    elif comment_enabled:
        comment_status = f"⚠️ Not posted — {jira_comment.get('reason') or 'unknown reason'}"
    else:
        comment_status = "⬜ Disabled for this run"

    lines.extend([
        "",
        "#### 💬 Jira Comment",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Posting enabled | {'✅ Yes' if comment_enabled else '⬜ No'} |",
        f"| Status | {comment_status} |",
    ])
    if jira_comment.get("reason") and not comment_posted:
        lines.append(f"| Detail | {jira_comment.get('reason')} |")

    # ── Extracted indicators ─────────────��────────────────────────────────────
    has_any = any(indicators.get(f) for f in ("hrCode", "hKey", "chainId", "customerKey", "companyKey"))
    lines.extend([
        "",
        "#### 🔑 Extracted Core Fields",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| hrCode | `{indicators.get('hrCode') or '—'}` |",
        f"| hKey | `{indicators.get('hKey') or '—'}` |",
        f"| chainId | `{indicators.get('chainId') or '—'}` |",
        f"| customerKey | `{indicators.get('customerKey') or '—'}` |",
        f"| companyKey | `{indicators.get('companyKey') or '—'}` |",
    ])
    if not has_any:
        lines.append("")
        lines.append("> ⚠️ No core filter fields were found in this ticket. Update the ticket with the required identifiers for full analysis.")

    return "\n".join(lines)


def _md_cell(value, *, limit: int = 140) -> str:
    text = "—" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip() or "—"
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|")


def _build_post_analysis_comment_reply(result: dict, args: dict) -> str:
    issue_key = result.get("issueKey") or args.get("issueKey") or "(unknown)"
    if result.get("error"):
        return (
            "### 💬 Post Analysis Comment\n\n"
            "| Field | Value |\n"
            "|-------|-------|\n"
            f"| Ticket | {issue_key} |\n"
            f"| Status | ❌ Failed |\n"
            f"| Error | {_md_cell(result.get('error'))} |"
        )

    comment = result.get("jiraComment") or {}
    posted = bool(comment.get("posted"))
    reason = comment.get("reason") or "n/a"
    api_status = (result.get("singleAvailResponse") or {}).get("statusCode")
    return (
        "### 💬 Post Analysis Comment\n\n"
        "| Field | Value |\n"
        "|-------|-------|\n"
        f"| Ticket | {issue_key} |\n"
        f"| Execute API | {'✅ Yes' if bool(result.get('executeApi')) else '❌ No'} |\n"
        f"| API Status | {_md_cell(api_status)} |\n"
        f"| Jira Comment | {'✅ Posted' if posted else '⚠️ Not posted'} |\n"
        f"| Reason | {_md_cell(reason)} |"
    )


def _build_generic_tool_trace_reply(tool_trace: list[dict]) -> str | None:
    if not tool_trace:
        return None

    lines: list[str] = [
        "### 📋 Query Result",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Tools executed | {len(tool_trace)} |",
        f"| Failed tools | {sum(1 for t in tool_trace if (t.get('result') or {}).get('error'))} |",
        "",
    ]

    for entry in tool_trace:
        name = entry.get("tool") or "unknown"
        args = entry.get("args") or {}
        result = entry.get("result") or {}
        lines.extend(["", f"#### 🛠️ `{name}`", ""])

        if result.get("error"):
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| Status | ❌ Failed |",
                f"| Error | {_md_cell(result.get('error'))} |",
            ])
            continue

        if name in {"search_issues", "search_concept"}:
            issues = result.get("issues") or []
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| Matches | {len(issues)} |",
                f"| Max Results | {_md_cell(args.get('maxResults'))} |",
                f"| Effective JQL | `{_md_cell(result.get('effective_jql'), limit=260)}` |",
                "",
                "| Ticket | Summary | Status | Priority | Assignee |",
                "|--------|---------|--------|----------|----------|",
            ])
            if issues:
                for issue in issues:
                    lines.append(
                        f"| **{_md_cell(issue.get('key'))}** | {_md_cell(issue.get('summary'))} | "
                        f"{_md_cell(issue.get('status'))} | {_md_cell(issue.get('priority'))} | {_md_cell(issue.get('assignee'))} |"
                    )
            else:
                lines.append("| — | No records | — | — | — |")
            continue

        if name == "get_issue":
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| Ticket | {_md_cell(result.get('key'))} |",
                f"| Summary | {_md_cell(result.get('summary'))} |",
                f"| Status | {_md_cell(result.get('status'))} |",
                f"| Priority | {_md_cell(result.get('priority'))} |",
                f"| Assignee | {_md_cell(result.get('assignee'))} |",
                f"| Reporter | {_md_cell(result.get('reporter'))} |",
            ])
            continue

        if name == "create_issue":
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| Status | {'✅ Created' if result.get('created') else '⚠️ Not created'} |",
                f"| Ticket | {_md_cell(result.get('created'))} |",
                f"| URL | {_md_cell(result.get('url'))} |",
                f"| Assignee | {_md_cell(result.get('assignee'))} |",
            ])
            continue

        if name == "assign_issue":
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| Ticket | {_md_cell(result.get('issueKey'))} |",
                f"| Assignee | {_md_cell(result.get('assignee'))} |",
                f"| Status | {'✅ Assigned' if result.get('status') == 'assigned' else _md_cell(result.get('status'))} |",
            ])
            continue

        if name == "add_comment":
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| Ticket | {_md_cell(result.get('issueKey'))} |",
                f"| Comment ID | {_md_cell(result.get('id'))} |",
                f"| Status | {'✅ Added' if result.get('status') == 'added' else _md_cell(result.get('status'))} |",
            ])
            continue

        if name == "link_issues":
            lines.extend([
                "| Field | Value |",
                "|-------|-------|",
                f"| From | {_md_cell(result.get('from'))} |",
                f"| To | {_md_cell(result.get('to'))} |",
                f"| Link Type | {_md_cell(result.get('type'))} |",
                f"| Linked | {'✅ Yes' if result.get('linked') else '❌ No'} |",
            ])
            continue

        # Safe fallback for other tool payloads
        lines.extend([
            "| Field | Value |",
            "|-------|-------|",
            "| Status | ✅ Success |",
            f"| Data | `{_md_cell(json.dumps(result, ensure_ascii=True), limit=280)}` |",
        ])

    return "\n".join(lines)


TOOL_FNS = {
    "search_issues":  tool_search_issues,
    "search_concept": tool_search_concept,
    "analyze_support_ticket": tool_analyze_support_ticket,
    "analyze_bulk_dry_run": tool_analyze_bulk_dry_run,
    "post_analysis_comment": tool_post_analysis_comment,
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
        "extraKeywords": [],
        "executeApi": True,
        "enableJiraComment": False,
    }

    # Parse key=value tokens for slash-command style.
    for key, val in re.findall(r"\b(executeApi|enableJiraComment)\s*=\s*([^,;\s]+)", text, flags=re.IGNORECASE):
        k = key.lower()
        if k == "executeapi":
            args["executeApi"] = _parse_bool_token(val, args["executeApi"])
        elif k == "enablejiracomment":
            args["enableJiraComment"] = _parse_bool_token(val, args["enableJiraComment"])

    # Parse natural-language variants.
    m = re.search(r"executeapi\s*(true|false|yes|no|on|off|1|0)", lower)
    if m:
        args["executeApi"] = _parse_bool_token(m.group(1), args["executeApi"])
    m = re.search(r"enablejiracomment\s*(true|false|yes|no|on|off|1|0)", lower)
    if m:
        args["enableJiraComment"] = _parse_bool_token(m.group(1), args["enableJiraComment"])

    # Detect natural-language comment intent ("comment on the jira ticket", etc.)
    _no_comment_phrases = ["do not comment", "don't comment", "no comment", "without comment",
                           "disable comment", "comment off"]
    _yes_comment_phrases = ["comment on jira", "comment on the jira", "comment on the ticket",
                            "comment on ticket", "add comment", "post comment", "enable comment",
                            "comment on it", "leave a comment", "write comment"]
    if not args["enableJiraComment"]:
        if any(p in lower for p in _yes_comment_phrases) and not any(p in lower for p in _no_comment_phrases):
            args["enableJiraComment"] = True

    # Parse "extra keywords: ..." list.
    extra_match = re.search(r"extra\s*keywords\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if extra_match:
        raw = extra_match.group(1).strip()
        parts = [p.strip() for p in re.split(r"[,;|]", raw) if p.strip()]
        args["extraKeywords"] = parts

    return args


def _extract_bulk_followup_args(user_message: str, history: list | None) -> dict | None:
    """Detect follow-up commands that should continue prior bulk-ticket workflow."""
    text = (user_message or "").strip()
    lower = text.lower()
    lower_norm = re.sub(r"[-_]+", " ", lower)
    if not lower:
        return None

    # Do not hijack concept-search requests (e.g. "room category issue")
    # into availability bulk dry-run.
    if re.search(r"\broom\s+category\b", lower_norm):
        return None

    # If user is asking to list/search tickets (without analysis intent),
    # route to search tools instead of bulk analyzer follow-up.
    search_intent = any(
        token in lower_norm
        for token in ("list", "list down", "show", "search", "find", "fetch", "get")
    ) and "ticket" in lower_norm
    analysis_intent = any(
        token in lower_norm
        for token in (
            "analy",
            "dry run",
            "dry-run",
            "bulk dry",
            "execute api",
            "hit the api",
            "run api",
            "call the api",
            "perform api",
            "post comment",
            "comment on jira",
        )
    )
    if search_intent and not analysis_intent:
        return None

    refers_previous_batch = any(
        token in lower_norm
        for token in (
            "for these tickets",
            "for above tickets",
            "for all above tickets",
            "above tickets",
            "for all these tickets",
            "for the tickets",
            "those tickets",
            "all matched tickets",
        )
    )
    asks_bulk_run = any(
        token in lower_norm
        for token in (
            "bulk",
            "all tickets",
            "all the tickets",
            "all crsup",
        )
    )

    if not (refers_previous_batch or asks_bulk_run):
        return None

    # Confirm there was a prior bulk context in recent conversation.
    recent = "\n".join(
        str((m or {}).get("content", ""))
        for m in (history or [])[-8:]
        if isinstance(m, dict)
    ).lower()
    has_bulk_context = any(
        token in recent
        for token in (
            "bulk",
            "dry-run",
            "tickets analyzed",
            "tickets matched",
            "picked (sample)",
            "crsup",
        )
    )
    if not has_bulk_context and not asks_bulk_run:
        return None

    execute_api = any(
        token in lower
        for token in (
            "hit the api",
            "execute api",
            "run api",
            "call the api",
            "perform api",
        )
    )
    no_comment = any(
        token in lower
        for token in (
            "do not comment",
            "don't comment",
            "no comment",
            "without comment",
            "disable comment",
            "comment off",
        )
    )
    yes_comment = any(
        token in lower
        for token in (
            "comment on jira",
            "comment on the jira",
            "comment on the ticket",
            "comment on ticket",
            "comment on it",
            "add comment",
            "post comment",
            "enable comment",
            "comment the ticket",
            "write comment",
            "leave a comment",
        )
    ) and not no_comment

    return {
        "extraKeywords": [],
        "executeApi": True,
        "enableJiraComment": bool(yes_comment),
    }

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
                "Optionally execute EC2 singleavail call when executeApi=true and post comment with payload+response when enableJiraComment=true. "
                "Use this when user asks to append request/response to Jira in the standard analysis comment format."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issueKey":   {"type": "string", "description": "Jira issue key e.g. CRSUP-4421"},
                    "executeApi": {"type": "boolean", "default": False, "description": "Whether to call EC2 singleavail endpoint"},
                    "enableJiraComment": {"type": "boolean", "default": False, "description": "Whether to post singleavail payload and response as Jira comment"},
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
                "Run CRSUP-only bulk dry-run analysis for availability keywords across a backend-configured sample of tickets. "
                "Supports executeApi toggle and optional Jira comment posting toggle. "
                "Since-hours and sample-size are taken from env defaults. Preview is included for testing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
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
            "name": "post_analysis_comment",
            "description": (
                "Post the standard analyzer-formatted Jira comment with request payload + response body for one ticket. "
                "This matches the same comment style used by single/bulk MCP analysis. "
                "Use this instead of generic add_comment for analysis outputs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string", "description": "Jira issue key e.g. CRSUP-4421"},
                    "executeApi": {"type": "boolean", "default": True, "description": "Whether to execute singleavail before commenting"},
                },
                "required": ["issueKey"],
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
            "description": "Add a plain/manual comment to an existing Jira issue. Do NOT use for payload/response analysis comments.",
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
    if direct_bulk_args is None:
        direct_bulk_args = _extract_bulk_followup_args(user_message, history)
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

    compact_mode = False
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _compact_history_for_model(history or []) + [
        {"role": "user", "content": _clip_text(user_message, CHAT_MSG_CHAR_LIMIT)}
    ]
    tool_trace = []
    # Guard: track keys created this turn so create_issue is never called twice
    _created_this_turn: list = []

    for _ in range(max_steps):
        try:
            resp = _client.chat.completions.create(
                model=_MODEL,
                temperature=0.2,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
        except Exception as exc:
            if _is_token_limit_error(exc) and not compact_mode:
                compact_mode = True
                messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _compact_history_for_model(
                    history or [], tight=True
                ) + [{"role": "user", "content": _clip_text(user_message, max(300, CHAT_MSG_CHAR_LIMIT // 2))}]
                continue
            if _is_token_limit_error(exc):
                return {
                    "reply": "Your request history is too large for the current model. I trimmed context as much as possible. Please start a new chat or resend with less prior context.",
                    "history": _history_for_client(messages),
                    "tool_trace": tool_trace,
                }
            raise
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
            tabular_reply = _build_generic_tool_trace_reply(tool_trace)
            return {
                "reply":      tabular_reply or msg.content or "(no response)",
                "history":    _history_for_client(messages),
                "tool_trace": tool_trace,
            }

        # execute each tool call
        direct_reply = None
        analyzed_result = None
        analyzed_args = None
        bulk_result = None
        bulk_args = None
        comment_post_result = None
        comment_post_args = None
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
                "content":      _clip_text(json.dumps(result, ensure_ascii=True), CHAT_TOOL_CHAR_LIMIT_TIGHT if compact_mode else CHAT_TOOL_CHAR_LIMIT),
            })

            # Capture high-signal tool outputs for deterministic reply generation.
            if name == "analyze_support_ticket":
                analyzed_result = result
                analyzed_args = args
            elif name == "analyze_bulk_dry_run":
                bulk_result = result
                bulk_args = args
            elif name == "post_analysis_comment":
                comment_post_result = result
                comment_post_args = args

        # Prefer deterministic summaries for analyzer-related tools, even when mixed with other tools.
        if bulk_result is not None:
            direct_reply = _build_bulk_dry_run_reply(bulk_result, bulk_args or {})
        elif analyzed_result is not None:
            direct_reply = _build_support_ticket_reply(analyzed_result, analyzed_args or {})
        elif comment_post_result is not None:
            direct_reply = _build_post_analysis_comment_reply(comment_post_result, comment_post_args or {})

        if direct_reply:
            messages.append({"role": "assistant", "content": direct_reply})
            return {
                "reply": direct_reply,
                "history": _history_for_client(messages),
                "tool_trace": tool_trace,
            }

    return {
        "reply":      "Reached max steps without completing. Please rephrase or break the task into smaller steps.",
        "history":    _history_for_client(messages),
        "tool_trace": tool_trace,
    }

