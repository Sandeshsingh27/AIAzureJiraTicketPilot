"""
JiraAzureCopilot Web UI
--------------------------
Runs on http://localhost:5000

Tabs:
  1. Ticket Orchestration  – JiraAzureCopilot ticket orchestration engine
  2. Jira MCP Tools       – Get Issue, Search Issues, Create Issue, Add Comment
"""
import os
import subprocess
import sys
import threading
import queue
import json
import re
import requests
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, Response, stream_with_context
from dotenv import load_dotenv
from ticket_modules.support_ticket_analyzer import run as run_support_ticket_analysis

try:
    from ticket_modules.chat.chat_agent import run_chat as _agent_run_chat
    _CHAT_OK = True
    _CHAT_ERR = ""
except Exception as _e:
    _CHAT_OK = False
    _CHAT_ERR = str(_e)
    _agent_run_chat = None

load_dotenv()

app = Flask(__name__)

JIRA_URL  = os.getenv("JIRA_URL", "").rstrip("/")
JIRA_PAT  = os.getenv("JIRA_PAT", "")

JIRA_HEADERS = {
    "Authorization": f"Bearer {JIRA_PAT}",
    "Content-Type":  "application/json",
    "Accept":        "application/json",
}

KEYWORDS_FILE = Path(__file__).resolve().parents[2] / "ticket_analysis_keywords.json"


