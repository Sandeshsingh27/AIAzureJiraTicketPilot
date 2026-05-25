import { useEffect, useRef, useState } from "react";

// ── Fetch Jira URL from backend config ───────────────────────
function useJiraUrl() {
  const [jiraUrl, setJiraUrl] = useState("");
  useEffect(() => {
    fetch("/jira/config")
      .then((r) => r.json())
      .then((d) => { if (d?.jiraUrl) setJiraUrl(d.jiraUrl.replace(/\/$/, "")); })
      .catch(() => {});
  }, []);
  return jiraUrl;
}

// ── Prompt library ────────────────────────────────────────────
const PROMPT_LIBRARY = {
  "Search & Discovery": [
    "Find all open CRSUP tickets about Hotel Unavailable",
    "Show details of CRSUP-4421",
    "Find similar tickets to CRSUP-4421, create a parent ticket and link them all",
  ],
  "Single Ticket Analysis": [
    "Analyze support ticket CRSUP-4421 for hotel unavailable. Check New Relic logs from last 24 hours and build the singleavail payload.",
    "Run end-to-end analysis for CRSUP-4421, include New Relic check, build payload, and execute the singleavail API call.",
  ],
  "Bulk Dry Run Analysis (CRSUP)": [
    "Run bulk dry-run analysis for CRSUP with safe defaults and executeApi false, enableJiraComment false.",
    "/bulk-dry-run executeApi=true enableJiraComment=false extra keywords: hotel closed, property suspended",
  ],
};

const QUICK_PILLS = [
  "Find open CRSUP hotel unavailable tickets",
  "Analyze CRSUP-4421 for hotel unavailable",
  "Bulk dry-run for CRSUP with safe defaults",
  "Show details of CRSUP-4421",
];

// ── API helper ────────────────────────────────────────────────
async function postJson(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.error || `HTTP ${r.status}`);
  return data;
}

// ── Sidebar icons ─────────────────────────────────────────────
const NAV = [
  { id: "chat",        icon: "💬", label: "AI Chat" },
  { id: "mcp",         icon: "🔧", label: "MCP Tools" },
  { id: "orchestrator",icon: "🤖", label: "JiraAzureCopilot" },
  { id: "howto",       icon: "📘", label: "How To Use" },
];

function Sidebar({ active, onChange }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">T</div>
      <div className="sidebar-divider" />
      {NAV.map((n) => (
        <button
          key={n.id}
          className={`nav-item ${active === n.id ? "active" : ""}`}
          onClick={() => onChange(n.id)}
          title=""
        >
          {n.icon}
          <span className="tooltip">{n.label}</span>
        </button>
      ))}
    </aside>
  );
}

