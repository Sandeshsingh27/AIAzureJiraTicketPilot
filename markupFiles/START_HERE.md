# 🎯 START HERE - Ticket Orchestrator MCP

Welcome! This is a complete Jira automation system with MCP (Model Context Protocol) support for Claude/Cline.

## ⚡ Get Started in 3 Steps (5 minutes)

```powershell
# 1. Install Node dependencies
npm install

# 2. Start MCP server
npm run start:mcp

# 3. In another terminal, test it
python .\ticket_orchestrator.py
```

Done! Your system is now running. ✅

---

## 📚 Documentation

**Where to go:**

| I want to... | Read this |
|--------------|-----------|
| **Get running fast** | `QUICK_START.md` ⚡ |
| **Full overview** | `README.md` 📖 |
| **Step-by-step setup** | `SETUP_CHECKLIST.md` ✅ |
| **All documentation** | `DOCUMENTATION_INDEX.md` 📚 |
| **Command reference** | `COMMANDS.md` 💻 |

---

## 🎯 What This Does

- 🔄 **Fetches tickets** from Jira
- 🧠 **Routes them intelligently** using keywords + AI
- 📤 **Assigns to the right team** (APAC, IMN, or keep with IDD)
- 💬 **Adds smart comments** with team mentions
- 🤖 **Integrates with Claude/Cline** via MCP

---

## 🚀 Key Features

✅ Intelligent ticket routing  
✅ AI-powered classification (GitHub Models)  
✅ Jira MCP server for Claude  
✅ Safe dry-run mode  
✅ Comprehensive documentation  
✅ Production-ready code  

---

## 📋 Quick Commands

```powershell
# Start MCP server
npm run start:mcp

# Run orchestrator (test mode)
python .\ticket_orchestrator.py

# Edit configuration
code .env

# View commands reference
code COMMANDS.md
```

---

## ⚠️ Before You Start

Make sure you have:
- ✅ Python 3.8+
- ✅ Node.js 16+
- ✅ Valid Jira credentials (.env file)
- ✅ GitHub token (for AI models)

---

## 🆘 Need Help?

1. **Just started?** → Read `QUICK_START.md`
2. **Something broke?** → Read `README.md` → Troubleshooting
3. **Need commands?** → Read `COMMANDS.md`
4. **Want architecture?** → Read `PROJECT_STRUCTURE.md`

---

## 📊 Project Status

✅ **Production Ready**  
✅ **Fully Tested**  
✅ **Fully Documented**  
✅ **Security Hardened**  

---

## 🎉 That's It!

You're ready to automate your ticket routing. 

**Next:** Run `npm install` and follow `QUICK_START.md`

Happy automating! 🚀
