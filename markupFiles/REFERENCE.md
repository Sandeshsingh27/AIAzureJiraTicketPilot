# Ticket Orchestrator - Reference

This file consolidates architecture, routing behavior, MCP tool payloads, and command reference.

## Architecture

Components:

- `ticket_orchestrator.py`: main routing engine
- `jira_connect.py`: Jira API helper
- `ai_client.py`: AI classification client
- `jira-mcp-server.js`: MCP server for Jira tools
- `cline_mcp_config.json`: MCP client configuration

Flow:

1. Orchestrator fetches Jira issues.
2. Rule-based routing runs first.
3. AI classification is used as fallback.
4. Decision applies assignment/comments (or dry-run output).
5. MCP server exposes Jira tools to compatible clients.

## Routing logic (current intent)

### Rule 1: APAC routing

- If issue content matches APAC keywords (`APAC_KEYWORDS`), route to `APAC_ASSIGNEE`.

### Rule 2: IMN room-category routing

- `room category` + (`ean` or `bcom`) routes to `IMN_ASSIGNEE`.
- Non-target connectors are excluded from this route.

### Rule 3: mismatch keywords

- Matches `IMN_MISMATCH_KEYWORDS` route to `IMN_ASSIGNEE`.

### Rule 4: AI fallback

- If no deterministic rule matches, AI decides APAC/IMN/KEEP.

### Default

- KEEP with IDD/CRS ownership if nothing else matches.

## MCP tools and JSON payloads

### `get_issue` / `fetch_jira_issue`

```json
{
  "issueKey": "CRSUP-4421"
}
```

### `search_jira_issues`

```json
{
  "jql": "project=CRSUP AND status=Open",
  "maxResults": 10
}
```

### `create_jira_issue`

```json
{
  "project": "CRSUP",
  "issueType": "Task",
  "summary": "Sample issue title",
  "description": "Sample issue description"
}
```

### `add_comment`

```json
{
  "issueKey": "CRSUP-4421",
  "comment": "This is a test comment from MCP."
}
```

## Command reference (PowerShell)

### Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
```

### Run

```powershell
npm run start:mcp
python .\ticket_orchestrator.py
```

### Debug

```powershell
python --version
pip --version
node --version
npm --version
```

```powershell
Test-Path .env
Get-Content .env | Select-Object -First 20
```

### Safe test mode

```powershell
$env:DRY_RUN = "true"
python .\ticket_orchestrator.py
```

## Operational checklist

- `.env` exists and has valid credentials
- Python dependencies installed
- Node dependencies installed
- MCP server starts without errors
- Dry-run routing behaves as expected
- Live mode enabled only after validation

## Security notes

- Keep `.env` private and out of version control.
- Use environment variables for tokens; do not hardcode secrets.
- Rotate Jira and GitHub tokens periodically.