// ── Prompt popup ──────────────────────────────────────────────
function PromptPopup({ onSelect, onClose }) {
  return (
    <div className="prompt-popup">
      <div className="prompt-popup-head">
        💡 Example prompts
        <button onClick={onClose}>✕</button>
      </div>
      {Object.entries(PROMPT_LIBRARY).map(([cat, items]) => (
        <div key={cat}>
          <div className="prompt-category">{cat}</div>
          {items.map((p) => (
            <div
              key={p}
              className="prompt-item"
              onClick={() => { onSelect(p); onClose(); }}
            >
              {p}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ── Chat view ─────────────────────────────────────────────────
function ChatView() {
  const [messages, setMessages] = useState([]);
  const [history, setHistory] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [trace, setTrace] = useState([]);
  const [showTrace, setShowTrace] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);
  const promptWrapRef = useRef(null);

  // Close prompt popup when clicking outside
  useEffect(() => {
    if (!showPrompts) return;
    const handler = (e) => {
      if (promptWrapRef.current && !promptWrapRef.current.contains(e.target)) {
        setShowPrompts(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showPrompts]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    setSending(true);
    setMessages((p) => [...p, { role: "user", text: msg }]);
    setInput("");
    setShowPrompts(false);
    try {
      const data = await postJson("/chat", { message: msg, history });
      setMessages((p) => [...p, { role: "bot", text: data.reply || "(no response)" }]);
      setHistory(data.history || history);
      setTrace(data.tool_trace || []);
      if ((data.tool_trace || []).length) setShowTrace(true);
    } catch (err) {
      setMessages((p) => [...p, { role: "bot", text: `❌ ${err.message}` }]);
    } finally {
      setSending(false);
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <div className="chat-view">
      {/* Header */}
      <div className="chat-header">
        <span style={{ fontSize: "1.1rem" }}>💬</span>
        <h2>JiraAzureCopilot</h2>
        <span className="header-badge">Jira + New Relic + Single Avail</span>
        <div style={{ flex: 1 }} />
        <button
          className="btn secondary"
          style={{ fontSize: "0.78rem", padding: "5px 10px" }}
          onClick={() => { setMessages([]); setHistory([]); setTrace([]); setShowTrace(false); }}
        >
          🗑 New Chat
        </button>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-welcome">
            <div className="chat-welcome-logo">💬</div>
            <h3>How can I help you today?</h3>
            <p>Search Jira tickets, run hotel availability analysis, bulk dry-run CRSUP checks, and more.</p>
            <div className="quick-pills">
              {QUICK_PILLS.map((p) => (
                <button key={p} className="quick-pill" onClick={() => send(p)}>{p}</button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((m, i) => (
              <div key={i} className={`msg-row ${m.role}`}>
                <div className={`bubble ${m.role}`}>{m.text}</div>
              </div>
            ))}
            {sending && (
              <div className="msg-row bot">
                <div className="bubble bot thinking">JiraAzureCopilot is thinking…</div>
              </div>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Tool trace */}
      {trace.length > 0 && (
        <>
          <div className="trace-toggle" onClick={() => setShowTrace((v) => !v)}>
            {showTrace ? "▲ Hide" : "▼ Show"} tools used ({trace.length})
          </div>
          {showTrace && (
            <pre className="trace-box">
              {trace.map((t, i) =>
                `→ ${t.tool}(${JSON.stringify(t.args)})\n   ${JSON.stringify(t.result).slice(0, 400)}\n`
              ).join("\n")}
            </pre>
          )}
        </>
      )}

      {/* Input bar */}
      <div className="chat-input-bar">
        <div className="chat-input-wrap">
          {/* Prompt hint icon */}
          <div className="prompt-hint-wrap" ref={promptWrapRef}>
            <button
              className={`prompt-hint-btn ${showPrompts ? "open" : ""}`}
              onClick={() => setShowPrompts((v) => !v)}
              title="Example prompts"
            >
              💡
            </button>
            {showPrompts && (
              <PromptPopup
                onSelect={(p) => { setInput(p); textareaRef.current?.focus(); }}
                onClose={() => setShowPrompts(false)}
              />
            )}
          </div>

          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask anything about your Jira tickets…"
          />
          <button className="send-btn" onClick={() => send()} disabled={sending || !input.trim()}>
            ➤
          </button>
        </div>
      </div>
    </div>
  );
}

// ── MCP Tools view ────────────────────────────────────────────
function MCPToolsView() {
  const [tool, setTool] = useState("get");
  const [result, setResult] = useState("Result will appear here after running a tool.");

  const [issueKey, setIssueKey] = useState("");
  const [jql, setJql] = useState("project=CRSUP AND status=Open");
  const [conceptPhrases, setConceptPhrases] = useState("hotel unavailable, hotel not bookable");
  const [conceptField, setConceptField] = useState("text");
  const [maxResults, setMaxResults] = useState(10);
  const [project, setProject] = useState("CRSUP");
  const [issueType, setIssueType] = useState("Task");
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [comment, setComment] = useState("");
  const [assignee, setAssignee] = useState("");
  const [inward, setInward] = useState("");
  const [outward, setOutward] = useState("");
  const [linkType, setLinkType] = useState("Relates");
  const [anExec, setAnExec] = useState(false);
  const [anComment, setAnComment] = useState(false);
  const [abKeywords, setAbKeywords] = useState("");
  const [abExec, setAbExec] = useState(false);
  const [abComment, setAbComment] = useState(false);
  const [running, setRunning] = useState(false);

  const runTool = async () => {
    setRunning(true);
    setResult("Running…");
    try {
      let data;
      if (tool === "get")      data = await postJson("/jira/get-issue", { issueKey });
      if (tool === "search")   data = await postJson("/jira/search", { jql, maxResults: +maxResults });
      if (tool === "concept")  data = await postJson("/jira/search-concept", {
        phrases: conceptPhrases.split(",").map((s) => s.trim()).filter(Boolean),
        field: conceptField,
        maxResults: +maxResults,
      });
      if (tool === "create")   data = await postJson("/jira/create-issue", { project, summary, issueType, description });
      if (tool === "comment")  data = await postJson("/jira/add-comment", { issueKey, comment });
      if (tool === "assign")   data = await postJson("/jira/assign-issue", { issueKey, assignee });
      if (tool === "link")     data = await postJson("/jira/link-issues", { inwardIssue: inward, outwardIssue: outward, linkType });
      if (tool === "analyze") data = await postJson("/jira/analyze-support-ticket", { issueKey, executeApi: anExec, enableJiraComment: anComment });
      if (tool === "analyze-bulk") {
        data = await postJson("/jira/analyze-bulk-dry-run", {
          project: "CRSUP",
          extraKeywords: abKeywords.split(",").map((s) => s.trim()).filter(Boolean),
          executeApi: abExec,
          enableJiraComment: abComment,
        });
      }
      setResult(JSON.stringify(data, null, 2));
    } catch (err) {
      setResult(`Error: ${err.message}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="panel-view">
      <div className="panel-header">
        <h2>🔧 MCP Tools</h2>
        <p>Direct Jira actions and ticket analysis — no chat required.</p>
      </div>
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="form-grid">
          <div className="field">
            <label>Tool</label>
            <select value={tool} onChange={(e) => setTool(e.target.value)}>
              <option value="get">Get Issue</option>
              <option value="search">Search Issues using JQL</option>
              <option value="concept">Search Issues using Keywords</option>
              <option value="create">Create Issue</option>
              <option value="comment">Add Comment</option>
              <option value="assign">Assign Issue</option>
              <option value="link">Link Issues</option>
              <option value="analyze">Analyze Support Ticket</option>
              <option value="analyze-bulk">Bulk Analyze (CRSUP Dry Run)</option>
            </select>
          </div>

          {["get", "comment", "assign", "analyze"].includes(tool) && (
            <div className="field">
              <label>Issue Key</label>
              <input value={issueKey} onChange={(e) => setIssueKey(e.target.value)} placeholder="CRSUP-4421" />
            </div>
          )}

          {tool === "search" && (
            <>
              <div className="field grow">
                <label>JQL</label>
                <input
                  value={jql}
                  onChange={(e) => setJql(e.target.value)}
                  placeholder="project=CRSUP AND status=Open"
                />
              </div>
              <div className="field" style={{ maxWidth: 100 }}>
                <label>Max</label>
                <input type="number" value={maxResults} onChange={(e) => setMaxResults(e.target.value)} />
              </div>
            </>
          )}

          {tool === "concept" && (
            <>
              <div className="field grow">
                <label>Keywords/Phrases (comma-separated)</label>
                <input
                  value={conceptPhrases}
                  onChange={(e) => setConceptPhrases(e.target.value)}
                  placeholder="hotel unavailable, hotel not bookable"
                />
              </div>
              <div className="field" style={{ maxWidth: 170 }}>
                <label>Field</label>
                <select value={conceptField} onChange={(e) => setConceptField(e.target.value)}>
                  <option value="text">text</option>
                  <option value="summary">summary</option>
                  <option value="description">description</option>
                  <option value="comment">comment</option>
                </select>
              </div>
              <div className="field" style={{ maxWidth: 100 }}>
                <label>Max</label>
                <input type="number" value={maxResults} onChange={(e) => setMaxResults(e.target.value)} />
              </div>
            </>
          )}

          {tool === "create" && (
            <>
              <div className="field"><label>Project</label><input value={project} onChange={(e) => setProject(e.target.value)} /></div>
              <div className="field"><label>Issue Type</label><input value={issueType} onChange={(e) => setIssueType(e.target.value)} /></div>
              <div className="field grow"><label>Summary</label><input value={summary} onChange={(e) => setSummary(e.target.value)} /></div>
              <div className="field grow"><label>Description</label><input value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            </>
          )}

          {tool === "comment" && (
            <div className="field grow"><label>Comment</label><input value={comment} onChange={(e) => setComment(e.target.value)} /></div>
          )}

          {tool === "assign" && (
            <div className="field"><label>Assignee</label><input value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="nsh50" /></div>
          )}

          {tool === "link" && (
            <>
              <div className="field"><label>Inward Issue</label><input value={inward} onChange={(e) => setInward(e.target.value)} /></div>
              <div className="field"><label>Outward Issue</label><input value={outward} onChange={(e) => setOutward(e.target.value)} /></div>
              <div className="field"><label>Link Type</label><input value={linkType} onChange={(e) => setLinkType(e.target.value)} /></div>
            </>
          )}

          {tool === "analyze" && (
            <>
              <div className="field" style={{ justifyContent: "flex-end" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={anExec} onChange={(e) => setAnExec(e.target.checked)} />
                  Execute API
                </label>
              </div>
              <div className="field" style={{ justifyContent: "flex-end" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={anComment} onChange={(e) => setAnComment(e.target.checked)} />
                  Post Comment
                </label>
              </div>
            </>
          )}

          {tool === "analyze-bulk" && (
            <>
              <div className="field" style={{ maxWidth: 130 }}>
                <label>Project</label>
                <input value="CRSUP" disabled />
              </div>
              <div className="field grow">
                <label>Extra Keywords (optional, comma-separated)</label>
                <input
                  value={abKeywords}
                  onChange={(e) => setAbKeywords(e.target.value)}
                  placeholder="hotel closed, property suspended"
                />
              </div>
              <div className="field" style={{ justifyContent: "flex-end" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={abExec} onChange={(e) => setAbExec(e.target.checked)} />
                  Execute API
                </label>
              </div>
              <div className="field" style={{ justifyContent: "flex-end" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={abComment} onChange={(e) => setAbComment(e.target.checked)} />
                  Enable Jira Comment Posting
                </label>
              </div>
            </>
          )}
        </div>

        <div className="toolbar">
          <button className="btn" onClick={runTool} disabled={running}>
            {running ? "Running…" : "▶ Run Tool"}
          </button>
        </div>

        <pre className="result-box">{result}</pre>
      </div>
    </div>
  );
}

// ── Ticket key link helper ────────────────────────────────────
function TicketLink({ ticketKey, jiraUrl }) {
  if (!ticketKey) return <span>-</span>;
  if (jiraUrl) {
    return (
      <a
        href={`${jiraUrl}/browse/${ticketKey}`}
        target="_blank"
        rel="noopener noreferrer"
        className="ticket-link"
      >
        {ticketKey}
      </a>
    );
  }
  return <strong>{ticketKey}</strong>;
}

// ── Orchestrator view ─────────────────────────────────────────
function OrchestratorView({ jiraUrl = "" }) {
  const [dryRun, setDryRun] = useState(true);
  const [testKey, setTestKey] = useState("");
  const [status, setStatus] = useState("Idle");
  const [output, setOutput] = useState("Ready. Click Run to start.");
  const [moves, setMoves] = useState([]);
  const [kept, setKept] = useState([]);
  const ctrlRef = useRef(null);

  const STATUS_PRIORITY = { summary: 1, classified: 2, pending: 3, "dry-run": 4, moved: 5, error: 6 };

  const moveRows = Object.values(
    moves.reduce((acc, item) => {
      const key = item?.key;
      if (!key) return acc;
      const prev = acc[key] || {};
      const newStatus = item.status || "";
      const curStatus = prev.status || "";
      const finalStatus =
        (STATUS_PRIORITY[newStatus] || 0) >= (STATUS_PRIORITY[curStatus] || 0)
          ? newStatus
          : curStatus;
      acc[key] = {
        key,
        title: item.title || prev.title || "",
        target: item.target || prev.target || "",
        assignee: item.assignee || prev.assignee || "",
        matched: item.matched || prev.matched || "",
        source: item.source || prev.source || "",
        status: finalStatus,
      };
      return acc;
    }, {})
  );

  const keptRows = Object.values(
    kept.reduce((acc, item) => {
      const key = item?.key;
      if (!key) return acc;
      acc[key] = { key, title: item.title || "" };
      return acc;
    }, {})
  );

  const statusLabel = (status) => {
    const s = String(status || "").toLowerCase();
    if (s === "moved") return "Moved";
    if (s === "dry-run") return "Dry Run";
    if (s === "pending") return "Pending";
    if (s === "classified") return "Classified";
    if (s === "summary") return "Summary";
    if (s === "error") return "Error";
    return status || "-";
  };

  const run = async () => {
    setOutput(""); setMoves([]); setKept([]); setStatus("Running");
    ctrlRef.current = new AbortController();
    try {
      const resp = await fetch("/run-orchestrator", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dry_run: String(dryRun), test_key: testKey.trim() }),
        signal: ctrlRef.current.signal,
      });
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
          let ev = "message", data = "";
          frame.split("\n").forEach((l) => {
            if (l.startsWith("event:")) ev = l.slice(6).trim();
            else if (l.startsWith("data:")) data += l.slice(5).trim();
          });
          if (!data) continue;
          let p; try { p = JSON.parse(data); } catch { continue; }
          if (ev === "log" && p.line) setOutput((x) => x + p.line);
          if (ev === "move") setMoves((x) => [...x, p]);
          if (ev === "kept") setKept((x) => [...x, p]);
          if (ev === "done") { setStatus(p.exit_code === 0 ? "Done" : "Error"); }
        }
      }
      setStatus((s) => s === "Running" ? "Done" : s);
    } catch (err) {
      setStatus(err.name === "AbortError" ? "Stopped" : "Error");
    }
  };

  return (
    <div className="panel-view">
      <div className="panel-header">
        <h2>🤖 Ticket Orchestrator</h2>
        <p>Run the routing engine to classify and reassign Jira tickets.</p>
      </div>
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="form-grid">
          <div className="field">
            <label>Mode</label>
            <select value={String(dryRun)} onChange={(e) => setDryRun(e.target.value === "true")}>
              <option value="true">🔍 Dry Run (preview)</option>
              <option value="false">🚀 Live (modify Jira)</option>
            </select>
          </div>
          <div className="field grow">
            <label>Test Issue Key (optional)</label>
            <input value={testKey} onChange={(e) => setTestKey(e.target.value)} placeholder="CRSUP-4421" />
          </div>
        </div>
        <div className="toolbar">
          <button className="btn" onClick={run}>▶ Run</button>
          <button className="btn danger" onClick={() => ctrlRef.current?.abort()}>■ Stop</button>
          <button className="btn secondary" onClick={() => { setOutput(""); setMoves([]); setKept([]); setStatus("Idle"); }}>🗑 Clear</button>
          <span className={`badge ${status.toLowerCase()}`}>{status}</span>
        </div>
        <pre className="result-box output">{output}</pre>
      </div>

      <div className="stack">
        <div className="card nested">
          <div className="card-head small">📦 Moved / Routed ({moveRows.length})</div>
          {moveRows.length === 0 ? (
            <div className="empty-box">No moved/routed tickets yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Title</th>
                    <th>Routed To</th>
                    <th>Assignee</th>
                    <th>Matched</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {moveRows.map((row) => (
                    <tr key={row.key}>
                      <td><TicketLink ticketKey={row.key} jiraUrl={jiraUrl} /></td>
                      <td>{row.title || "-"}</td>
                      <td>{row.target || "-"}</td>
                      <td>{row.assignee || "-"}</td>
                      <td>{row.matched || "-"}</td>
                      <td>
                        <span className={`status-pill ${String(row.status || "").toLowerCase()}`}>
                          {statusLabel(row.status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card nested">
          <div className="card-head small">📥 Kept Tickets ({keptRows.length})</div>
          {keptRows.length === 0 ? (
            <div className="empty-box">No kept tickets yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Title</th>
                    <th>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {keptRows.map((row) => (
                    <tr key={row.key}>
                      <td><TicketLink ticketKey={row.key} jiraUrl={jiraUrl} /></td>
                      <td>{row.title || "-"}</td>
                      <td><span className="status-pill keep">KEEP</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── How To view ───────────────────────────────────────────────
function HowToView() {
  const sections = [
    {
      title: "🚀 Quick Start",
      items: [
        "Start Flask backend: python .\\ui_app.py (port 5000)",
        "Start React UI: npm run dev in frontend/ (port 5173)",
        "Use the sidebar icons to navigate between views",
      ],
      type: "ol",
    },
    {
      title: "💬 AI Chat",
      items: [
        "Default start page — full ChatGPT-style interface",
        "Click 💡 near the input to browse example prompts",
        "Click any quick-start pill on the welcome screen to run instantly",
        "Use New Chat to clear history",
      ],
      type: "ul",
    },
    {
      title: "🔧 MCP Tools",
      items: [
        "Get Issue — fetch ticket by key",
        "Search Issues using JQL — raw Jira JQL query",
        "Search Issues using Keywords — phrase-based keyword search",
        "Create / Comment / Assign / Link",
        "Analyze Support Ticket — single-ticket New Relic + payload analysis",
        "Bulk Analyze (CRSUP Dry Run) — backend defaults for since/sample size",
      ],
      type: "ul",
    },
    {
      title: "📚 Bulk Dry-Run (Chat)",
      items: [
        "Use the AI Chat to run bulk CRSUP analysis",
        "Say: Run bulk dry-run analysis for CRSUP with safe defaults, executeApi false, enableJiraComment false.",
        "Or slash command: /bulk-dry-run executeApi=true enableJiraComment=false",
        "Preview is always included; real Jira commenting is opt-in",
      ],
      type: "ol",
    },
    {
      title: "🛡 Safety Rules",
      items: [
        "Bulk analysis is scoped to CRSUP only",
        "Both toggles (Execute API, Jira Comment) default to OFF",
        "If ticket has no core filter fields, analyzer asks for them instead of running broad NRQL",
        "Duplicate Jira comment detection prevents duplicate posting",
      ],
      type: "ul",
    },
    {
      title: "🧩 Toggle Meanings",
      items: [
        "Execute API — calls EC2 singleavail endpoint",
        "Enable Jira Comment Posting — posts real comments on CRSUP tickets",
        "Single-ticket since-hours comes from backend env defaults",
        "Jira comment preview is always generated for dry-run testing",
        "Bulk since/sample size values come from backend env defaults",
      ],
      type: "ul",
    },
  ];

  return (
    <div className="panel-view">
      <div className="panel-header">
        <h2>📘 How To Use</h2>
        <p>Features, step-by-step flows, and safety notes.</p>
      </div>
      <div className="howto-grid">
        {sections.map((s) => (
          <div key={s.title} className="howto-card">
            <h4>{s.title}</h4>
            {s.type === "ol" ? (
              <ol>{s.items.map((i) => <li key={i}>{i}</li>)}</ol>
            ) : (
              <ul>{s.items.map((i) => <li key={i}>{i}</li>)}</ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── App root ──────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState("chat");
  const jiraUrl = useJiraUrl();

  const view = {
    chat: <ChatView />,
    mcp: <MCPToolsView />,
    orchestrator: <OrchestratorView jiraUrl={jiraUrl} />,
    howto: <HowToView />,
  }[tab] ?? <ChatView />;

  return (
    <div className="app-shell">
      <Sidebar active={tab} onChange={setTab} />
      <main className="main">{view}</main>
    </div>
  );
}

