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
| `NEW_RELIC_CA_BUNDLE` | Optional | Analyzer + NR MCP | Custom CA bundle path for TLS interception/proxy environments. |
| `NEW_RELIC_INSECURE` | Optional | Analyzer + NR MCP | If true, disables TLS validation (testing only). |
| `EC2_SINGLEAVAIL_URL` | Optional | Analyzer + EC2 MCP | Endpoint for singleavail API execution. |
| `EC2_BEARER_TOKEN` | Optional | Analyzer + EC2 MCP | Authorization token for EC2 singleavail endpoint. |
| `TICKET_ANALYSIS_KEYWORDS_FILE` | Optional | `support_ticket_analyzer.py` | Override path for availability keyword config JSON. |

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


