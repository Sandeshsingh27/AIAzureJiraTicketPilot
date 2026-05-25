# Ticket Orchestrator - AI-Powered Jira Automation

A comprehensive Jira automation system with AI-powered ticket routing and a Model Context Protocol (MCP) server for Claude/Cline integration.

## Features

✅ **Intelligent Ticket Routing** - AI-powered classification with keyword-based rules  
✅ **Jira MCP Server** - Direct integration with Claude/Cline via Model Context Protocol  
✅ **Ticket Management** - Assign, comment, and manage Jira tickets automatically  
✅ **Team Coordination** - Route tickets to APAC or IMN teams based on content analysis  
✅ **Dry-Run Mode** - Preview changes before applying to Jira  
✅ **Natural-Language AI Chat** - Route plain English requests to search/analyze/comment tools automatically  
✅ **Deterministic Analysis Replies** - Single/bulk analyzer responses are generated from tool output to avoid vague/opposite summaries  
✅ **Bulk Follow-Up Routing** - Follow-ups like "for these tickets hit API, do not comment" continue bulk workflow correctly  

## Project Structure

```
├── ticket_modules/                     # Module-oriented source package
│   ├── orchestrator.py                 # Main orchestration engine
│   ├── clients/
│   │   ├── ai_client.py                # AI classification using GitHub Models
│   │   ├── jira_connect.py             # Jira connectivity helper
│   │   └── azure_devops_connect.py     # Azure DevOps integration
│   ├── chat/
│   │   └── chat_agent.py               # JiraAzureCopilot chat logic
│   └── web/
│       └── ui_app.py                   # Flask web UI
├── ticket_orchestrator.py              # Backward-compatible entrypoint
├── ai_client.py                        # Backward-compatible export shim
├── jira_connect.py                     # Backward-compatible entrypoint
├── chat_agent.py                       # Backward-compatible export shim
├── ui_app.py                           # Backward-compatible entrypoint
├── jira-mcp-server.js                  # MCP server for Claude/Cline
├── .env.example                        # Environment variables template
├── requirements.txt                    # Python dependencies
├── package.json                        # Node.js dependencies
├── cline_mcp_config.json               # MCP configuration for Cline
└── markupFiles/                        # Consolidated project docs
```

## Prerequisites

- **Python 3.8+** with pip
- **Node.js 16+** with npm
- **Jira Cloud/Server instance** with API access
- **GitHub PAT** (for AI models via GitHub Models)

## Setup

### 1. Environment Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with:
- `JIRA_URL`: Your Jira instance URL
- `JIRA_PAT`: Personal Access Token from Jira
- `GITHUB_TOKEN`: GitHub PAT for AI models
- `APAC_ASSIGNEE`: User to assign APAC tickets
- `IMN_ASSIGNEE`: User to assign IMN tickets
- `IDD_TEAM_USERS`: Comma-separated list of team members

### 2. Python Setup

