# JiraAzureCopilot - Getting Started

This guide replaces multiple setup/checklist docs and gives you a single path to get running quickly.

## 1) Prerequisites

- Python 3.8+
- Node.js 16+
- Jira personal access token
- GitHub token for AI classification

## 2) Project setup

Use PowerShell from the project root (`C:\Users\ssi51\Documents\Project\TicketOrchestrator`).

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
```

## 3) Configure environment

Create/update `.env` using `.env.example` as template.

Required values:

- `JIRA_URL`
- `JIRA_PAT`
- `GITHUB_TOKEN`
- `JIRA_PROJECT_KEY`
- `IDD_TEAM_USERS`
- `APAC_ASSIGNEE`
- `IMN_ASSIGNEE`
- `DRY_RUN`

Recommended for first run:

- `DRY_RUN=true`

## 4) Start services

In terminal 1:

```powershell
npm run start:mcp
```

In terminal 2:

```powershell
.\venv\Scripts\Activate.ps1
python .\ticket_orchestrator.py
```

## 5) Verify expected behavior

- MCP terminal shows the server started message.
- Orchestrator prints Jira authentication/user info.
- Tickets are fetched and routed with dry-run output.

## 6) Common workflows

### Test one issue only

Set this in `.env`:

```dotenv
TEST_ISSUE_KEY=CRSUP-4422
```

Then run:

```powershell
.\venv\Scripts\Activate.ps1
python .\ticket_orchestrator.py
```

### Go live (after validation)

Set in `.env`:

```dotenv
DRY_RUN=false
```

Then run orchestrator again.

## 7) Quick troubleshooting

### `ModuleNotFoundError`

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### MCP server does not start

```powershell
npm install
npm run start:mcp
```

### Jira auth errors

- Confirm `JIRA_URL` and `JIRA_PAT` in `.env`.
- Verify token is active and has required permissions.

### AI classification errors

- Confirm `GITHUB_TOKEN` is valid.
- Confirm `AI_BASE_URL` and `AI_MODEL` values.

## 8) Claude/Cline MCP integration

- Ensure `cline_mcp_config.json` points to the local `jira-mcp-server.js` path.
- Start MCP server with `npm run start:mcp`.
- In your MCP client, verify the `jira` server is connected.

## 9) What to read next

- Main project overview: `README.md`
- Detailed technical reference: `markupFiles/REFERENCE.md`

