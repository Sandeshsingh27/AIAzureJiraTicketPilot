"""
AI Ticket Orchestrator

Flow:
  1. Pull open Jira tickets assigned to IDD/CRS team members.
  2. Parse title + description + comments.
  3. Apply keyword rules first; fall back to gpt-4o-mini (via GitHub Models)
     for fuzzy classification.
  4. Reassign APAC -> Gilbert, IMN -> Dipeen, and add a comment.
  5. Print a summary report.

Set DRY_RUN=true in .env to preview without modifying Jira.
"""
import os
import re
from collections import Counter
from dotenv import load_dotenv
from jira import JIRA

from ticket_modules.clients.ai_client import classify_ticket

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")
JIRA_PAT = os.getenv("JIRA_PAT")

JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "").strip()
JIRA_BOARD_NAME = os.getenv("JIRA_BOARD_NAME", "").strip()

TEAM_USERS = [u.strip() for u in os.getenv("IDD_TEAM_USERS", "").split(",") if u.strip()]
APAC_ASSIGNEE = os.getenv("APAC_ASSIGNEE", "").strip()
IMN_ASSIGNEE = os.getenv("IMN_ASSIGNEE", "").strip()
APAC_WATCHERS = [u.strip() for u in os.getenv("APAC_WATCHERS", "").split(",") if u.strip()]

APAC_KW = [k.strip().lower() for k in os.getenv("APAC_KEYWORDS", "").split(",") if k.strip()]
IMN_RC_KW = [k.strip().lower() for k in os.getenv("IMN_ROOM_CATEGORY_KEYWORDS", "").split(",") if k.strip()]
IMN_MM_KW = [k.strip().lower() for k in os.getenv("IMN_MISMATCH_KEYWORDS", "").split(",") if k.strip()]

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
TEST_ISSUE_KEY = os.getenv("TEST_ISSUE_KEY", "").strip()


def connect_jira():
    if not JIRA_PAT:
        raise RuntimeError("JIRA_PAT not set in .env")
    return JIRA(server=JIRA_URL, token_auth=JIRA_PAT)


def _resolve_board_jql(jira):
    """If JIRA_BOARD_NAME is set, fetch that board's saved filter JQL via Agile API."""
    if not JIRA_BOARD_NAME:
        return None
    try:
        boards = jira.boards(name=JIRA_BOARD_NAME)
        match = next((b for b in boards if b.name == JIRA_BOARD_NAME),
                     boards[0] if boards else None)
        if not match:
            print("WARN: board not found:", JIRA_BOARD_NAME)
            return None
        data = jira._session.get(
            "{}/rest/agile/1.0/board/{}/configuration".format(JIRA_URL, match.id)
        ).json()
        filter_id = data.get("filter", {}).get("id")
        if not filter_id:
            return None
        f = jira.filter(filter_id)
        print("Using board '{}' filter JQL: {}".format(match.name, f.jql))
        return f.jql
    except Exception as e:
        print("WARN: could not resolve board JQL ({}); falling back to project filter".format(e))
        return None


def _strip_order_by_clause(jql: str) -> str:
    """Remove trailing ORDER BY from JQL so it can be safely embedded in AND clauses."""
    text = str(jql or "").strip()
    if not text:
        return text
    # Jira board filters often include ORDER BY; we apply final ordering at query end.
    parts = re.split(r"\border\s+by\b", text, maxsplit=1, flags=re.IGNORECASE)
    return parts[0].strip() if parts else text


def fetch_team_tickets(jira):
    if TEST_ISSUE_KEY:
        jql = 'issuekey = "{}"'.format(TEST_ISSUE_KEY)
        print("JQL:", jql)
        return jira.search_issues(jql, maxResults=1, fields="*all")

    if not TEAM_USERS:
        raise RuntimeError("IDD_TEAM_USERS empty in .env")
    user_list = ",".join('"{}"'.format(u) for u in TEAM_USERS)

    clauses = []
    board_jql = _resolve_board_jql(jira)
    if board_jql:
        clauses.append("(" + _strip_order_by_clause(board_jql) + ")")
    elif JIRA_PROJECT_KEY:
        keys = [k.strip() for k in JIRA_PROJECT_KEY.split(",") if k.strip()]
        if len(keys) == 1:
            clauses.append('project = "{}"'.format(keys[0]))
        else:
            joined = ", ".join('"{}"'.format(k) for k in keys)
            clauses.append('project in ({})'.format(joined))

    clauses.append("assignee in ({})".format(user_list))
    clauses.append("statusCategory != Done")

    jql = " AND ".join(clauses) + " ORDER BY updated DESC"
    print("JQL:", jql)
    return jira.search_issues(jql, maxResults=100, fields="*all")