```bash
# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Node.js Setup (for MCP Server)

```bash
# Install Node dependencies
npm install
```

### 4. React UI Setup (optional, new flexible UI)

```bash
cd frontend
npm install
```

## Usage

### Run Ticket Orchestrator

```powershell
python .\ticket_orchestrator.py
```

**Dry-run mode** (preview changes, don't modify Jira):
```powershell
# Set in .env: DRY_RUN=true
python .\ticket_orchestrator.py
```

**Live mode** (modify Jira):
```powershell
# Set in .env: DRY_RUN=false
python .\ticket_orchestrator.py
```

### Run Web UI (Flask backend)

```powershell
python .\ui_app.py
```

### Run React UI (ChatGPT-style sidebar workspace)

```powershell
npm run ui:dev
```

Or directly:

```powershell
cd .\frontend
npm run dev
```

React UI tabs:

- `AI Chat`
- `MCP Tools`
- `Ticket Orchestrator`
- `How To Use`

### Quick Python Syntax Check

Use `py_compile` to validate Python files quickly:

```powershell
python -m py_compile .\ticket_orchestrator.py
python -m py_compile .\support_ticket_analyzer.py
python -m py_compile .\ui_app.py
python -m py_compile .\ticket_modules\orchestrator.py
python -m py_compile .\ticket_modules\support_ticket_analyzer.py
python -m py_compile .\ticket_modules\web\ui_app.py
```

### MCP Server Usage (Claude/Cline)

#### 1. Start the MCP Server

```bash
npm run start:mcp
```

Or manually:
```bash
node jira-mcp-server.js
```

#### 2. Add to Claude/Cline Settings

The MCP server is configured in `cline_mcp_config.json`. Cline will auto-detect it.

#### 3. Available MCP Tools in Claude/Cline

- **fetch_jira_issue** - Get issue details by key
- **search_jira_issues** - Search using JQL
- **create_jira_issue** - Create new issues
- **add_comment** - Add comments to issues

**Example Claude prompt:**
```
Search for all open issues in CRSUP project and summarize them.
```

Claude will automatically use the `search_jira_issues` MCP tool.

### Three Dedicated MCP Servers (Jira -> New Relic -> EC2)

You can run these as separate servers, one per investigation stage:

1. `jira-ticket-context-mcp-server.js` - extract `museId`/`hrCode`/`hKey`/dates from Jira tickets
2. `newrelic-log-check-mcp-server.js` - verify related New Relic logs and success status
3. `singleavail-ec2-mcp-server.js` - build payload and call EC2 `singleavail` endpoint

Run each server:

```powershell
npm run start:mcp:jira-context
npm run start:mcp:newrelic
npm run start:mcp:singleavail
```

Use `cline_mcp_config.multi.example.json` as a starting point for client config.

### Support Ticket Analyzer (Jira + New Relic + EC2)

Use this when a Jira ticket mentions "hotel unavailable" and you want to:
- pull identifiers from Jira (`museId`, `hrCode`, `hKey`, dates),
- validate related New Relic logs,
- build a `singleavail` payload,
- optionally call the EC2 endpoint.

```powershell
python .\support_ticket_analyzer.py --issue-key CRSUP-4421 --since-hours 24 --output analysis.json
```

To also call the EC2 endpoint:

```powershell
python .\support_ticket_analyzer.py --issue-key CRSUP-4421 --since-hours 24 --execute-api --output analysis.json
```

Required env vars:
- `NEW_RELIC_API_KEY`
- `NEW_RELIC_ACCOUNT_ID`

New Relic endpoint options:
- `NEW_RELIC_LOG_API_URL` (example: `https://log-api.eu.newrelic.com/log/v1`)
- `NEW_RELIC_GRAPHQL_URL` (optional explicit override)
- `NEW_RELIC_CA_BUNDLE` (optional PEM file path for corporate CA trust)
- `NEW_RELIC_INSECURE` (optional `true/false`, test-only TLS bypass)

If `NEW_RELIC_GRAPHQL_URL` is empty and `NEW_RELIC_LOG_API_URL` uses `log-api.<region>.newrelic.com`,
the tool derives NerdGraph automatically as `https://api.<region>.newrelic.com/graphql`.

If you hit `SSLCertVerificationError` in corporate environments:
1. Export your corporate root/intermediate CA certificate as PEM.
2. Set `NEW_RELIC_CA_BUNDLE` to that PEM file path.
3. Re-run analyzer.
4. Use `NEW_RELIC_INSECURE=true` only for temporary testing.

Optional env vars:
- `EC2_SINGLEAVAIL_URL`
- `EC2_BEARER_TOKEN`

### AI Chat Prompt Examples (UI)

Use these prompts in the **AI Chat** tab of `ui_app.py`:

Analyze only (no EC2 call):

```text
Analyze support ticket CRSUP-4421 for hotel unavailable. Check New Relic logs from last 24 hours and build the singleavail payload.
```

Analyze + execute EC2 call:

```text
Run end-to-end analysis for CRSUP-4421, include New Relic check, build payload, and execute the singleavail API call.
```

Bulk dry-run and then execute API for matched tickets (no Jira comments):

```text
Check all CRSUP tickets about hotel unavailable and run dry-run analysis.
Then for these tickets hit the API as well after fetching New Relic data, do not comment on Jira.
```

Append request/response in Jira using analyzer-standard formatting:

```text
For CRSUP-4421, post the analysis comment with request payload and response on Jira.
```

## Routing Rules

### Rule #1: APAC Connects
Keywords: CTRIP, AUTOR, VIENNA → Assigns to **APAC_ASSIGNEE**

