# Jira MCP (Model Context Protocol) Setup Guide

## Current Status ✅

Your project has a functional Jira MCP server (`jira-mcp-server.js`) with the following tools:
- ✅ `fetch_jira_issue` - Fetch issue details
- ✅ `search_jira_issues` - Search issues using JQL
- ✅ `create_jira_issue` - Create new issues
- ✅ `add_comment` - Add comments to issues

## What's Missing / TODO

### 1. **Node.js Dependencies** ❌
The `jira-mcp-server.js` requires Node.js packages but there's NO `package.json`.

**Action Required:**
```bash
npm init -y
npm install @modelcontextprotocol/sdk axios
```

### 2. **Fix cline_mcp_config.json Path** ❌
The config file has a placeholder path: `"/path/to/jira-mcp-server.js"`

**Action Required:** Update to absolute path:
```json
{
  "mcpServers": {
    "jira": {
      "command": "node",
      "args": ["C:\\Users\\nsh50\\projects\\TicketOrchestrator\\jira-mcp-server.js"],
      "env": {
        "JIRA_HOST": "https://jira.hrs.io",
        "JIRA_PAT": "${JIRA_PAT}"
      }
    }
  }
}
```

### 3. **.env Configuration** ❌
Verify these variables are set in your `.env`:
```
JIRA_URL=https://jira.hrs.io
JIRA_PAT=<your_valid_token>
```

For MCP Server:
```
JIRA_HOST=https://jira.hrs.io
```

### 4. **Update package.json** (After creation)
Add a start script:
```json
{
  "name": "jira-orchestrator",
  "version": "1.0.0",
  "scripts": {
    "start:mcp": "node jira-mcp-server.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "latest",
    "axios": "latest"
  }
}
```

### 5. **Documentation Updates** ❌
Update README.md to include MCP setup instructions

### 6. **Test MCP Server** ❌
After setup, test with:
```bash
$env:JIRA_HOST="https://jira.hrs.io"
$env:JIRA_PAT="<your_token>"
node jira-mcp-server.js
```

### 7. **Additional MCP Tools to Consider** 📝
The current implementation has 4 tools. Consider adding:
- `assign_jira_issue` - Assign issue to user
- `transition_jira_issue` - Change issue status
- `update_jira_issue` - Update fields
- `get_jira_projects` - List available projects
- `get_issue_type_fields` - Get required fields for creating issues

### 8. **Error Handling & Logging** 📝
Improve error messages and add:
- Structured logging
- Retry logic for API failures
- Rate limiting awareness

### 9. **Integration with Cline/Claude** 📝
- Ensure `cline_mcp_config.json` path is correct in your IDE settings
- Test MCP connection through Claude/Cline interface
- Verify tool availability in chat

### 10. **Security** 🔒
- Never commit `.env` (already in `.gitignore` ✅)
- Use environment variable substitution for JIRA_PAT
- Consider token rotation/expiration

---

## Quick Setup Steps

1. **Create package.json:**
   ```bash
   cd C:\Users\nsh50\projects\TicketOrchestrator
   npm init -y
   npm install @modelcontextprotocol/sdk axios
   ```

2. **Update cline_mcp_config.json** with absolute path

3. **Verify .env has:**
   - `JIRA_URL=https://jira.hrs.io`
   - `JIRA_PAT=<valid_token>`

4. **Test MCP server:**
   ```bash
   npm run start:mcp
   ```

5. **Add to Claude/Cline MCP config** and test

---

## Files Summary

| File | Purpose | Status |
|------|---------|--------|
| `jira-mcp-server.js` | MCP server implementation | ✅ Complete |
| `cline_mcp_config.json` | MCP config for Cline | ⚠️ Needs path update |
| `package.json` | Node dependencies | ❌ Missing |
| `.env` | Environment variables | ✅ Has vars (needs valid token) |
| `jira_connect.py` | Python Jira client | ✅ Working |
| `ticket_orchestrator.py` | Main orchestrator | ✅ Working |
| `ai_client.py` | AI classification | ✅ Working |