def _stringify(val):
    """Convert any Jira field value into searchable text."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, list):
        return " ".join(_stringify(v) for v in val)
    if isinstance(val, dict):
        return " ".join(_stringify(v) for v in val.values())
    # jira.resources.Resource-like objects: try common attrs
    for attr in ("value", "name", "displayName", "key"):
        if hasattr(val, attr):
            return str(getattr(val, attr) or "")
    return str(val)


# Fields to skip when building the searchable blob (noisy / huge / irrelevant)
_SKIP_FIELDS = {
    "attachment", "worklog", "watches", "subtasks", "issuelinks",
    "votes", "progress", "aggregateprogress", "timetracking",
    "thumbnail", "lastViewed", "created", "updated", "resolutiondate",
    "duedate", "statuscategorychangedate", "workratio",
}


def get_text(issue):
    title = issue.fields.summary or ""
    desc = issue.fields.description or ""
    comments = ""
    if getattr(issue.fields, "comment", None) and issue.fields.comment.comments:
        comments = "\n".join(c.body for c in issue.fields.comment.comments)

    # Walk every field on the issue and stringify (custom fields like museId,
    # connector, source, channel, brand etc. live under customfield_xxxxx)
    extras = []
    raw_fields = issue.raw.get("fields", {}) if hasattr(issue, "raw") else {}
    for fname, fval in raw_fields.items():
        if fname in _SKIP_FIELDS:
            continue
        if fname in ("summary", "description", "comment"):
            continue  # already captured
        text = _stringify(fval)
        if text:
            extras.append("{}: {}".format(fname, text))
    extras_text = "\n".join(extras)

    return title, desc, comments, extras_text


def rule_based_route(title, desc, comments, extras=""):
    blob = "\n".join([title, desc, comments, extras]).lower()
    # 1) APAC connects win first (CTRIP, AUTOR VIENNA, other APAC connects -> Gilbert)
    apac_hits = [k for k in APAC_KW if k in blob]
    if apac_hits:
        return "APAC", apac_hits
    # 2) Room Category + EAN / BCOM museId only -> IMN (Dipeen)
    #    If any other museId is present, do NOT route to IMN at all (keep in IDD)
    IMN_MUSEID = ["ean", "bcom"]
    OTHER_MUSEID = ["amadeus", "derbysoft", "solmelia", "lido", "ihg"]
    if "room category" in blob:
        rc_hits = [k for k in IMN_MUSEID if k in blob]
        other_hits = [k for k in OTHER_MUSEID if k in blob]
        if other_hits:
            # Room category + excluded museId -> keep in IDD, do not route
            return None, []
        if rc_hits:
            return "IMN", ["room category"] + rc_hits
    # 3) Multi source mismatch / wrong hotels -> IMN (Dipeen)
    mm_hits = [k for k in IMN_MM_KW if k in blob]
    if mm_hits:
        return "IMN", mm_hits
    return None, []


def decide(title, desc, comments, extras=""):
    team, hits = rule_based_route(title, desc, comments, extras)
    if team:
        return {
            "team": team,
            "reason": "matched keyword rule",
            "matched": hits,
            "confidence": 1.0,
            "source": "rule",
        }
    try:
        ai = classify_ticket(title, desc, comments + "\n\n[FIELDS]\n" + extras)
        ai["source"] = "ai"
        ai.setdefault("matched", [])
        return ai
    except Exception as e:
        print("  WARN: AI classification failed ({}); keeping ticket".format(e))
        return {"team": "KEEP", "reason": "ai_error: {}".format(e),
                "matched": [], "confidence": 0.0, "source": "ai_error"}


def _mention(u):
    """Jira wiki-markup mention."""
    return "[~{}]".format(u) if u else ""


def _format_connects(matched):
    """Pretty-print matched APAC keywords like ['ctrip','vienna'] -> 'CTRIP, VIENNA'."""
    seen = []
    for m in matched or []:
        up = m.upper()
        if up not in seen:
            seen.append(up)
    return ", ".join(seen)


def apply_decision(jira, issue, decision):
    team = decision.get("team", "KEEP")
    matched = decision.get("matched", [])

    if team == "APAC":
        new_assignee = APAC_ASSIGNEE
        watchers = APAC_WATCHERS
        connects = _format_connects(matched) or "APAC connect"
        comment = (
            "Hi {assignee_m},\n\n\n"
            "Reassigning this ticket to you as it belongs to the APAC connect ({connects}). "
            "Kindly take it forward.\n\n"
            "Thanks and Regards,\n"
            "Team IDD."
        ).format(
            assignee_m=_mention(new_assignee),
            connects=connects,
        )
    elif team == "IMN":
        new_assignee = IMN_ASSIGNEE
        watchers = []
        reason_bits = _format_connects(matched) or "Room Category / multi-source mismatch"
        comment = (
            "Hi {assignee_m},\n\n\n"
            "Reassigning this ticket to you as it belongs to the IMN team (Room Category for BCOM/EAN). "
            "Kindly take it forward.\n\n"
            "Thanks and Regards,\n"
            "Team IDD."
        ).format(
            assignee_m=_mention(new_assignee),
        )
    else:
        return False

    print("  -> {} reassign to {} ({}) [{}] matched={}".format(
        issue.key, new_assignee, team, decision.get("source"), matched
    ))
    if DRY_RUN:
        print("     (DRY_RUN=true; not modifying Jira)")
        print("     comment preview:", comment)
        return True
    try:
        jira.assign_issue(issue, new_assignee)
        jira.add_comment(issue, comment)
        # Also add as watchers so they get notifications even if mention parsing fails
        for w in watchers:
            try:
                jira.add_watcher(issue, w)
            except Exception as we:
                print("     WARN: could not add watcher {}: {}".format(w, we))
        refreshed = jira.issue(issue.key, fields="assignee")
        actual = refreshed.fields.assignee.name if refreshed.fields.assignee else None
        if actual == new_assignee:
            print("     OK: now assigned to", actual)
        else:
            print("     WARN: assignee is '{}', expected '{}'".format(actual, new_assignee))
        return True
    except Exception as e:
        print("     ERROR: failed to assign/comment on {}: {}".format(issue.key, e))
        return False


def main():
    jira = connect_jira()
    me = jira.myself()
    print("Authenticated as", me.get("name"))

    issues = fetch_team_tickets(jira)
    print("Fetched {} open tickets for {}".format(len(issues), TEAM_USERS))

    stats = Counter()
    routed = []
    for issue in issues:
        title, desc, comments, extras = get_text(issue)
        decision = decide(title, desc, comments, extras)
        team = decision.get("team", "KEEP")
        stats[team] += 1
        print("{} | {} -> {} ({})".format(
            issue.key, title[:80], team, decision.get("source")
        ))
        if team in ("APAC", "IMN"):
            apply_decision(jira, issue, decision)
            routed.append((issue.key, team))

    print("\n========== REPORT ==========")
    print("Mode             :", "DRY RUN (no Jira changes)" if DRY_RUN else "LIVE")
    print("Total scanned    :", sum(stats.values()))
    print("Kept in IDD/CRS  :", stats["KEEP"])
    print("Shifted to APAC  :", stats["APAC"], "->", APAC_ASSIGNEE)
    print("Shifted to IMN   :", stats["IMN"], "->", IMN_ASSIGNEE)
    if routed:
        print("Routed tickets   :")
        for k, t in routed:
            print("  -", k, "->", t)
    print("============================")


if __name__ == "__main__":
    main()

