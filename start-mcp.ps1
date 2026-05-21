# Ticket Orchestrator MCP - Startup Script (PowerShell)
# Windows PowerShell script to setup and run the project

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Ticket Orchestrator MCP Startup" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

$ProjectDir = Get-Location
$ErrorActionPreference = "Continue"

# Step 1: Check Python
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = & python --version 2>&1
    Write-Host "Python OK: $pythonVersion" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: Python not found. Please install Python 3.8+" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 2: Check Node.js
Write-Host "[2/5] Checking Node.js installation..." -ForegroundColor Yellow
try {
    $nodeVersion = & node --version
    Write-Host "Node.js OK: $nodeVersion" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: Node.js not found. Please install Node.js 16+" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 3: Check dependencies
Write-Host "[3/5] Checking for dependencies..." -ForegroundColor Yellow
if (-not (Test-Path "venv")) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
    & python -m venv venv
}
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing Node dependencies..." -ForegroundColor Cyan
    & npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install Node dependencies" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Write-Host "Dependencies OK" -ForegroundColor Green

# Step 4: Check .env file
Write-Host "[4/5] Checking .env file..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Write-Host "ERROR: .env file not found" -ForegroundColor Red
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host ".env created - please update with your credentials" -ForegroundColor Cyan
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ".env OK" -ForegroundColor Green

# Step 5: Start MCP Server
Write-Host "[5/5] Starting Jira MCP Server..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Starting server... (Press Ctrl+C to stop)" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
& ".\venv\Scripts\Activate.ps1"

# Start MCP server
& npm run start:mcp

Read-Host "Press Enter to exit"
