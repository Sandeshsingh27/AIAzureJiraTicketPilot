# TicketOrchestrator React UI

This is a React (Vite) UI workspace with a ChatGPT-style layout and left sidebar tabs:

- MCP Tools
- Ticket Orchestrator
- How To Use

It is designed to work with the existing Flask backend (`ui_app.py`) on port `5000`.

## Prerequisites

- Node.js 18+ recommended
- Python backend dependencies installed (`requirements.txt`)

## Run Backend

From project root:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```powershell
python .\ui_app.py
```

Backend URL:

- `http://localhost:5000`

## Run React UI

From `frontend` folder:

```powershell
npm install
npm run dev
```

Frontend URL:

- `http://localhost:5173`

Vite proxy is configured so `/chat`, `/jira/*`, and `/run-orchestrator` calls are forwarded to `http://localhost:5000`.

## Build

From `frontend` folder:

```powershell
npm run build
npm run preview
```

## Notes

- This React UI is added as a flexible frontend workspace and does not remove the existing Flask-rendered UI.
- You can incrementally migrate pages/components from Flask templates into React.