### Rule #2: Room Category + EAN/BCOM
Room category issues with EAN or BCOM (excluding other connects like Amadeus) → Assigns to **IMN_ASSIGNEE**

### Rule #3: Multi-Source Mismatch
Keywords like "wrong hotels" or booking mismatches → Assigns to **IMN_ASSIGNEE**

### Fallback: AI Classification
If no keyword rules match, uses GitHub Models (gpt-4o-mini) to classify the ticket.

## Configuration

### Environment Variables

| Variable | Required | Example |
|----------|----------|---------|
| JIRA_URL | Yes | `https://jira.hrs.io` |
| JIRA_PAT | Yes | `rMzUyNTE2MjI0MDAxOkgGvPp...` |
| JIRA_PROJECT_KEY | Yes | `CRSUP` |
| GITHUB_TOKEN | Yes | `ghp_xxx...` |
| APAC_ASSIGNEE | Yes | `ssi51` |
| IMN_ASSIGNEE | Yes | `nsh51` |
| IDD_TEAM_USERS | Yes | `nsh50,nsh51` |
| DRY_RUN | No | `true` (default) |
| AI_MODEL | No | `gpt-4o-mini` (default) |

### Keywords Configuration

Edit `.env` to customize routing keywords:

```env
APAC_KEYWORDS=ctrip,autor,vienna
IMN_ROOM_CATEGORY_KEYWORDS=room category
IMN_MISMATCH_KEYWORDS=wrong hotels,booking error
```

## Troubleshooting

### Jira Connection Error (401 Unauthorized)

**Cause:** Invalid or expired JIRA_PAT token

**Solution:**
1. Generate a new Personal Access Token in Jira settings
2. Update JIRA_PAT in `.env`
3. Verify JIRA_URL is correct

### MCP Server Not Starting

**Cause:** Missing Node.js dependencies

**Solution:**
```bash
npm install
npm run start:mcp
```

### AI Classification Failed

**Cause:** Invalid GITHUB_TOKEN or API quota exceeded

**Solution:**
1. Verify GITHUB_TOKEN is valid
2. Check GitHub Models API limits
3. Set DRY_RUN=true to test without AI

### Ticket Not Being Assigned

**Cause:** Routing rules not matching or user doesn't have permission

**Solution:**
1. Check keyword configuration in `.env`
2. Verify assignee usernames exist in Jira
3. Check Jira permissions for the authenticating user

## Development

### Adding New Routing Rules

Edit the `rule_based_route()` function in `ticket_orchestrator.py`:

```python
# Example: Add new rule for SPECIAL tickets
if "special_keyword" in blob:
    return "SPECIAL_TEAM", ["special_keyword"]
```

### Adding MCP Tools

Edit `jira-mcp-server.js` in the `tools/call` handler to add new tools.

## Security

⚠️ **Important Security Notes:**

- Never commit `.env` to version control (already in `.gitignore`)
- Use Personal Access Tokens, not passwords
- Rotate tokens regularly
- Keep GitHub token secret
- Use environment variables in production, not hardcoded values

## Files Reference

| File | Purpose |
|------|---------|
| `ticket_orchestrator.py` | Main orchestration logic |
| `jira_connect.py` | Jira API helper functions |
| `ai_client.py` | AI classification via GitHub Models |
| `jira-mcp-server.js` | MCP server for Claude/Cline |
| `requirements.txt` | Python dependencies |
| `package.json` | Node.js dependencies |
| `.env.example` | Environment variables template |

## API Documentation

### Jira MCP Server Endpoints

**fetch_jira_issue**
```json
{
  "issueKey": "CRSUP-4422"
}
```

**search_jira_issues**
```json
{
  "jql": "project = CRSUP AND status = Open",
  "maxResults": 10
}
```

**create_jira_issue**
```json
{
  "project": "CRSUP",
  "issueType": "Task",
  "summary": "Issue title",
  "description": "Issue description"
}
```

**add_comment**
```json
{
  "issueKey": "CRSUP-4422",
  "comment": "Comment text"
}
```

## License

MIT

## Notes

- Keep `.env` and credentials secure
- Test with `DRY_RUN=true` before enabling live mode
- Monitor ticket routing accuracy and adjust keyword rules as needed
- For setup help, see `markupFiles/GETTING_STARTED.md`
- For technical details, see `markupFiles/REFERENCE.md`
