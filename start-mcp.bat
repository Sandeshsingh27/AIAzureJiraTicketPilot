@echo off
REM Ticket Orchestrator MCP - Startup Script
REM Windows batch script to setup and run the project

setlocal enabledelayedexpansion

echo.
echo ======================================
echo Ticket Orchestrator MCP Startup
echo ======================================
echo.

REM Get the current directory
set PROJECT_DIR=%cd%

echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)
echo Python OK

echo [2/5] Checking Node.js installation...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found. Please install Node.js 16+
    pause
    exit /b 1
)
echo Node.js OK

echo [3/5] Checking for dependencies...
if not exist "venv" (
    echo Creating Python virtual environment...
    python -m venv venv
)
if not exist "node_modules" (
    echo Installing Node dependencies...
    call npm install
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install Node dependencies
        pause
        exit /b 1
    )
)
echo Dependencies OK

echo [4/5] Checking .env file...
if not exist ".env" (
    echo ERROR: .env file not found. Please create it from .env.example
    copy .env.example .env
    echo Created .env - please update with your credentials
    pause
    exit /b 1
)
echo .env OK

echo [5/5] Starting Jira MCP Server...
echo.
echo Starting server... Press Ctrl+C to stop
echo.

REM Activate virtual environment and start MCP server
call venv\Scripts\activate.bat
npm run start:mcp

pause