def _int_env(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


BULK_DRY_RUN_SINCE_HOURS = _int_env("BULK_DRY_RUN_SINCE_HOURS", 24, minimum=1, maximum=240)
BULK_DRY_RUN_SAMPLE_SIZE = _int_env("BULK_DRY_RUN_SAMPLE_SIZE", 3, minimum=1, maximum=10)
SINGLE_ANALYZE_SINCE_HOURS = _int_env("SINGLE_ANALYZE_SINCE_HOURS", 24, minimum=1, maximum=240)


def _load_availability_keywords_for_ui() -> list[str]:
    default_keywords = ["hotel not available", "hotel unavailable", "hotel not bookable"]
    try:
        payload = json.loads(KEYWORDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_keywords
    raw = payload.get("availabilityKeywords") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return default_keywords
    out: list[str] = []
    for item in raw:
        kw = str(item or "").strip()
        if kw and kw.lower() not in [x.lower() for x in out]:
            out.append(kw)
    return out or default_keywords


def _resolve_orchestrator_script() -> str:
    """Find the orchestrator entry script regardless of current module location."""
    here = Path(__file__).resolve()
    candidates = [
        # Root compatibility entrypoint
        here.parents[2] / "ticket_orchestrator.py",
        # Direct module implementation
        here.parents[1] / "orchestrator.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    # Keep previous behavior as final fallback (will still error clearly if missing)
    return str(here.parent / "ticket_orchestrator.py")

# ─── HTML Template ────────────────────────────────────────────────────────────
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>🎫 TicketOrchestrator UI</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0;
           min-height: 100vh; display: flex; flex-direction: column; }

    header { background: linear-gradient(135deg, #1e293b, #0f172a); padding: 18px 32px;
             border-bottom: 1px solid #334155; display:flex; align-items:center; gap:12px; }
    header h1 { font-size: 1.5rem; font-weight: 700; color: #f8fafc; }
    header span { font-size: 1.8rem; }

    .tabs { display:flex; gap:4px; padding: 16px 32px 0; border-bottom: 1px solid #1e293b; }
    .tab-btn { padding: 10px 24px; border: none; border-radius: 8px 8px 0 0; cursor:pointer;
               font-size: .95rem; font-weight: 600; background: #1e293b; color: #94a3b8;
               transition: all .2s; }
    .tab-btn.active { background: #3b82f6; color: #fff; }
    .tab-btn:hover:not(.active) { background: #334155; color: #e2e8f0; }

    .tab-content { display:none; padding: 28px 32px; }
    .tab-content.active { display:block; }

    /* ── Orchestrator ── */
    .orch-controls { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:16px; }
    .orch-controls label { font-size:.9rem; color:#94a3b8; }
    .orch-controls select, .orch-controls input[type=text] {
      background: #1e293b; border: 1px solid #334155; color:#e2e8f0;
      padding: 8px 12px; border-radius: 6px; font-size:.9rem; }
    .btn { padding: 10px 22px; border:none; border-radius: 8px; font-weight:600;
           cursor:pointer; font-size:.9rem; transition: all .2s; }
    .btn-blue  { background:#3b82f6; color:#fff; }
    .btn-blue:hover  { background:#2563eb; }
    .btn-red   { background:#ef4444; color:#fff; }
    .btn-red:hover   { background:#dc2626; }
    .btn-green { background:#10b981; color:#fff; }
    .btn-green:hover { background:#059669; }
    .btn-gray  { background:#334155; color:#e2e8f0; }
    .btn-gray:hover  { background:#475569; }
    #orch-output { background:#0a0f1e; border:1px solid #1e293b; border-radius:10px;
                   padding:16px; font-family:monospace; font-size:.85rem; color:#a3e635;
                   min-height:240px; max-height:390px; overflow-y:auto; white-space:pre-wrap;
                   line-height:1.6; }
    .status-badge { padding:4px 12px; border-radius:20px; font-size:.8rem; font-weight:700; }
    .status-idle    { background:#1e293b; color:#94a3b8; }
    .status-running { background:#f59e0b; color:#000; }
    .status-done    { background:#10b981; color:#000; }
    .status-error   { background:#ef4444; color:#fff; }

    /* ── Jira Tools ── */
    .tools-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(360px,1fr)); gap:20px; }
    .tool-card { background:#1e293b; border:1px solid #334155; border-radius:12px; padding:22px; }
    .tool-card h3 { font-size:1rem; font-weight:700; color:#38bdf8; margin-bottom:14px;
                    display:flex; align-items:center; gap:8px; }
    .tool-card h3 span { font-size:1.2rem; }
    .form-group { margin-bottom:12px; }
    .form-group label { display:block; font-size:.82rem; color:#94a3b8; margin-bottom:4px; }
    .form-group input, .form-group textarea, .form-group select {
      width:100%; background:#0f172a; border:1px solid #334155; color:#e2e8f0;
      padding:9px 12px; border-radius:6px; font-size:.9rem; resize:vertical; }
    .form-group input:focus, .form-group textarea:focus { outline:none; border-color:#3b82f6; }
    .result-box { margin-top:14px; background:#0a0f1e; border:1px solid #1e293b;
                  border-radius:8px; padding:12px; font-family:monospace; font-size:.82rem;
                  color:#86efac; min-height:60px; max-height:260px; overflow-y:auto;
                  white-space:pre-wrap; display:none; }
    .help-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }
    .help-card { background:#1e293b; border:1px solid #334155; border-radius:10px; padding:16px; }
    .help-card h3 { color:#38bdf8; margin-bottom:8px; font-size:1rem; }
    .help-card ol, .help-card ul { margin:8px 0 0 18px; color:#cbd5e1; line-height:1.5; }
    .help-card code { background:#0a0f1e; padding:2px 6px; border-radius:5px; }
    .spinner { display:inline-block; width:14px; height:14px; border:2px solid #94a3b8;
               border-top-color:#3b82f6; border-radius:50%; animation:spin .7s linear infinite;
               margin-left:8px; vertical-align:middle; }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Results table ── */
    .results-table { width:100%; border-collapse:collapse; margin-top:12px; font-size:.85rem; }
    .results-table th { background:#0f172a; color:#94a3b8; padding:8px 12px; text-align:left;
                        border-bottom:1px solid #334155; }
    .results-table td { padding:8px 12px; border-bottom:1px solid #1e293b; vertical-align:top; }
    .results-table tr:hover td { background:#1e293b44; }
    .priority-P1,.priority-Blocker { color:#f87171; font-weight:700; }
    .priority-P2,.priority-Critical { color:#fb923c; font-weight:700; }
    .priority-P3,.priority-Major { color:#facc15; }
    .priority-Normal,.priority-Minor { color:#86efac; }
    a.key-link { color:#38bdf8; text-decoration:none; }
    a.key-link:hover { text-decoration:underline; }

    footer { text-align:center; padding:20px; color:#475569; font-size:.8rem;
             margin-top:auto; border-top:1px solid #1e293b; background:#0a0f1e; }
  </style>
</head>
<body>

<header>
  <span>🎫</span>
  <h1>TicketOrchestrator UI</h1>
</header>

<!-- Tabs -->
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('orchestrator',this)">🤖 Ticket Orchestrator</button>
  <button class="tab-btn"        onclick="switchTab('jira',this)">🔧 Jira MCP Tools</button>
  <button class="tab-btn"        onclick="switchTab('chat',this)">💬 AI Chat</button>
  <button class="tab-btn"        onclick="switchTab('howto',this)">📘 How To Use</button>
</div>

<!-- ══════════════════ TAB 1: Ticket Orchestrator ══════════════════ -->
<div id="tab-orchestrator" class="tab-content active">
  <div class="orch-controls">
    <label>Mode:</label>
    <select id="dry-run-sel">
      <option value="true">🔍 Dry Run (preview only)</option>
      <option value="false">🚀 Live (modify Jira)</option>
    </select>
    <label style="margin-left:12px;">Test Issue Key (optional):</label>
    <input type="text" id="test-key" placeholder="e.g. CRSUP-4421" style="width:170px"/>
    <button class="btn btn-blue"  onclick="runOrchestrator()">▶ Run</button>
    <button class="btn btn-red"   onclick="stopOrchestrator()" id="stop-btn" disabled>■ Stop</button>
    <button class="btn btn-gray"  onclick="clearOutput()">🗑 Clear</button>
    <span id="orch-status" class="status-badge status-idle">Idle</span>
  </div>
  <div id="orch-output">Ready. Click ▶ Run to start JiraAzureCopilot ticket orchestration...</div>

  <!-- Results (hidden until run completes) -->
  <div id="results-section" style="display:none;">
  <div style="margin-top:24px;">
    <h3 style="font-size:1.05rem; color:#38bdf8; margin-bottom:10px; display:flex; align-items:center; gap:8px;">
      <span>📦</span> Moved / Routed Tickets
      <span id="moves-count" style="background:#1e293b; color:#94a3b8; padding:2px 10px;
            border-radius:12px; font-size:.75rem; font-weight:600;">0</span>
    </h3>
    <div id="moves-empty" style="color:#94a3b8; font-size:.9rem; padding:14px; background:#1e293b;
         border:1px dashed #334155; border-radius:8px;">
      No moved tickets detected yet. Run the orchestrator to see results here.
    </div>
    <div style="max-height:500px; overflow:auto; border-radius:8px; border:1px solid #1e293b;">
    <table class="results-table" id="moves-table" style="display:none; margin-top:0;">
      <thead style="position:sticky; top:0; z-index:1;">
        <tr>
          <th>Ticket</th>
          <th>Title</th>
          <th>Routed To</th>
          <th>New Assignee</th>
          <th>Matched Keywords</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="moves-body"></tbody>
    </table>
    </div>
  </div>

  <!-- Kept (not routed) Tickets table -->
  <div style="margin-top:24px;">
    <h3 style="font-size:1.05rem; color:#facc15; margin-bottom:10px; display:flex; align-items:center; gap:8px;">
      <span>📥</span> Kept Tickets (Not Routed)
      <span id="kept-count" style="background:#1e293b; color:#94a3b8; padding:2px 10px;
            border-radius:12px; font-size:.75rem; font-weight:600;">0</span>
    </h3>
    <div id="kept-empty" style="color:#94a3b8; font-size:.9rem; padding:14px; background:#1e293b;
         border:1px dashed #334155; border-radius:8px;">
      No kept tickets yet. Tickets that stay in IDD/CRS will appear here.
    </div>
    <div style="max-height:500px; overflow:auto; border-radius:8px; border:1px solid #1e293b;">
    <table class="results-table" id="kept-table" style="display:none; margin-top:0;">
      <thead style="position:sticky; top:0; z-index:1;">
        <tr>
          <th>Ticket</th>
          <th>Title</th>
          <th>Decision</th>
        </tr>
      </thead>
      <tbody id="kept-body"></tbody>
    </table>
    </div>
  </div>
  </div><!-- /results-section -->
</div>

<!-- ══════════════════ TAB 2: Jira MCP Tools ══════════════════ -->
<div id="tab-jira" class="tab-content">

  <!-- Single toolbar card: dropdown + dynamic inputs + action button -->
  <div style="display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end;
              background:#1e293b; padding:18px; border:1px solid #334155;
              border-radius:10px; margin-bottom:16px;">

    <div style="display:flex; flex-direction:column; flex:1; min-width:220px;">
      <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Tool</label>
      <select id="jira-tool" onchange="switchJiraTool()"
              style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                     padding:11px 14px; border-radius:8px; font-size:.95rem; font-weight:600;">
        <option value="get">🔍 Get Issue</option>
        <option value="search">🔎 Search Issues (JQL)</option>
        <option value="concept">🧠 Search Concept</option>
        <option value="create">➕ Create Issue</option>
        <option value="comment">💬 Add Comment</option>
        <option value="assign">👤 Assign Issue</option>
        <option value="link">🔗 Link Issues</option>
        <option value="analyze">🧪 Analyze Support Ticket</option>
        <option value="analyze-bulk">📚 Bulk Analyze (CRSUP Dry Run)</option>
      </select>
    </div>

    <!-- Get Issue inputs -->
    <div class="jira-inputs" id="inputs-get" style="display:flex; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; flex:1; min-width:240px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Issue Key</label>
        <input type="text" id="gi-key" placeholder="e.g. CRSUP-4421"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <button class="btn btn-blue" onclick="getIssue()" style="padding:11px 28px; font-size:.95rem;">Fetch</button>
    </div>

    <!-- Search Issues inputs -->
    <div class="jira-inputs" id="inputs-search" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; flex:1; min-width:300px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">JQL Query</label>
        <input type="text" id="si-jql" placeholder="project=CRSUP AND status=Open"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; width:110px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Max</label>
        <input type="number" id="si-max" value="10" min="1" max="100"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <button class="btn btn-blue" onclick="searchIssues()" style="padding:11px 28px; font-size:.95rem;">Search</button>
    </div>

    <!-- Search Concept inputs -->
    <div class="jira-inputs" id="inputs-concept" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; flex:2; min-width:300px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Phrases (comma-separated)</label>
        <input type="text" id="sc-phrases" placeholder="hotel unavailable, hotel not available, property unavailable"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; width:130px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Field</label>
        <select id="sc-field" style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;">
          <option value="text">text</option><option value="summary">summary</option><option value="description">description</option><option value="comment">comment</option>
        </select>
      </div>
      <button class="btn btn-blue" onclick="searchConcept()" style="padding:11px 28px; font-size:.95rem;">Search</button>
    </div>

    <!-- Create Issue inputs -->
    <div class="jira-inputs" id="inputs-create" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; width:140px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Project</label>
        <input type="text" id="ci-project" placeholder="CRSUP"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; width:150px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Type</label>
        <select id="ci-type"
                style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                       padding:11px 14px; border-radius:8px; font-size:.95rem;">
          <option>Task</option><option>Bug</option><option>Story</option>
          <option>Epic</option><option>Sub-task</option>
        </select>
      </div>
      <div style="display:flex; flex-direction:column; flex:1; min-width:240px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Summary</label>
        <input type="text" id="ci-summary" placeholder="Issue title"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; flex:1; min-width:240px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Description</label>
        <input type="text" id="ci-desc" placeholder="Optional"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <button class="btn btn-green" onclick="createIssue()" style="padding:11px 28px; font-size:.95rem;">Create</button>
    </div>

    <!-- Add Comment inputs -->
    <div class="jira-inputs" id="inputs-comment" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; width:200px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Issue Key</label>
        <input type="text" id="ac-key" placeholder="e.g. CRSUP-4421"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; flex:1; min-width:300px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Comment</label>
        <input type="text" id="ac-comment" placeholder="Your comment..."
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                      padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <button class="btn btn-green" onclick="addComment()" style="padding:11px 28px; font-size:.95rem;">Post</button>
    </div>

    <!-- Assign Issue inputs -->
    <div class="jira-inputs" id="inputs-assign" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; width:200px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Issue Key</label>
        <input type="text" id="as-key" placeholder="e.g. CRSUP-4421"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; width:220px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Assignee (username)</label>
        <input type="text" id="as-user" placeholder="e.g. nsh50"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <button class="btn btn-green" onclick="assignIssue()" style="padding:11px 28px; font-size:.95rem;">Assign</button>
    </div>

    <!-- Link Issues inputs -->
    <div class="jira-inputs" id="inputs-link" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; width:180px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Inward Issue</label>
        <input type="text" id="li-inward" placeholder="e.g. CRSUP-5000"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; width:180px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Outward Issue</label>
        <input type="text" id="li-outward" placeholder="e.g. CRSUP-5001"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; width:150px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Link Type</label>
        <input type="text" id="li-type" value="Relates"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <button class="btn btn-green" onclick="linkIssues()" style="padding:11px 28px; font-size:.95rem;">Link</button>
    </div>

    <!-- Analyze Support Ticket inputs -->
    <div class="jira-inputs" id="inputs-analyze" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; width:200px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Issue Key</label>
        <input type="text" id="an-key" placeholder="e.g. CRSUP-4421"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; align-items:center; gap:8px; color:#cbd5e1; font-size:.9rem;">
        <input type="checkbox" id="an-exec" /> Execute API
      </div>
      <button class="btn btn-blue" onclick="analyzeSupportTicket()" style="padding:11px 28px; font-size:.95rem;">Analyze</button>
    </div>

    <!-- Bulk Analyze inputs (CRSUP dry-run only) -->
    <div class="jira-inputs" id="inputs-analyze-bulk" style="display:none; flex:2; gap:12px; align-items:flex-end; flex-wrap:wrap;">
      <div style="display:flex; flex-direction:column; width:130px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Project</label>
        <input type="text" value="CRSUP" disabled
               style="background:#111827; border:1px solid #334155; color:#94a3b8; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; flex-direction:column; flex:1; min-width:320px;">
        <label style="font-size:.82rem; color:#94a3b8; margin-bottom:6px;">Extra Keywords (optional, comma-separated)</label>
        <input type="text" id="ab-extra-keywords" placeholder="e.g. hotel closed, property suspended"
               style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:11px 14px; border-radius:8px; font-size:.95rem;"/>
      </div>
      <div style="display:flex; align-items:center; gap:8px; color:#cbd5e1; font-size:.9rem;">
        <input type="checkbox" id="ab-exec-api" /> Execute API
      </div>
      <div style="display:flex; align-items:center; gap:8px; color:#cbd5e1; font-size:.9rem;">
        <input type="checkbox" id="ab-jira-comment" /> Enable Jira Comment Posting (CRSUP only)
      </div>
      <div style="display:flex; align-items:center; color:#facc15; font-size:.82rem;">
        Since hours and sample size are fixed by backend env defaults. Safe defaults keep API and commenting off.
      </div>
      <div style="display:flex; align-items:center; color:#94a3b8; font-size:.8rem; width:100%;">
        Both off by default for safe production testing.
      </div>
      <button class="btn btn-blue" onclick="analyzeBulkDryRun()" style="padding:11px 28px; font-size:.95rem;">Run Bulk Dry Run</button>
    </div>
  </div>

  <!-- Single result area below toolbar -->
  <div class="result-box" id="jira-result" style="display:block; min-height:120px;">
    <span style="color:#64748b;">Result will appear here after running a tool…</span>
  </div>
</div>

<!-- ══════════════════ TAB 3: AI Chat ══════════════════ -->
<div id="tab-chat" class="tab-content">
  <div style="display:flex; flex-direction:column; height:calc(100vh - 240px); min-height:480px;
              background:#1e293b; border:1px solid #334155; border-radius:10px; overflow:hidden;">

    <!-- Header / examples -->
    <div style="padding:14px 18px; border-bottom:1px solid #334155; display:flex;
                gap:10px; align-items:center; flex-wrap:wrap;">
      <span style="color:#38bdf8; font-weight:700; font-size:1rem;">💬 JiraAzureCopilot</span>
      <span style="color:#64748b; font-size:.8rem;">— Ask naturally or use prompt library below for common workflows.</span>
      <div style="flex:1;"></div>
      <button class="btn btn-gray" onclick="resetChat()" style="padding:6px 14px; font-size:.8rem;">🗑 New Chat</button>
    </div>

    <div class="chat-utility-wrap">
      <details class="prompt-help" open>
        <summary>🧠 Prompt Library</summary>
        <div class="prompt-form-row">
          <div class="prompt-field">
            <label>Category</label>
            <select id="prompt-category" onchange="renderPromptTemplates()"></select>
          </div>
          <div class="prompt-field" style="flex:2;">
            <label>Template</label>
            <select id="prompt-template"></select>
          </div>
          <button class="btn btn-gray" onclick="insertSelectedPrompt(false)" style="padding:8px 14px; font-size:.8rem;">Insert</button>
          <button class="btn btn-blue" onclick="insertSelectedPrompt(true)" style="padding:8px 14px; font-size:.8rem;">Insert & Send</button>
        </div>
      </details>

      <details class="prompt-help">
        <summary>📘 How to ask better</summary>
        <div class="prompt-tips">
          <div>- Mention issue key for single-ticket actions: <code>CRSUP-4421</code></div>
          <div>- For bulk dry-run in chat: use toggle flags and optional extra keywords</div>
          <div>- Use <code>enableJiraComment false</code> for safe testing</div>
          <div>- Add extra keywords with: <code>extra keywords: hotel closed, property suspended</code></div>
        </div>
      </details>
    </div>

    <details class="prompt-help" style="border-top:none;">
      <summary>✨ Quick examples</summary>
      <div class="prompt-grid">
        <button class="prompt-chip" onclick="usePrompt('Find all open CRSUP tickets about Hotel Unavailable')">Find open CRSUP unavailable tickets</button>
        <button class="prompt-chip" onclick="usePrompt('Show details of CRSUP-4421')">Show issue details</button>
        <button class="prompt-chip" onclick="usePrompt('Analyze support ticket CRSUP-4421 for hotel unavailable. Check New Relic logs from last 24 hours and build the singleavail payload.')">Analyze single ticket</button>
        <button class="prompt-chip" onclick="usePrompt('Run bulk dry-run analysis for CRSUP with safe defaults, executeApi false, enableJiraComment false.')">Bulk dry run safe defaults</button>
      </div>
    </details>

    <!-- Messages area -->
    <div id="chat-messages" style="flex:1; overflow-y:auto; padding:18px;
                                   display:flex; flex-direction:column; gap:14px;">
      <div class="chat-msg chat-bot">
        <div class="chat-bubble">
          👋 Hi! I'm JiraAzureCopilot. You can use the example prompts section above, or try:
          <ul style="margin:8px 0 0 18px; color:#94a3b8;">
            <li>"Find all open CRSUP tickets about Hotel Unavailable"</li>
            <li>"Show details of CRSUP-4421"</li>
            <li>"Find similar tickets to CRSUP-4421, create a parent ticket and link them all"</li>
            <li>"Analyze support ticket CRSUP-4421 for hotel unavailable. Check New Relic logs from last 24 hours and build the singleavail payload."</li>
            <li>"Run end-to-end analysis for CRSUP-4421, include New Relic check, build payload, and execute the singleavail API call."</li>
            <li>"Run bulk dry-run analysis for CRSUP with safe defaults, executeApi false, enableJiraComment false."</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Tool trace (collapsible) -->
    <details id="chat-trace-wrap" style="border-top:1px solid #334155; padding:10px 18px;
                                          background:#0f172a; display:none;">
      <summary style="cursor:pointer; color:#94a3b8; font-size:.82rem;">🔧 Tools used in last turn</summary>
      <pre id="chat-trace" style="margin-top:8px; color:#a3e635; font-size:.78rem;
                                   white-space:pre-wrap; max-height:200px; overflow:auto;"></pre>
    </details>

    <!-- Input bar -->
    <div style="padding:14px 18px; border-top:1px solid #334155; display:flex; gap:10px;">
      <textarea id="chat-input" rows="2" placeholder="Ask JiraAzureCopilot anything..."
                onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault(); sendChat();}"
                style="flex:1; background:#0f172a; border:1px solid #334155; color:#e2e8f0;
                       padding:11px 14px; border-radius:8px; font-size:.92rem; resize:none;
                       font-family:inherit;"></textarea>
      <button class="btn btn-blue" id="chat-send-btn" onclick="sendChat()"
              style="padding:11px 24px; font-size:.95rem;">Send</button>
    </div>
  </div>
</div>

<!-- ══════════════════ TAB 4: How To Use ══════════════════ -->
<div id="tab-howto" class="tab-content">
  <div class="help-grid">
    <div class="help-card">
      <h3>🚀 Quick Start</h3>
       <ol>
         <li>Use <code>🔧 Jira MCP Tools</code> when you want direct UI actions and structured inputs.</li>
         <li>Use <code>💬 AI Chat</code> when you want natural-language workflows, prompt templates, and dry-run chat commands.</li>
         <li>Use <code>🤖 JiraAzureCopilot</code> for ticket orchestration, routing and reassignment workflows.</li>
       </ol>
    </div>
    <div class="help-card">
      <h3>🔧 Jira MCP Tools (UI)</h3>
      <ul>
        <li><b>Get Issue</b>: fetch ticket details by key.</li>
        <li><b>Search Issues</b>: run raw JQL.</li>
        <li><b>Search Concept</b>: phrase-based search (comma-separated variants).</li>
        <li><b>Create / Comment / Assign / Link</b>: perform Jira actions directly.</li>
        <li><b>Analyze Support Ticket</b>: single-ticket Jira + New Relic + payload analysis.</li>
        <li><b>Bulk Analyze (CRSUP Dry Run)</b>: sample-based keyword analysis for CRSUP tickets.</li>
      </ul>
    </div>
    <div class="help-card">
      <h3>💬 AI Chat Features</h3>
      <ul>
        <li>Use the <b>Prompt Library</b> dropdowns to insert common requests.</li>
        <li>Use <b>Insert</b> to edit before sending, or <b>Insert &amp; Send</b> to run immediately.</li>
        <li>Use <b>Quick examples</b> for one-click starter prompts.</li>
        <li>Use the collapsible <b>How to ask better</b> section for dry-run syntax guidance.</li>
      </ul>
    </div>
    <div class="help-card">
      <h3>💬 Example Chat Prompts</h3>
      <ul>
        <li><code>Find all open CRSUP tickets about hotel unavailable</code></li>
        <li><code>Show details of CRSUP-4421</code></li>
        <li><code>Create a parent issue for these tickets and link them</code></li>
        <li><code>Analyze CRSUP-4421 for hotel unavailable and execute singleavail API</code></li>
        <li><code>Run bulk dry-run analysis for CRSUP with safe defaults, executeApi false, enableJiraComment false.</code></li>
        <li><code>/bulk-dry-run executeApi=true enableJiraComment=false extra keywords: hotel closed</code></li>
      </ul>
    </div>
    <div class="help-card">
      <h3>🧪 Analyze Support Ticket Steps</h3>
      <ol>
        <li>Select <code>Analyze Support Ticket</code> in Jira MCP Tools.</li>
        <li>Enter issue key (lookback window comes from backend env default).</li>
        <li>Optionally tick <code>Execute API</code>.</li>
        <li>Click <code>Analyze</code> and inspect payload, New Relic summary, response, and Jira comment result.</li>
      </ol>
    </div>
    <div class="help-card">
      <h3>📚 Bulk Analyze (CRSUP Dry Run) Steps</h3>
      <ol>
        <li>Select <code>Bulk Analyze (CRSUP Dry Run)</code> in Jira MCP Tools.</li>
         <li>Since and sample size are fixed by backend env defaults.</li>
        <li>Optionally add <code>Extra Keywords</code> to extend the backend keyword list.</li>
        <li>Use <code>Execute API</code> only if you want EC2 singleavail executed during dry run.</li>
        <li>Use <code>Enable Jira Comment Posting (CRSUP only)</code> only when you want real comments posted.</li>
        <li>Otherwise keep both toggles off for safe production testing.</li>
        <li>Review matched tickets, dry-run log, and would-be Jira comment preview in the result.</li>
      </ol>
    </div>
    <div class="help-card">
      <h3>🧩 Toggle Meanings</h3>
      <ul>
        <li><b>Execute API</b>: runs the EC2 singleavail call for the analyzed ticket(s).</li>
        <li><b>Enable Jira Comment Posting (CRSUP only)</b>: posts actual Jira comments on CRSUP tickets.</li>
        <li><b>Jira comment preview</b>: generated in dry-run results for testing when available.</li>
        <li><b>Bulk defaults</b>: since-hours and sample-size are read from backend env configuration.</li>
      </ul>
    </div>
    <div class="help-card">
      <h3>🛡 Safety Rules</h3>
      <ul>
        <li>Bulk analysis is restricted to <code>CRSUP</code>.</li>
        <li>Both bulk toggles default to off for safe production testing.</li>
        <li>If core identifiers are missing from a ticket, analyzer skips broad NRQL fallback and asks for required fields.</li>
        <li>Availability keywords come from the backend config and optional extra keywords you provide.</li>
      </ol>
    </div>
  </div>
</div>

<style>
.chat-msg { display:flex; gap:10px; }
.chat-msg.chat-user { justify-content:flex-end; }
.chat-bubble { max-width:78%; padding:11px 14px; border-radius:10px; font-size:.9rem;
               line-height:1.5; word-wrap:break-word; }
.chat-bot .chat-bubble  { background:#0f172a; border:1px solid #334155; color:#e2e8f0; }
.chat-user .chat-bubble { background:#3b82f6; color:#fff; }
.chat-bubble a { color:#38bdf8; text-decoration:underline; }
.chat-bubble ul, .chat-bubble ol { margin:6px 0 6px 20px; }
.chat-bubble pre { background:#0a0f1e; padding:8px; border-radius:6px;
                   overflow:auto; font-size:.8rem; margin:6px 0; }
.chat-bubble code { background:#0a0f1e; padding:1px 6px; border-radius:4px; font-size:.85em; }
.chat-typing { color:#94a3b8; font-style:italic; }
.chat-typing::after { content:'▎'; animation:blink 1s infinite; }
.chat-utility-wrap { border-top:1px solid #334155; background:#0f172a; }
.prompt-help { border-top:1px solid #334155; background:#0f172a; padding:10px 18px; }
.prompt-help summary { cursor:pointer; color:#94a3b8; font-size:.82rem; }
.prompt-form-row { margin-top:10px; display:flex; gap:8px; align-items:flex-end; flex-wrap:wrap; }
.prompt-field { display:flex; flex-direction:column; min-width:180px; flex:1; }
.prompt-field label { font-size:.75rem; color:#94a3b8; margin-bottom:4px; }
.prompt-field select { background:#1e293b; border:1px solid #334155; color:#e2e8f0; border-radius:7px; padding:8px 10px; font-size:.82rem; }
.prompt-grid { margin-top:10px; display:flex; flex-wrap:wrap; gap:8px; }
.prompt-chip { background:#1e293b; border:1px solid #334155; color:#cbd5e1; border-radius:999px;
               padding:6px 10px; font-size:.78rem; cursor:pointer; }
.prompt-chip:hover { border-color:#3b82f6; color:#e2e8f0; }
.prompt-tips { margin-top:10px; display:grid; gap:6px; color:#cbd5e1; font-size:.8rem; }
@keyframes blink { 50% { opacity:0; } }
</style>

<footer>TicketOrchestrator UI • Flask Backend • Jira REST API</footer>

<script>
// ── Tab switching ───────���──────────────────────────────────────
function switchTab(name, el) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
}

// ── Jira tool dropdown switch ─────────────────────────────────
function switchJiraTool() {
  const v = document.getElementById('jira-tool').value;
  document.querySelectorAll('.jira-inputs').forEach(p => p.style.display = 'none');
  const panel = document.getElementById('inputs-' + v);
  if (panel) panel.style.display = 'flex';
  const res = document.getElementById('jira-result');
  res.innerHTML = '<span style="color:#64748b;">Result will appear here after running a tool…</span>';
}

// ── AI Chat (JiraAzureCopilot) ─────────────────────────────────────
let chatHistory = [];
const PROMPT_LIBRARY = {
  'Search & Discovery': [
    'Find all open CRSUP tickets about Hotel Unavailable',
    'Show details of CRSUP-4421',
    'Find similar tickets to CRSUP-4421, create a parent ticket and link them all'
  ],
  'Single Ticket Analysis': [
    'Analyze support ticket CRSUP-4421 for hotel unavailable. Check New Relic logs from last 24 hours and build the singleavail payload.',
    'Run end-to-end analysis for CRSUP-4421, include New Relic check, build payload, and execute the singleavail API call.'
  ],
  'Bulk Dry Run (CRSUP)': [
    'Run bulk dry-run analysis for CRSUP with safe defaults, executeApi false, enableJiraComment false.',
    'Run bulk dry-run analysis for CRSUP with extra keywords: hotel closed, property suspended; executeApi true; enableJiraComment false.'
  ]
};

function linkifyKeys(text) {
  if (!text) return '';
  const safe = escapeHtml(text);
  if (!JIRA_HOST) return safe;
  return safe.replace(/\\b([A-Z][A-Z0-9]+-\\d+)\\b/g,
    `<a href="${JIRA_HOST}/browse/$1" target="_blank" rel="noopener">$1</a>`);
}

function renderMarkdownLite(text) {
  // very small markdown: bold, italics, code, lists, line breaks
  let s = linkifyKeys(text);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\\*\\*([^*]+)\\*\\*/g, '<b>$1</b>');
  s = s.replace(/(^|\\n)- (.+)/g, '$1• $2');
  s = s.replace(/\\n/g, '<br/>');
  return s;
}

function appendChatMessage(role, text) {
  const box = document.getElementById('chat-messages');
  const wrap = document.createElement('div');
  wrap.className = 'chat-msg ' + (role === 'user' ? 'chat-user' : 'chat-bot');
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.innerHTML = renderMarkdownLite(text);
  wrap.appendChild(bubble);
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return bubble;
}

function showTyping() {
  const box = document.getElementById('chat-messages');
  const wrap = document.createElement('div');
  wrap.className = 'chat-msg chat-bot';
  wrap.id = 'chat-typing-wrap';
  wrap.innerHTML = '<div class="chat-bubble chat-typing">JiraAzureCopilot is thinking</div>';
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
}

function clearTyping() {
  const t = document.getElementById('chat-typing-wrap');
  if (t) t.remove();
}

function initPromptLibrary() {
  const category = document.getElementById('prompt-category');
  if (!category) return;
  const keys = Object.keys(PROMPT_LIBRARY);
  category.innerHTML = keys.map(k => `<option value="${escapeHtml(k)}">${escapeHtml(k)}</option>`).join('');
  renderPromptTemplates();
}

function renderPromptTemplates() {
  const category = document.getElementById('prompt-category');
  const template = document.getElementById('prompt-template');
  if (!category || !template) return;
  const key = category.value;
  const list = PROMPT_LIBRARY[key] || [];
  template.innerHTML = list.map((prompt, idx) => `<option value="${idx}">${escapeHtml(prompt)}</option>`).join('');
}

function insertSelectedPrompt(sendNow) {
  const category = document.getElementById('prompt-category');
  const template = document.getElementById('prompt-template');
  const input = document.getElementById('chat-input');
  if (!category || !template || !input) return;
  const list = PROMPT_LIBRARY[category.value] || [];
  const prompt = list[parseInt(template.value, 10)] || '';
  if (!prompt) return;
  input.value = prompt;
  input.focus();
  if (sendNow) sendChat();
}

function usePrompt(text) {
  const input = document.getElementById('chat-input');
  input.value = text;
  input.focus();
}

function resetChat() {
  chatHistory = [];
  document.getElementById('chat-messages').innerHTML =
    '<div class="chat-msg chat-bot"><div class="chat-bubble">New chat started. How can I help?</div></div>';
  document.getElementById('chat-trace-wrap').style.display = 'none';
  document.getElementById('chat-trace').textContent = '';
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  const btn = document.getElementById('chat-send-btn');
  input.value = '';
  btn.disabled = true; btn.textContent = '...';
  appendChatMessage('user', msg);
  showTyping();

  try {
    const r = await fetch('/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: msg, history: chatHistory }),
    });
    const data = await r.json();
    clearTyping();
    if (data.error) {
      appendChatMessage('bot', '❌ Error: ' + data.error);
    } else {
      appendChatMessage('bot', data.reply || '(no reply)');
      chatHistory = data.history || chatHistory;
      const trace = data.tool_trace || [];
      if (trace.length) {
        document.getElementById('chat-trace-wrap').style.display = 'block';
        document.getElementById('chat-trace').textContent =
          trace.map(t => `→ ${t.tool}(${JSON.stringify(t.args)})\\n   ${JSON.stringify(t.result).slice(0,400)}`).join('\\n\\n');
      } else {
        document.getElementById('chat-trace-wrap').style.display = 'none';
      }
    }
  } catch (e) {
    clearTyping();
    appendChatMessage('bot', '❌ Network error: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Send';
    input.focus();
  }
}

// ── Orchestrator ──────────────────────────────────────────────
let orchController = null;
let movesMap = new Map();
let keptMap = new Map();
const JIRA_HOST = "__JIRA_HOST__";

function setStatus(text, cls) {
  const el = document.getElementById('orch-status');
  el.textContent = text;
  el.className = 'status-badge ' + cls;
}

function appendOutput(text) {
  const box = document.getElementById('orch-output');
  box.textContent += text;
  box.scrollTop = box.scrollHeight;
}

function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function resetMovesTable() {
  movesMap = new Map();
  document.getElementById('moves-body').innerHTML = '';
  document.getElementById('moves-table').style.display = 'none';
  document.getElementById('moves-empty').style.display = 'block';
  document.getElementById('moves-count').textContent = '0';
  document.getElementById('results-section').style.display = 'none';
  resetKeptTable();
}

function resetKeptTable() {
  keptMap = new Map();
  document.getElementById('kept-body').innerHTML = '';
  document.getElementById('kept-table').style.display = 'none';
  document.getElementById('kept-empty').style.display = 'block';
  document.getElementById('kept-count').textContent = '0';
}

function renderKeptTable() {
  const body = document.getElementById('kept-body');
  const table = document.getElementById('kept-table');
  const empty = document.getElementById('kept-empty');
  const cnt = document.getElementById('kept-count');
  const rows = Array.from(keptMap.values());
  cnt.textContent = rows.length;
  if (!rows.length) {
    body.innerHTML = '';
    table.style.display = 'none';
    empty.style.display = 'block';
    return;
  }
  let html = '';
  rows.forEach(k => {
    const href = JIRA_HOST ? (JIRA_HOST + '/browse/' + k.key) : '#';
    html += `<tr>
      <td style="white-space:nowrap; vertical-align:middle;"><a class="key-link" href="${escapeHtml(href)}" target="_blank"><b>${escapeHtml(k.key)}</b></a></td>
      <td style="color:#cbd5e1; vertical-align:middle; word-break:break-word;">${escapeHtml(k.title || '—')}</td>
      <td style="vertical-align:middle;"><span style="background:#1e293b;color:#facc15;padding:3px 10px;border-radius:12px;font-size:.75rem;font-weight:700;">⏸ KEEP</span></td>
    </tr>`;
  });
  body.innerHTML = html;
  table.style.display = '';
  empty.style.display = 'none';
}

function upsertKept(kept) {
  keptMap.set(kept.key, kept);
  // render only on 'done'
}

function renderMovesTable() {
  const body = document.getElementById('moves-body');
  const table = document.getElementById('moves-table');
  const empty = document.getElementById('moves-empty');
  const cnt = document.getElementById('moves-count');
  const rows = Array.from(movesMap.values());
  cnt.textContent = rows.length;
  if (!rows.length) {
    body.innerHTML = '';
    table.style.display = 'none';
    empty.style.display = 'block';
    return;
  }
  const statusBadge = (s) => {
    const map = {
      'moved':      ['#10b981', '#fff', '✓ Moved'],
      'dry-run':    ['#f59e0b', '#000', '🔍 Dry Run'],
      'pending':    ['#3b82f6', '#fff', '⏳ Pending'],
      'classified': ['#64748b', '#fff', '🏷 Classified'],
      'summary':    ['#334155', '#cbd5e1', '📋 Summary'],
      'error':      ['#ef4444', '#fff', '✗ Error'],
    };
    const [bg, fg, lbl] = map[s] || ['#334155', '#cbd5e1', s || '—'];
    return `<span style="background:${bg};color:${fg};padding:3px 10px;border-radius:12px;font-size:.75rem;font-weight:700;">${lbl}</span>`;
  };
  const teamBadge = (t) => {
    if (!t) return '—';
    const c = t.startsWith('APAC') ? '#38bdf8'
            : t.startsWith('IMN')  ? '#a78bfa'
            : '#94a3b8';
    return `<span style="color:${c};font-weight:600;">${escapeHtml(t)}</span>`;
  };
  let html = '';
  rows.forEach(m => {
    const href = JIRA_HOST ? (JIRA_HOST + '/browse/' + m.key) : '#';
    html += `<tr>
      <td style="white-space:nowrap; vertical-align:middle;"><a class="key-link" href="${escapeHtml(href)}" target="_blank"><b>${escapeHtml(m.key)}</b></a></td>
      <td style="color:#cbd5e1; vertical-align:middle; word-break:break-word;">${escapeHtml(m.title || '—')}</td>
      <td style="vertical-align:middle;">${teamBadge(m.target)}</td>
      <td style="vertical-align:middle;">${escapeHtml(m.assignee || '—')}</td>
      <td style="color:#a3e635; font-size:.82rem; vertical-align:middle;">${escapeHtml(m.matched || '—')}</td>
      <td style="vertical-align:middle;">${statusBadge(m.status)}</td>
    </tr>`;
  });
  body.innerHTML = html;
  table.style.display = '';
  empty.style.display = 'none';
}

function upsertMove(move) {
  // Merge by ticket key so later updates (DRY-RUN / OK / report) enrich the same row
  const existing = movesMap.get(move.key) || {};
  const priority = { 'summary': 1, 'classified': 2, 'pending': 3, 'dry-run': 4, 'moved': 5, 'error': 6 };
  const curStatus = existing.status || '';
  const newStatus = move.status || '';
  // keep the higher-priority status if both exist
  const finalStatus = (priority[newStatus] || 0) >= (priority[curStatus] || 0) ? newStatus : curStatus;

  const merged = {
    key:      move.key,
    title:    move.title    || existing.title    || '',
    target:   move.target   || existing.target   || '',
    assignee: move.assignee || existing.assignee || '',
    matched:  move.matched  || existing.matched  || '',
    source:   move.source   || existing.source   || '',
    status:   finalStatus,
    raw:      move.raw      || existing.raw      || '',
  };
  movesMap.set(move.key, merged);
  // render only on 'done' — keep tables hidden during run
}

function clearOutput() {
  document.getElementById('orch-output').textContent = '';
  resetMovesTable();
}

function stopOrchestrator() {
  if (orchController) orchController.abort();
}

async function runOrchestrator() {
  clearOutput();
  setStatus('Running...', 'status-running');
  document.getElementById('stop-btn').disabled = false;

  const dryRun   = document.getElementById('dry-run-sel').value;
  const testKey  = document.getElementById('test-key').value.trim();

  orchController = new AbortController();
  try {
    const resp = await fetch('/run-orchestrator', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ dry_run: dryRun, test_key: testKey }),
      signal: orchController.signal,
    });
    const reader = resp.body.getReader();
    const dec    = new TextDecoder();
    let buffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += dec.decode(value, {stream: true});

      let idx;
      while ((idx = buffer.indexOf('\\n\\n')) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        let event = 'message', data = '';
        frame.split('\\n').forEach(line => {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        });
        if (!data) continue;
        let payload;
        try { payload = JSON.parse(data); } catch (e) { continue; }

        if (event === 'log' && payload.line) {
          appendOutput(payload.line);
        } else if (event === 'move') {
          upsertMove(payload);
        } else if (event === 'kept') {
          upsertKept(payload);
        } else if (event === 'done') {
          appendOutput(`\\n[Exit code: ${payload.exit_code}]\\n`);
          setStatus(payload.exit_code === 0 ? 'Done' : 'Error',
                    payload.exit_code === 0 ? 'status-done' : 'status-error');
          document.getElementById('results-section').style.display = 'block';
          renderMovesTable();
          renderKeptTable();
        }
      }
    }
    if (document.getElementById('orch-status').textContent === 'Running...') {
      setStatus('Done', 'status-done');
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      appendOutput('\\n[Stopped by user]');
      setStatus('Stopped', 'status-error');
    } else {
      appendOutput('\\n[Error] ' + e.message);
      setStatus('Error', 'status-error');
    }
  } finally {
    document.getElementById('stop-btn').disabled = true;
  }
}

// ── Jira helpers ──────────────────────────────────────────────
function showResult(id, data) {
  const el = document.getElementById(id);
  el.style.display = 'block';
  if (typeof data === 'string') { el.textContent = data; return; }
  el.innerHTML = '';
  el.textContent = JSON.stringify(data, null, 2);
}

function showTable(id, issues) {
  const el = document.getElementById(id);
  el.style.display = 'block';
  if (!issues.length) { el.textContent = 'No issues found.'; return; }
  let html = '<div style="max-height:560px; overflow:auto; border-radius:8px; border:1px solid #1e293b;">'
    + '<table class="results-table" style="margin-top:0; width:100%;">'
    + '<thead style="position:sticky; top:0; z-index:1;"><tr>'
    + '<th style="width:120px;">Key</th><th>Summary</th>'
    + '<th style="width:140px;">Status</th><th style="width:110px;">Priority</th>'
    + '<th style="width:180px;">Assignee</th>'
    + '</tr></thead><tbody>';
  issues.forEach(i => {
    const pc = 'priority-' + (i.priority || '').replace(/\\s+/,'');
    const href = JIRA_HOST ? (JIRA_HOST + '/browse/' + i.key) : '#';
    html += `<tr>
      <td style="white-space:nowrap; vertical-align:middle;"><a class="key-link" href="${escapeHtml(href)}" target="_blank" rel="noopener"><b>${escapeHtml(i.key)}</b></a></td>
      <td style="vertical-align:middle; color:#f8fafc; word-break:break-word;">${escapeHtml(i.summary || '')}</td>
      <td style="vertical-align:middle;">${escapeHtml(i.status || '')}</td>
      <td style="vertical-align:middle;" class="${pc}">${escapeHtml(i.priority || '')}</td>
      <td style="vertical-align:middle;">${escapeHtml(i.assignee || '—')}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  el.innerHTML = html;
}

// ── Get Issue ─────────────────────────────────────────────────
function renderIssueCard(id, d) {
  const el = document.getElementById(id);
  el.style.display = 'block';
  if (d.error) {
    el.innerHTML = `<div style="color:#f87171;"><b>Error:</b> ${escapeHtml(d.error)}</div>`;
    return;
  }
  const href = JIRA_HOST ? (JIRA_HOST + '/browse/' + d.key) : '#';
  const prClass = 'priority-' + String(d.priority || '').replace(/\\s+/g, '');
  const statusColor = /done|closed|resolved/i.test(d.status || '') ? '#10b981'
                    : /progress|review/i.test(d.status || '') ? '#3b82f6'
                    : /open|ready|todo/i.test(d.status || '') ? '#facc15'
                    : '#94a3b8';
  const fmt = (v) => v ? new Date(v).toLocaleString() : '—';

  const keyLink = `<a class="key-link" href="${escapeHtml(href)}" target="_blank"><b>${escapeHtml(d.key || '')}</b></a>`;
  const descCell = d.description ? escapeHtml(d.description) : '—';

  el.innerHTML = `
    <div style="max-height:560px; overflow:auto; border-radius:8px; border:1px solid #1e293b;">
      <table class="results-table" style="margin-top:0; width:100%; table-layout:fixed;">
        <thead style="position:sticky; top:0; z-index:1;">
          <tr>
            <th style="width:9%;">Ticket</th>
            <th style="width:22%;">Summary</th>
            <th style="width:10%;">Status</th>
            <th style="width:8%;">Priority</th>
            <th style="width:12%;">Assignee</th>
            <th style="width:12%;">Reporter</th>
            <th style="width:27%;">Description</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="white-space:nowrap; vertical-align:middle;">${keyLink}</td>
            <td style="color:#f8fafc; font-weight:600; vertical-align:middle; word-break:break-word;">${escapeHtml(d.summary || '—')}</td>
            <td style="vertical-align:middle;"><span style="color:${statusColor};font-weight:600;">${escapeHtml(d.status || '—')}</span></td>
            <td style="vertical-align:middle;" class="${prClass}">${escapeHtml(d.priority || '—')}</td>
            <td style="vertical-align:middle;">${escapeHtml(d.assignee || '—')}</td>
            <td style="vertical-align:middle;">${escapeHtml(d.reporter || '—')}</td>
            <td style="vertical-align:middle; color:#cbd5e1; white-space:pre-wrap; word-break:break-word;">${descCell}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
}

async function getIssue() {
  const key = document.getElementById('gi-key').value.trim();
  if (!key) { alert('Enter an issue key'); return; }
  showResult('jira-result', 'Loading...');
  const r = await fetch('/jira/get-issue', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({issueKey: key})
  });
  renderIssueCard('jira-result', await r.json());
}

// ── Search Issues ──────────────────────────��──────────────────
async function searchIssues() {
  const jql = document.getElementById('si-jql').value.trim();
  const max = parseInt(document.getElementById('si-max').value) || 10;
  if (!jql) { alert('Enter a JQL query'); return; }
  showResult('jira-result', 'Searching...');
  const r = await fetch('/jira/search', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({jql, maxResults: max})
  });
  const data = await r.json();
  if (Array.isArray(data)) showTable('jira-result', data);
  else showResult('jira-result', data);
}

// ── Search Concept ─────────────────────────────────────────────
async function searchConcept() {
  const raw = document.getElementById('sc-phrases').value.trim();
  const field = document.getElementById('sc-field').value;
  if (!raw) { alert('Enter comma-separated phrases'); return; }
  const phrases = raw.split(',').map(s => s.trim()).filter(Boolean);
  if (!phrases.length) { alert('Enter valid phrases'); return; }
  showResult('jira-result', 'Searching concept...');
  const r = await fetch('/jira/search-concept', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phrases, field, maxResults: 20})
  });
  const data = await r.json();
  if (Array.isArray(data.issues)) showTable('jira-result', data.issues);
  else showResult('jira-result', data);
}

// ── Create Issue ─────────────────────────────────────────────
async function createIssue() {
  const project = document.getElementById('ci-project').value.trim();
  const summary = document.getElementById('ci-summary').value.trim();
  const issueType = document.getElementById('ci-type').value;
  const description = document.getElementById('ci-desc').value.trim();
  if (!project || !summary) { alert('Project and Summary are required'); return; }
  showResult('jira-result', 'Creating...');
  const r = await fetch('/jira/create-issue', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({project, summary, issueType, description})
  });
  showResult('jira-result', await r.json());
}

// ── Add Comment ───────────────────────────────────────────────
async function addComment() {
  const issueKey = document.getElementById('ac-key').value.trim();
  const comment  = document.getElementById('ac-comment').value.trim();
  if (!issueKey || !comment) { alert('Issue key and comment are required'); return; }
  showResult('jira-result', 'Posting...');
  const r = await fetch('/jira/add-comment', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({issueKey, comment})
  });
  showResult('jira-result', await r.json());
}

// ── Assign Issue ───────────────────────────────────────────────
async function assignIssue() {
  const issueKey = document.getElementById('as-key').value.trim();
  const assignee = document.getElementById('as-user').value.trim();
  if (!issueKey || !assignee) { alert('Issue key and assignee are required'); return; }
  showResult('jira-result', 'Assigning...');
  const r = await fetch('/jira/assign-issue', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({issueKey, assignee})
  });
  showResult('jira-result', await r.json());
}

// ── Link Issues ───────────────────────────────────────────────
async function linkIssues() {
  const inwardIssue = document.getElementById('li-inward').value.trim();
  const outwardIssue = document.getElementById('li-outward').value.trim();
  const linkType = document.getElementById('li-type').value.trim() || 'Relates';
  if (!inwardIssue || !outwardIssue) { alert('Both issue keys are required'); return; }
  showResult('jira-result', 'Linking...');
  const r = await fetch('/jira/link-issues', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({inwardIssue, outwardIssue, linkType})
  });
  showResult('jira-result', await r.json());
}

// ── Analyze Support Ticket ─────────────────────────────────────
async function analyzeSupportTicket() {
  const issueKey = document.getElementById('an-key').value.trim();
  const executeApi = document.getElementById('an-exec').checked;
  if (!issueKey) { alert('Issue key is required'); return; }
  showResult('jira-result', 'Analyzing...');
  const r = await fetch('/jira/analyze-support-ticket', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({issueKey, executeApi})
  });
  showResult('jira-result', await r.json());
}

// ── Bulk Analyze (CRSUP dry-run) ──────────────────────────────
async function analyzeBulkDryRun() {
  const extraKeywordsRaw = document.getElementById('ab-extra-keywords').value.trim();
  const extraKeywords = extraKeywordsRaw ? extraKeywordsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
  const executeApi = document.getElementById('ab-exec-api').checked;
  const enableJiraComment = document.getElementById('ab-jira-comment').checked;
  showResult('jira-result', 'Running CRSUP bulk dry-run analysis...');
  const r = await fetch('/jira/analyze-bulk-dry-run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({project: 'CRSUP', extraKeywords, executeApi, enableJiraComment})
  });
  showResult('jira-result', await r.json());
}

initPromptLibrary();
</script>
</body>
</html>
"""

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML.replace("__JIRA_HOST__", JIRA_URL))


@app.route("/jira/config", methods=["GET"])
def jira_config():
    """Return non-sensitive config values needed by the React frontend."""
    return jsonify({"jiraUrl": JIRA_URL})


# ─── Orchestrator log parser ─────────────────────────────────────────────────

KEY_RE = r"[A-Z][A-Z0-9]+-\d+"

# Primary action line emitted by apply_decision():
#   "  -> CRSUP-1234 reassign to gilbert (APAC) [rule] matched=['ctrip', 'vienna']"
REASSIGN_RE = re.compile(
    rf"->\s*(?P<key>{KEY_RE})\s+reassign\s+to\s+(?P<assignee>\S+)\s+"
    rf"\((?P<team>[A-Z]+)\)\s*\[(?P<source>[^\]]+)\]"
    rf"(?:\s*matched=(?P<matched>\[[^\]]*\]))?",
    re.I,
)

# Classification line emitted in main():
#   "CRSUP-1234 | Some title text -> APAC (rule)"
CLASSIFY_RE = re.compile(
    rf"^(?P<key>{KEY_RE})\s*\|\s*(?P<title>.+?)\s*->\s*(?P<team>[A-Z]+)\s*\((?P<source>[^)]+)\)\s*$"
)

# Report summary line:
#   "  - CRSUP-1234 -> APAC"
REPORT_RE = re.compile(rf"^\s*-\s*(?P<key>{KEY_RE})\s*->\s*(?P<team>[A-Z]+)\s*$")

# Confirmation line after live assignment:
#   "     OK: now assigned to gilbert"
OK_ASSIGN_RE = re.compile(r"OK:\s*now\s+assigned\s+to\s+(?P<assignee>\S+)", re.I)

# Dry-run marker line
DRY_RUN_RE = re.compile(r"\(DRY_RUN=true;\s*not\s+modifying\s+Jira\)", re.I)


def _extract_move_event(line):
    text = (line or "").rstrip("\n")
    if not text.strip():
        return None

    # 1) Strongest signal: reassign action line
    m = REASSIGN_RE.search(text)
    if m:
        matched_raw = m.group("matched") or ""
        # convert "['ctrip', 'vienna']" into "ctrip, vienna"
        matched_clean = re.sub(r"[\[\]']", "", matched_raw).strip()
        team = m.group("team").upper()
        target_label = "APAC Connect" if team == "APAC" \
                       else "IMN Team" if team == "IMN" \
                       else team
        return {
            "key": m.group("key"),
            "target": target_label,
            "assignee": m.group("assignee"),
            "action": "reassign",
            "status": "pending",   # may become 'moved' or 'dry-run' from subsequent lines
            "source": m.group("source"),
            "matched": matched_clean,
            "raw": text.strip(),
        }

    # 2) Classification line (lower priority — only show if it routes somewhere)
    m = CLASSIFY_RE.match(text)
    if m:
        team = m.group("team").upper()
        if team in ("APAC", "IMN"):
            target_label = "APAC Connect" if team == "APAC" else "IMN Team"
            return {
                "key": m.group("key"),
                "target": target_label,
                "assignee": "",
                "action": "classify",
                "status": "classified",
                "source": m.group("source"),
                "matched": "",
                "raw": text.strip(),
                "title": m.group("title").strip(),
            }
        if team == "KEEP":
            # Marker so generate() can route this to the 'kept' SSE event
            return {
                "__kept__": True,
                "key": m.group("key"),
                "title": m.group("title").strip(),
                "source": m.group("source"),
                "raw": text.strip(),
            }

    # 3) Report summary entries (de-duped by upsert on client)
    m = REPORT_RE.match(text)
    if m:
        team = m.group("team").upper()
        target_label = "APAC Connect" if team == "APAC" else "IMN Team" if team == "IMN" else team
        return {
            "key": m.group("key"),
            "target": target_label,
            "assignee": "",
            "action": "report",
            "status": "summary",
            "source": "report",
            "matched": "",
            "raw": text.strip(),
        }

    return None


def _post_process_status(line, last_move):
    """Update status of the last seen move based on follow-up lines (DRY_RUN / OK)."""
    if not last_move:
        return None
    if DRY_RUN_RE.search(line):
        last_move["status"] = "dry-run"
        return last_move
    m = OK_ASSIGN_RE.search(line)
    if m:
        last_move["status"] = "moved"
        last_move["assignee"] = m.group("assignee")
        return last_move
    if "ERROR:" in line and last_move["key"] in line:
        last_move["status"] = "error"
        return last_move
    return None


@app.route("/run-orchestrator", methods=["POST"])
def run_orchestrator():
    data     = request.json or {}
    dry_run  = data.get("dry_run", "true")
    test_key = data.get("test_key", "").strip()

    env = os.environ.copy()
    env["DRY_RUN"] = dry_run
    if test_key:
        env["TEST_ISSUE_KEY"] = test_key
    else:
        env.pop("TEST_ISSUE_KEY", None)

    script = _resolve_orchestrator_script()

    def sse(event, payload):
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    def generate():
        proc = subprocess.Popen(
            [sys.executable, "-u", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, text=True, bufsize=1,
        )
        last_move = None
        try:
            for line in iter(proc.stdout.readline, ""):
                yield sse("log", {"line": line})

                move = _extract_move_event(line)
                if move:
                    if move.get("__kept__"):
                        move.pop("__kept__", None)
                        yield sse("kept", move)
                        continue
                    # If a reassign event just came, remember it for status updates
                    if move["action"] == "reassign":
                        last_move = move
                    yield sse("move", move)
                    continue

                # Not a new move line — check if it updates the previous move's status
                updated = _post_process_status(line, last_move)
                if updated:
                    yield sse("move", updated)

            proc.wait()
            yield sse("done", {"exit_code": proc.returncode})
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Jira REST helpers ────────────────────────────────────────────────────────

def _jira_get(path):
    try:
        r = requests.get(f"{JIRA_URL}{path}", headers=JIRA_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json(), 200
    except requests.HTTPError as e:
        return {"error": str(e), "detail": e.response.text}, e.response.status_code
    except Exception as e:
        return {"error": str(e)}, 500


def _jira_post(path, payload):
    try:
        r = requests.post(f"{JIRA_URL}{path}", headers=JIRA_HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        return r.json(), r.status_code
    except requests.HTTPError as e:
        return {"error": str(e), "detail": e.response.text}, e.response.status_code
    except Exception as e:
        return {"error": str(e)}, 500


def _jira_put(path, payload):
    try:
        r = requests.put(f"{JIRA_URL}{path}", headers=JIRA_HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        return (r.json() if r.text else {}), r.status_code
    except requests.HTTPError as e:
        return {"error": str(e), "detail": e.response.text}, e.response.status_code
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/jira/get-issue", methods=["POST"])
def jira_get_issue():
    key = (request.json or {}).get("issueKey", "")
    data, code = _jira_get(f"/rest/api/2/issue/{key}")
    if "error" in data:
        return jsonify(data), code
    f = data.get("fields", {})
    result = {
        "key":         data.get("key"),
        "summary":     f.get("summary"),
        "description": f.get("description"),
        "status":      (f.get("status") or {}).get("name"),
        "priority":    (f.get("priority") or {}).get("name"),
        "assignee":    (f.get("assignee") or {}).get("displayName"),
        "reporter":    (f.get("reporter") or {}).get("displayName"),
        "created":     f.get("created"),
        "updated":     f.get("updated"),
    }
    return jsonify(result)


@app.route("/jira/search", methods=["POST"])
def jira_search():
    body      = request.json or {}
    jql       = body.get("jql", "")
    max_res   = int(body.get("maxResults", 10))
    payload   = {"jql": jql, "maxResults": max_res, "fields": ["summary","status","priority","assignee"]}
    data, code = _jira_post("/rest/api/2/search", payload)
    if "error" in data:
        return jsonify(data), code
    issues = []
    for i in data.get("issues", []):
        f = i.get("fields", {})
        issues.append({
            "key":      i.get("key"),
            "summary":  f.get("summary"),
            "status":   (f.get("status") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "assignee": (f.get("assignee") or {}).get("displayName"),
        })
    return jsonify(issues)


@app.route("/jira/create-issue", methods=["POST"])
def jira_create_issue():
    body        = request.json or {}
    project     = body.get("project", "")
    summary     = body.get("summary", "")
    issue_type  = body.get("issueType", "Task")
    description = body.get("description", "")
    payload = {
        "fields": {
            "project":   {"key": project},
            "summary":   summary,
            "issuetype": {"name": issue_type},
        }
    }
    if description:
        payload["fields"]["description"] = description
    data, code = _jira_post("/rest/api/2/issue", payload)
    if "error" in data:
        return jsonify(data), code
    key  = data.get("key")
    link = f"{JIRA_URL}/browse/{key}"
    return jsonify({"created": key, "url": link})


@app.route("/jira/add-comment", methods=["POST"])
def jira_add_comment():
    body      = request.json or {}
    issue_key = body.get("issueKey", "")
    comment   = body.get("comment", "")
    data, code = _jira_post(f"/rest/api/2/issue/{issue_key}/comment", {"body": comment})
    if "error" in data:
        return jsonify(data), code
    return jsonify({"status": "Comment added", "id": data.get("id"), "issueKey": issue_key})


@app.route("/jira/assign-issue", methods=["POST"])
def jira_assign_issue():
    body = request.json or {}
    issue_key = body.get("issueKey", "")
    assignee = body.get("assignee", "")
    data, code = _jira_put(f"/rest/api/2/issue/{issue_key}/assignee", {"name": assignee})
    if "error" in data:
        return jsonify(data), code
    return jsonify({"status": "Assigned", "issueKey": issue_key, "assignee": assignee})


@app.route("/jira/link-issues", methods=["POST"])
def jira_link_issues():
    body = request.json or {}
    inward = body.get("inwardIssue", "")
    outward = body.get("outwardIssue", "")
    link_type = body.get("linkType", "Relates")
    payload = {
        "type": {"name": link_type},
        "inwardIssue": {"key": inward},
        "outwardIssue": {"key": outward},
    }
    data, code = _jira_post("/rest/api/2/issueLink", payload)
    if "error" in data:
        return jsonify(data), code
    return jsonify({"linked": True, "inwardIssue": inward, "outwardIssue": outward, "linkType": link_type})


@app.route("/jira/search-concept", methods=["POST"])
def jira_search_concept():
    body = request.json or {}
    phrases = body.get("phrases") or []
    field = (body.get("field") or "text").lower().strip()
    max_res = int(body.get("maxResults", 20))
    if not isinstance(phrases, list) or not phrases:
        return jsonify({"error": "phrases must be a non-empty list"}), 400
    if field not in {"text", "summary", "description", "comment"}:
        return jsonify({"error": f"unsupported field '{field}'"}), 400

    clean: List[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        p = str(phrase or "").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            clean.append(p)
    if not clean:
        return jsonify({"error": "no usable phrases"}), 400

    or_block = " OR ".join(f'{field} ~ "\\"{p}\\""' for p in clean)
    payload = {
        "jql": f"({or_block})",
        "maxResults": max_res,
        "fields": ["summary", "status", "priority", "assignee"],
    }
    data, code = _jira_post("/rest/api/2/search", payload)
    if "error" in data:
        return jsonify(data), code

    issues = []
    for i in data.get("issues", []):
        f = i.get("fields", {})
        issues.append({
            "key": i.get("key"),
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "assignee": (f.get("assignee") or {}).get("displayName"),
        })
    return jsonify({"count": len(issues), "issues": issues, "phrases_used": clean, "effective_jql": payload["jql"]})


@app.route("/jira/analyze-support-ticket", methods=["POST"])
def jira_analyze_support_ticket():
    body = request.json or {}
    issue_key = str(body.get("issueKey") or "").strip()
    since_hours = SINGLE_ANALYZE_SINCE_HOURS
    execute_api = bool(body.get("executeApi", False))
    enable_jira_comment = bool(body.get("enableJiraComment", False))
    if not issue_key:
        return jsonify({"error": "issueKey is required"}), 400
    try:
        result = run_support_ticket_analysis(
            issue_key=issue_key,
            since_hours=since_hours,
            execute_api=execute_api,
            output_path=None,
            comment_jira=enable_jira_comment,
            preview_jira_comment=True,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/jira/analyze-bulk-dry-run", methods=["POST"])
def jira_analyze_bulk_dry_run():
    body = request.json or {}
    project = str(body.get("project") or "CRSUP").strip().upper()
    since_hours = BULK_DRY_RUN_SINCE_HOURS
    sample_size = BULK_DRY_RUN_SAMPLE_SIZE
    extra_keywords_raw = body.get("extraKeywords") or []
    execute_api = bool(body.get("executeApi", False))
    enable_jira_comment = bool(body.get("enableJiraComment", False))

    # Safety guard: testing-only scope as requested.
    if project != "CRSUP":
        return jsonify({"error": "Only CRSUP is allowed for bulk dry run."}), 400

    keywords = _load_availability_keywords_for_ui()
    extra_keywords: list[str] = []
    if isinstance(extra_keywords_raw, list):
        for item in extra_keywords_raw:
            keyword = str(item or "").strip()
            if keyword and keyword.lower() not in [k.lower() for k in extra_keywords]:
                extra_keywords.append(keyword)
    combined_keywords: list[str] = []
    for keyword in keywords + extra_keywords:
        if keyword.lower() not in [k.lower() for k in combined_keywords]:
            combined_keywords.append(keyword)

    if not combined_keywords:
        return jsonify({"error": "No keywords available for bulk analysis."}), 400

    phrase_clause = " OR ".join([f'text ~ "\\"{kw}\\""' for kw in combined_keywords])
    jql = (
        f'project = "CRSUP" AND statusCategory != Done AND ({phrase_clause}) '
        "ORDER BY updated DESC"
    )

    search_payload = {
        "jql": jql,
        "maxResults": sample_size,
        "fields": ["summary", "status"],
    }
    data, code = _jira_post("/rest/api/2/search", search_payload)
    if "error" in data:
        return jsonify(data), code

    issues = data.get("issues", []) or []
    analyzed = []
    for item in issues:
        key = item.get("key")
        summary = (item.get("fields") or {}).get("summary")
        try:
            result = run_support_ticket_analysis(
                issue_key=key,
                since_hours=since_hours,
                execute_api=execute_api,
                output_path=None,
                comment_jira=enable_jira_comment,
                preview_jira_comment=True,
            )
            analyzed.append({
                "issueKey": key,
                "summary": summary,
                "analyzed": True,
                "dryRun": True,
                "executeApi": execute_api,
                "jiraCommentPreviewEnabled": True,
                "jiraCommentPostingEnabled": enable_jira_comment,
                "wouldPostComment": bool(execute_api and enable_jira_comment),
                "jiraComment": result.get("jiraComment"),
                "payloadPreview": result.get("singleAvailPayload"),
                "singleAvailExecution": result.get("singleAvailExecution"),
                "singleAvailResponseStatus": (result.get("singleAvailResponse") or {}).get("statusCode"),
                "wouldCommentPreview": ((result.get("jiraComment") or {}).get("comments") or [None])[0],
                "availabilityHits": (result.get("indicators") or {}).get("ticketAvailabilityKeywordHits"),
                "newRelicSampleCount": (result.get("newRelic") or {}).get("sampleCount"),
            })
        except Exception as exc:
            analyzed.append({
                "issueKey": key,
                "summary": summary,
                "analyzed": False,
                "dryRun": True,
                "error": str(exc),
            })

    return jsonify({
        "mode": "bulk-keyword-analysis-dry-run",
        "project": "CRSUP",
        "dryRun": True,
        "sinceHoursConfigured": since_hours,
        "sampleSizeConfigured": sample_size,
        "sampleSizeMeaning": "Number of latest matching CRSUP tickets analyzed in this run.",
        "executeApi": execute_api,
        "jiraCommentPreviewEnabled": True,
        "jiraCommentPostingEnabled": enable_jira_comment,
        "keywordsFromConfig": keywords,
        "keywordsFromInput": extra_keywords,
        "keywordsUsed": combined_keywords,
        "effectiveJql": jql,
        "ticketsMatched": len(issues),
        "results": analyzed,
        "note": "Preview is always generated when available. Jira posting only happens if 'Enable Jira Comment Posting (CRSUP only)' is checked.",
    })


# ─── AI Chat (JiraAzureCopilot) ───────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat():
    if not _CHAT_OK:
        return jsonify({"error": f"chat_agent unavailable: {_CHAT_ERR}"}), 500
    body    = request.json or {}
    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        return jsonify({"error": "empty message"}), 400
    try:
        result = _agent_run_chat(history, message)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🎫  JiraAzureCopilot UI  →  http://localhost:5000")
    app.run(debug=True, port=5000, threaded=True)

