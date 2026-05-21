# Jira MCP Quick Setup Checklist

## ✅ Completed

- [x] Created `package.json` with Node dependencies
- [x] Updated `cline_mcp_config.json` with correct paths and credentials
- [x] Created `.env.example` with all required variables
- [x] Updated `README.md` with comprehensive documentation
- [x] Created `MCP_SETUP_GUIDE.md` with detailed setup instructions
- [x] Removed `IMN_WATCHERS` code completely
- [x] Fixed IMN routing logic (only EAN/BCOM, exclude Amadeus)
- [x] Fixed AI system prompt to exclude Amadeus from IMN routing
- [x] Created `.gitignore` with necessary entries

## 📋 TODO Before Going Live

### 1. Install Node Dependencies ⚠️
```bash
cd C:\Users\nsh50\projects\TicketOrchestrator
npm install
```

### 2. Verify Environment Variables ✓
Ensure `.env` has these set:
```
JIRA_URL=https://jira.hrs.io
JIRA_PAT=<your_valid_token>
GITHUB_TOKEN=<your_github_token>
APAC_ASSIGNEE=ssi51
IMN_ASSIGNEE=nsh51
IDD_TEAM_USERS=nsh50
DRY_RUN=true
```

### 3. Test Python Script
```bash
python .\ticket_orchestrator.py
```

Expected output:
```
Authenticated as nsh50
Fetched X open tickets...
```

### 4. Test MCP Server
```bash
npm run start:mcp
```

Expected output:
```
Jira MCP Server running (PAT auth)...
```

### 5. Add to Claude/Cline
- Open Claude or Cline
- Add MCP server: `jira` 
- Verify connection in settings
- Test with a simple query: "Search for open CRSUP issues"

### 6. Run in Live Mode (Optional)
Once tested, set `DRY_RUN=false` in `.env` to enable automatic ticket assignment

## 📁 New Files Created

- `package.json` - Node.js dependencies
- `.env.example` - Environment template
- `MCP_SETUP_GUIDE.md` - Detailed MCP documentation
- `.gitignore` - Git ignore rules

## 📝 Files Updated

- `README.md` - Complete project documentation
- `cline_mcp_config.json` - MCP configuration with correct paths
- `ticket_orchestrator.py` - Removed IMN_WATCHERS, fixed routing logic
- `ai_client.py` - Updated AI prompt to exclude Amadeus

## 🚀 Current Status

| Component | Status |
|-----------|--------|
| Python Orchestrator | ✅ Working |
| Jira Connection | ✅ Tested |
| MCP Server Code | ✅ Ready |
| Node Dependencies | ⚠️ Needs: `npm install` |
| Configuration | ✅ Complete |
| Documentation | ✅ Complete |

## 🔧 Next Steps

1. Run `npm install` to install Node dependencies
2. Test MCP server: `npm run start:mcp`
3. Add to Claude/Cline MCP settings
4. Test ticket routing with `DRY_RUN=true`
5. Enable live mode with `DRY_RUN=false`

## 🆘 Common Issues

| Issue | Solution |
|-------|----------|
| `npm: command not found` | Install Node.js from nodejs.org |
| `JIRA_PAT is invalid` | Generate new token in Jira settings |
| `MCP server not found` | Verify path in cline_mcp_config.json |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |

## 📚 Documentation Files

- `README.md` - Main project documentation
- `MCP_SETUP_GUIDE.md` - Detailed MCP setup
- `.env.example` - Environment variables template
- This file - Quick checklist

---

**Created:** May 18, 2026  
**Last Updated:** May 18, 2026
