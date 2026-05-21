# Jira MCP - Quick Command Reference

## Installation & Setup

```powershell
# 1. Install Node dependencies
npm install

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create virtual environment (if not done)
python -m venv venv
.\venv\Scripts\Activate.ps1
```

## Starting Services

```powershell
# Start MCP Server (Method 1 - Direct)
npm run start:mcp

# Start MCP Server (Method 2 - Using startup script)
.\start-mcp.ps1

# Run Python Orchestrator (Dry-run)
python .\ticket_orchestrator.py

# Run Python Orchestrator (Live - be careful!)
# Set DRY_RUN=false in .env, then:
python .\ticket_orchestrator.py
```

## Testing

```powershell
# Test Jira connection
python jira_connect.py

# Test MCP server in separate terminal
npm run start:mcp

# Test Python orchestrator (dry-run)
python .\ticket_orchestrator.py
```

## Configuration

```powershell
# Edit configuration
code .env

# Edit environment template
code .env.example

# Edit MCP config
code cline_mcp_config.json

# Edit routing rules
code ticket_orchestrator.py  # Edit rule_based_route() function

# Edit AI classification
code ai_client.py  # Edit system prompt in classify_ticket()
```

## Project Structure Navigation

```powershell
# Main orchestrator
code ticket_orchestrator.py

# Jira helper
code jira_connect.py

# MCP Server
code jira-mcp-server.js

# AI Classification
code ai_client.py

# Configuration
code cline_mcp_config.json

# Documentation
code README.md
code MCP_SETUP_GUIDE.md
code PROJECT_SCAN_REPORT.md
```

## Debugging

```powershell
# Check environment variables
echo $env:JIRA_URL
echo $env:JIRA_PAT
echo $env:GITHUB_TOKEN

# Run with debug output
python .\ticket_orchestrator.py -v

# Check Node processes
Get-Process node

# Kill Node processes if stuck
Stop-Process -Name node -Force

# Clear npm cache
npm cache clean --force
```

## Git Operations

```powershell
# Check git status
git status

# See what's staged
git diff --cached

# Unstage all files
git reset

# Unstage specific file
git reset HEAD filename

# View git log
git log --oneline -n 10
```

## Common Tasks

### Add New APAC Keyword
```powershell
# 1. Edit .env
APAC_KEYWORDS=ctrip,autor,vienna,new_keyword

# 2. Restart MCP server
npm run start:mcp

# 3. Restart orchestrator
python .\ticket_orchestrator.py
```

### Add New Routing Rule
```powershell
# 1. Edit ticket_orchestrator.py
# 2. Add rule in rule_based_route() function
# 3. Test with DRY_RUN=true
python .\ticket_orchestrator.py

# 4. Enable in .env: DRY_RUN=false
# 5. Run again: python .\ticket_orchestrator.py
```

### Change Assignee
```powershell
# Edit .env:
APAC_ASSIGNEE=new_username
IMN_ASSIGNEE=another_username

# Restart services
npm run start:mcp
python .\ticket_orchestrator.py
```

### Test Single Ticket
```powershell
# Edit .env:
TEST_ISSUE_KEY=CRSUP-4422

# Run:
python .\ticket_orchestrator.py

# This will only process that single ticket
```

## Troubleshooting Commands

```powershell
# Verify Node.js and npm
node --version
npm --version

# Verify Python and pip
python --version
pip --version

# List installed Python packages
pip list

# List installed npm packages
npm list

# Check npm registry
npm config get registry

# Verify .env file exists and is readable
Test-Path .env
Get-Content .env | Select-Object -First 10

# Check if port 9000 is in use (if using local MCP)
netstat -ano | findstr :9000

# Test Jira connectivity
python -c "from jira import JIRA; import os; from dotenv import load_dotenv; load_dotenv(); print(JIRA(server=os.getenv('JIRA_URL'), token_auth=os.getenv('JIRA_PAT')).myself())"
```

## Environment Variables Quick Check

```powershell
# Display all configured environment variables
Get-Item env:JIRA_*
Get-Item env:GITHUB_*
Get-Item env:AI_*
Get-Item env:DRY_*

# Set environment variable temporarily
$env:DRY_RUN = "false"

# Set environment variable permanently
[Environment]::SetEnvironmentVariable("DRY_RUN", "false", "User")
```

## File Management

```powershell
# View directory structure
tree /F

# List all Python files
Get-ChildItem -Filter *.py

# List all Node files
Get-ChildItem -Filter *.js

# Find files containing text
Select-String -Path "*.py" -Pattern "IMN_ASSIGNEE"

# View recent changes
git log --oneline -n 5

# View changes to specific file
git log -p -- ticket_orchestrator.py | head -50
```

## Performance Monitoring

```powershell
# Run with timing
Measure-Command { python .\ticket_orchestrator.py }

# Monitor process CPU/Memory
Get-Process node | Format-Table CPU, Memory

# Check disk space
Get-Volume
```

## Documentation & Help

```powershell
# View README
type README.md

# View MCP Setup Guide
type MCP_SETUP_GUIDE.md

# View Project Scan Report
type PROJECT_SCAN_REPORT.md

# View Setup Checklist
type SETUP_CHECKLIST.md

# Open in VS Code
code README.md
code MCP_SETUP_GUIDE.md
```

## Useful Shortcuts

```powershell
# Quick start MCP
.\start-mcp.ps1

# Quick test orchestrator
python .\ticket_orchestrator.py

# Quick check status
git status
npm list
pip list

# Quick edit config
code .env
```

## Quick Copy-Paste Commands

```powershell
# Full setup from scratch
npm install; pip install -r requirements.txt; .\venv\Scripts\Activate.ps1; npm run start:mcp

# Test everything
python jira_connect.py; npm run start:mcp

# Run with dry-run (safe)
$env:DRY_RUN = "true"; python .\ticket_orchestrator.py
```

## Notes

- Replace `python` with `python3` if on macOS/Linux
- Replace `powershell` commands with `bash` equivalents on Linux/macOS
- Always use `DRY_RUN=true` before enabling live mode
- Keep `.env` file secure and never commit to git
- Test routing rules thoroughly before going live

---

**Last Updated:** May 18, 2026
