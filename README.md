# Ticket Orchestrator - AI-Powered Jira Automation

A comprehensive Jira automation system with AI-powered ticket routing and a Model Context Protocol (MCP) server for Claude/Cline integration.

## Features

✅ **Intelligent Ticket Routing** - AI-powered classification with keyword-based rules  
✅ **Jira MCP Server** - Direct integration with Claude/Cline via Model Context Protocol  
✅ **Ticket Management** - Assign, comment, and manage Jira tickets automatically  
✅ **Team Coordination** - Route tickets to APAC or IMN teams based on content analysis  
✅ **Dry-Run Mode** - Preview changes before applying to Jira  

## Project Structure

```
├── ticket_orchestrator.py      # Main orchestration engine
├── jira_connect.py             # Jira connectivity helper
├── jira-mcp-server.js          # MCP server for Claude/Cline
├── ai_client.py                # AI classification using GitHub Models
├── azure_devops_connect.py     # Azure DevOps integration
├── .env.example                # Environment variables template
├── requirements.txt            # Python dependencies
├── package.json                # Node.js dependencies
├── cline_mcp_config.json       # MCP configuration for Cline
└── markupFiles/                # Consolidated project docs
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
