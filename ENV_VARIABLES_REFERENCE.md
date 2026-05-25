# Environment Variables Reference

This document explains every key in `.env.example`, where it is used, and why it matters.

## Quick Notes

- Use `JIRA_PAT` as the primary Jira authentication method.
- Keep `JIRA_URL` and `JIRA_HOST` identical.
- `DRY_RUN=true` is strongly recommended for testing.
- `NEW_RELIC_ACCOUNT_ID` must be a plain numeric id (no inline comments in the value).

## Variables

| Variable | Required | Used By | Significance |
|---|---|---|---|
| `JIRA_URL` | Yes | Python modules (`orchestrator`, `support_ticket_analyzer`, Flask UI) | Base URL for Jira REST calls in Python flows. |
| `JIRA_HOST` | Yes (for Node MCP) | Node MCP servers (`jira-mcp-server.js`, `mcp_servers/jira-ticket-context-mcp-server.js`) | Base URL for Jira REST calls in Node MCP tools. Keep same as `JIRA_URL`. |
| `JIRA_PAT` | Yes | Python + Node Jira integrations | Main Jira auth token (Bearer). |
| `GITHUB_TOKEN` | Yes (for AI chat/classification) | `ticket_modules/chat/chat_agent.py`, AI client | Token used for GitHub Models/OpenAI-compatible endpoint. |
| `AI_BASE_URL` | Optional | AI chat/client | Override AI endpoint URL (defaults exist in code). |
| `AI_MODEL` | Optional | AI chat/client | AI model name (for example `gpt-4o-mini`). |
| `JIRA_PROJECT_KEY` | Yes | `ticket_modules/orchestrator.py` | Project scope for orchestrator ticket fetch fallback. Supports comma-separated keys. |
| `JIRA_BOARD_NAME` | Optional | `ticket_modules/orchestrator.py` | Board filter source for orchestrator. If empty, orchestrator uses the first `JIRA_PROJECT_KEY` value as board lookup name. |
| `IDD_TEAM_USERS` | Yes | `ticket_modules/orchestrator.py` | Assignee filter list for orchestrator pickup. |
| `APAC_ASSIGNEE` | Yes | `ticket_modules/orchestrator.py` | Assignee used when route is APAC. |
| `APAC_WATCHERS` | Optional | `ticket_modules/orchestrator.py` | Extra users to add/watch when APAC routing occurs. |
| `IMN_ASSIGNEE` | Yes | `ticket_modules/orchestrator.py` | Assignee used when route is IMN. |
| `APAC_KEYWORDS` | Yes | `ticket_modules/orchestrator.py` | Rule keywords for APAC routing. |
| `IMN_ROOM_CATEGORY_KEYWORDS` | Yes | `ticket_modules/orchestrator.py` | Rule keywords for IMN room-category path. |
| `IMN_MISMATCH_KEYWORDS` | Yes | `ticket_modules/orchestrator.py` | Rule keywords for IMN mismatch path. |
| `DRY_RUN` | Optional (default `true`) | `ticket_modules/orchestrator.py`, Flask UI orchestrator launch | Prevents live Jira mutation during test runs. |
| `TEST_ISSUE_KEY` | Optional | `ticket_modules/orchestrator.py` | Restricts orchestrator run to one issue key. |
| `JIRA_EMAIL` | Optional (legacy path) | `ticket_modules/clients/jira_connect.py` | Jira Cloud basic auth helper script fallback. |
| `JIRA_API_TOKEN` | Optional (legacy path) | `ticket_modules/clients/jira_connect.py` | Jira Cloud basic auth helper script fallback. |
| `NEW_RELIC_API_KEY` | Yes (for analyzer/NR MCP) | `support_ticket_analyzer.py`, `newrelic-log-check-mcp-server.js` | NerdGraph API key for New Relic query. |
| `NEW_RELIC_ACCOUNT_ID` | Yes (for analyzer/NR MCP) | `support_ticket_analyzer.py`, `newrelic-log-check-mcp-server.js` | Active New Relic account id used for queries. |
| `NEW_RELIC_LOG_API_URL` | Optional | Analyzer + NR MCP | Used to infer regional NerdGraph URL when needed. |
| `NEW_RELIC_GRAPHQL_URL` | Optional | Analyzer + NR MCP | Explicit NerdGraph URL override. |
| `NRQL_DEFAULT_SINCE_DAYS` | Optional (default `7`) | `ticket_modules/support_ticket_analyzer.py` | Fallback NRQL lookback window in days when `since_hours` is not provided by caller. |
| `NRQL_DEFAULT_LIMIT` | Optional (default `40`) | `ticket_modules/support_ticket_analyzer.py` | Default NRQL row limit used by analyzer queries. |
| `NEW_RELIC_CA_BUNDLE` | Optional | Analyzer + NR MCP | Custom CA bundle path for TLS interception/proxy environments. |
| `NEW_RELIC_INSECURE` | Optional | Analyzer + NR MCP | If true, disables TLS validation (testing only). |
| `EC2_SINGLEAVAIL_URL` | Optional | Analyzer + EC2 MCP | Endpoint for singleavail API execution. |
| `EC2_BEARER_TOKEN` | Optional | Analyzer + EC2 MCP | Authorization token for EC2 singleavail endpoint. |
| `TICKET_ANALYSIS_KEYWORDS_FILE` | Optional | `support_ticket_analyzer.py` | Override path for availability keyword config JSON. |
| `ANALYZER_INCLUDE_COMMENTS` | Optional (default `false`) | `ticket_modules/support_ticket_analyzer.py` | Controls whether Jira comments are included while extracting analyzer indicators (`false` recommended). |
| `BULK_DRY_RUN_SINCE_HOURS` | Optional (unset by default) | `ticket_modules/web/ui_app.py`, `ticket_modules/chat/chat_agent.py` | Optional bulk lookback override in hours; if unset, analyzer falls back to `NRQL_DEFAULT_SINCE_DAYS` in NRQL generation. |
| `BULK_DRY_RUN_SAMPLE_SIZE` | Optional (default `3`) | `ticket_modules/web/ui_app.py`, `ticket_modules/chat/chat_agent.py` | Backend ticket count limit for CRSUP bulk dry-run analysis (clamped to 1-10). |
| `SINGLE_ANALYZE_SINCE_HOURS` | Optional (unset by default) | `ticket_modules/web/ui_app.py`, `ticket_modules/chat/chat_agent.py` | Optional single-ticket lookback override in hours; if unset, analyzer falls back to `NRQL_DEFAULT_SINCE_DAYS` in NRQL generation. |
| `CHAT_HISTORY_WINDOW` | Optional (default `18`) | `ticket_modules/chat/chat_agent.py` | Max recent messages retained in standard chat context window. |
| `CHAT_HISTORY_WINDOW_TIGHT` | Optional (default `8`) | `ticket_modules/chat/chat_agent.py` | Smaller fallback history window when token limits are hit. |
| `CHAT_MSG_CHAR_LIMIT` | Optional (default `1400`) | `ticket_modules/chat/chat_agent.py` | Per-message character cap for user/assistant history passed to model. |
| `CHAT_TOOL_CHAR_LIMIT` | Optional (default `2000`) | `ticket_modules/chat/chat_agent.py` | Per-tool-result character cap in normal mode. |
| `CHAT_TOOL_CHAR_LIMIT_TIGHT` | Optional (default `900`) | `ticket_modules/chat/chat_agent.py` | Per-tool-result character cap in compact fallback mode. |
| `CHAT_CLIENT_HISTORY_WINDOW` | Optional (default `20`) | `ticket_modules/chat/chat_agent.py` | Max user/assistant turns persisted back to client history. |
| `BULK_REPLY_COMMENT_PREVIEW_MAX_CHARS` | Optional (default `0`) | `ticket_modules/chat/chat_agent.py` | Bulk chat reply preview cap for would-be Jira comments (`0` means no truncation). |

## Cleanup Performed

The following duplicate/reference-only keys were removed from `.env.example` because they are not used by runtime code paths:

- `NEW_RELIC_ACCOUNT_ID_PROD`
- `NEW_RELIC_ACCOUNT_ID_IUT`

If you still want to keep account references, store them in documentation or comments, not as active env keys.

## Recommended Minimal Setup

For core orchestrator + analyzer + UI:

```dotenv
JIRA_URL=https://jira.hrs.io
JIRA_HOST=https://jira.hrs.io
JIRA_PAT=...
GITHUB_TOKEN=...
JIRA_PROJECT_KEY=CRSUP
IDD_TEAM_USERS=nsh50
APAC_ASSIGNEE=ssi51
IMN_ASSIGNEE=nsh51
APAC_KEYWORDS=ctrip,autor,vienna
IMN_ROOM_CATEGORY_KEYWORDS=room category
IMN_MISMATCH_KEYWORDS=wrong hotels
NEW_RELIC_API_KEY=...
NEW_RELIC_ACCOUNT_ID=4107119
DRY_RUN=true
```


