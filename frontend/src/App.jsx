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
  "Search & Investigate": [
    "Find all open tickets about hotel unavailability",
    "Show me tickets with payment failures",
    "Search for price mismatch issues",
    "What are similar issues to CRSUP-4421?",
  ],
  "Single Ticket Analysis": [
    "Analyze CRSUP-4421 for hotel unavailability",
    "Run end-to-end analysis on CRSUP-4421 and check New Relic logs",
    "Analyze CRSUP-4421 for hotel unbookable issues with singleavail payload",
  ],
  "Bulk Analysis": [
    "Run bulk analysis on CRSUP to find common hotel availability issues",
    "Analyze multiple CRSUP tickets for hotel unavailability with keyword search",
    "Do a bulk dry-run to check which tickets might have availability problems",
  ],
  "Consolidation & Linking": [
    "Find all hotel unavailable tickets and create a parent ticket to link them",
    "Create a master issue for payment failure tickets and link them together",
  ],
};

const QUICK_PILLS = [
  "Search for hotel unavailability tickets",
  "Analyze CRSUP-4421 for hotel unavailable",
  "Bulk analysis of CRSUP for availability issues",
  "Show CRSUP-4421 details",
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
  const [runningToolLabel, setRunningToolLabel] = useState("");
  const [loaderTick, setLoaderTick] = useState(0);
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

  useEffect(() => {
    if (!sending) {
      setLoaderTick(0);
      return;
    }
    const id = setInterval(() => setLoaderTick((t) => t + 1), 450);
    return () => clearInterval(id);
  }, [sending]);

  const inferRunningToolLabel = (text) => {
    const msg = String(text || "").toLowerCase();
    if (!msg) return "Routing request to MCP tools...";
    if (msg.includes("for these tickets") || msg.includes("bulk") || msg.includes("all tickets")) {
      return "Running MCP tool: analyze_bulk_dry_run";
    }
    if (msg.includes("append request") || msg.includes("append response") || msg.includes("post analysis comment")) {
      return "Running MCP tool: post_analysis_comment";
    }
    if (/(crsup|swpsup)-\d+/i.test(msg) && (msg.includes("analy") || msg.includes("new relic") || msg.includes("singleavail") || msg.includes("api"))) {
      return "Running MCP tool: analyze_support_ticket";
    }
    if (msg.includes("search") || msg.includes("find") || msg.includes("similar") || msg.includes("related")) {
      return "Running MCP tool: search_concept";
    }
    if (msg.includes("show") || msg.includes("details") || /(crsup|swpsup)-\d+/i.test(msg)) {
      return "Running MCP tool: get_issue";
    }
    if (msg.includes("create") && msg.includes("ticket")) {
      return "Running MCP tool: create_issue";
    }
    return "Routing request to MCP tools...";
  };

  const mcpStepsForTool = (toolLabel) => {
    const lower = String(toolLabel || "").toLowerCase();
    const generic = [
      "Understand request",
      "Route to MCP server",
      "Run MCP tool",
      "Format final response",
    ];
    if (lower.includes("analyze_bulk_dry_run")) {
      return [
        "Understand bulk request",
        "Search matching CRSUP tickets",
        "Analyze each ticket via MCP tools",
        "Compile bulk dry-run report",
      ];
    }
    if (lower.includes("analyze_support_ticket")) {
      return [
        "Read ticket context",
        "Query New Relic logs",
        "Build and run singleavail",
        "Summarize analysis output",
      ];
    }
    if (lower.includes("search_concept") || lower.includes("search_issues")) {
      return [
        "Understand search intent",
        "Build Jira query",
        "Run MCP search tool",
        "Summarize matching tickets",
      ];
    }
    return generic;
  };

  const loaderDots = ".".repeat((loaderTick % 3) + 1);
  const mcpSteps = mcpStepsForTool(runningToolLabel);
  // Move step highlight forward in order and hold at final step until response returns.
  const activeStepIdx = mcpSteps.length
    ? Math.min(mcpSteps.length - 1, Math.floor(loaderTick / 3))
    : 0;

   const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    setSending(true);
    setRunningToolLabel(inferRunningToolLabel(msg));
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
      setRunningToolLabel("");
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
        <span className="header-badge">Jira/Azure + New Relic + MCP Tools</span>
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
             <p>Search tickets, analyze issues, run bulk dry-runs, consolidate tickets — just ask in plain language.</p>
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
                <div className={`bubble ${m.role}${m.role === "bot" && hasMarkdown(m.text) ? " md-mode" : ""}`}>
                  {m.role === "bot" && hasMarkdown(m.text)
                    ? <MarkdownBubble text={m.text} />
                    : m.text}
                </div>
              </div>
            ))}
            {sending && (
              <div className="msg-row bot">
                <div className="bubble bot thinking">
                  <div className="tool-running-inline">
                    <span className="loader-dot" />
                    <div className="tool-running-stack">
                      <span className="tool-running-title">JiraAzureCopilot is thinking{loaderDots}</span>
                      <span className="tool-running-phase">MCP workflow in progress</span>
                      <span className="tool-running-tool">{runningToolLabel || "Routing request to MCP tools..."}</span>
                      <div className="tool-running-steps">
                        {mcpSteps.map((step, idx) => {
                          const state = idx < activeStepIdx ? "done" : idx === activeStepIdx ? "active" : "todo";
                          return (
                            <span key={`${step}-${idx}`} className={`tool-step ${state}`}>
                              {idx + 1}. {step}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
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
function MCPToolsView({ jiraUrl = "" }) {
  const [tool, setTool] = useState("get");
  const [resultData, setResultData] = useState(null);
  const [resultText, setResultText] = useState("Result will appear here after running a tool.");

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
  const [anExec, setAnExec] = useState(true);
  const [anComment, setAnComment] = useState(false);
  const [abKeywords, setAbKeywords] = useState("");
  const [abExec, setAbExec] = useState(true);
  const [abComment, setAbComment] = useState(false);
  const [rtJql, setRtJql] = useState('project = SWPSUP AND status IN (Done, Resolved) AND (status WAS "Third Lvl To Do" OR status WAS "Third Lvl In Progress" OR status WAS "Second Lvl To Do" OR status WAS "Second Lvl In Progress") AND assignee IN (rba50, ksh03, mga50, nsh50, ssi51) AND resolved >= -90d ORDER BY resolved DESC');
  const [rtAssignees, setRtAssignees] = useState("rba50, ksh03, mga50, nsh50, ssi51");
  const [rtMaxIssues, setRtMaxIssues] = useState(100);
  const [rtIncludePerIssue, setRtIncludePerIssue] = useState(true);
  const [running, setRunning] = useState(false);

  const rowsFromIssueArray = (payload) => {
    if (!Array.isArray(payload)) return null;
    const rows = payload.filter((item) => item && typeof item === "object" && item.key);
    return rows.length ? rows : null;
  };

  const rowsFromIssueObject = (payload) => {
    if (!payload || typeof payload !== "object") return null;
    if (!Array.isArray(payload.issues)) return null;
    const rows = payload.issues.filter((item) => item && typeof item === "object" && item.key);
    return rows.length ? rows : null;
  };

  const rowsFromBulkResults = (payload) => {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.results)) return null;
    const rows = payload.results.filter((item) => item && typeof item === "object" && item.issueKey);
    return rows.length ? rows : null;
  };

  const priorityTone = (priority) => {
    const p = String(priority || "").toLowerCase();
    if (p.includes("blocker") || p.includes("critical") || p === "p1") return "danger";
    if (p.includes("high") || p === "p2") return "warn";
    if (p.includes("medium") || p === "p3") return "info";
    if (p.includes("low") || p.includes("minor") || p === "p4") return "ok";
    return "neutral";
  };

  const statusTone = (status) => {
    const s = String(status || "").toLowerCase();
    if (s.includes("done") || s.includes("resolved") || s.includes("closed")) return "ok";
    if (s.includes("progress") || s.includes("review") || s.includes("open") || s.includes("todo")) return "info";
    return "neutral";
  };

  const apiStatusTone = (statusCode) => {
    const n = Number(statusCode);
    if (Number.isNaN(n)) return "neutral";
    if (n >= 200 && n < 300) return "ok";
    if (n >= 400) return "danger";
    return "warn";
  };

  const renderIssuesTable = (rows) => (
    <div className="table-wrap">
      <table className="results-table mcp-results-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Ticket</th>
            <th>Summary</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Assignee</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={row.key}>
              <td className="mcp-col-idx">{idx + 1}</td>
              <td><TicketLink ticketKey={row.key} jiraUrl={jiraUrl} /></td>
              <td className="mcp-cell-ellipsis" title={row.summary || "-"}>{row.summary || "-"}</td>
              <td>
                <span className={`mcp-pill ${statusTone(row.status)}`}>{row.status || "-"}</span>
              </td>
              <td>
                <span className={`mcp-pill ${priorityTone(row.priority)}`}>{row.priority || "-"}</span>
              </td>
              <td>{row.assignee || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderBulkTable = (rows) => (
    <div className="table-wrap">
      <table className="results-table mcp-results-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Ticket</th>
            <th>Summary</th>
            <th>Analyzed</th>
            <th>NR Samples</th>
            <th>API Status</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={row.issueKey}>
              <td className="mcp-col-idx">{idx + 1}</td>
              <td><TicketLink ticketKey={row.issueKey} jiraUrl={jiraUrl} /></td>
              <td className="mcp-cell-ellipsis" title={row.summary || "-"}>{row.summary || "-"}</td>
              <td>
                <span className={`mcp-pill ${row.analyzed ? "ok" : "danger"}`}>{row.analyzed ? "Yes" : "No"}</span>
              </td>
              <td>{row.newRelicSampleCount ?? "-"}</td>
              <td>
                {row.singleAvailResponseStatus == null && row?.singleAvailExecution?.performed === false ? (
                  <span className="mcp-pill neutral">Skipped</span>
                ) : (
                  <span className={`mcp-pill ${apiStatusTone(row.singleAvailResponseStatus)}`}>
                    {row.singleAvailResponseStatus ?? "-"}
                  </span>
                )}
              </td>
              <td className="mcp-cell-ellipsis" title={row.error || "-"}>{row.error || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderResolutionTimeTable = (payload) => {
    const rows = Array.isArray(payload?.issueDurations) ? payload.issueDurations : [];
    return (
      <div className="mcp-result-wrap">
        <div className="mcp-meta-row">
          <span>Matched: {payload?.matchedIssueCount ?? 0}</span>
          <span>Analyzed: {payload?.analyzedIssueCount ?? 0}</span>
          <span>Skipped: {payload?.skippedIssueCount ?? 0}</span>
          <span>Avg Hours: {payload?.averageHoursToResolveAfterAssignment ?? "-"}</span>
          <span>Avg Days: {payload?.averageDaysToResolveAfterAssignment ?? "-"}</span>
        </div>
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="results-table mcp-results-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Ticket</th>
                  <th>Assigned At</th>
                  <th>Resolved At</th>
                  <th>Hours</th>
                  <th>Days</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={row.issueKey}>
                    <td className="mcp-col-idx">{idx + 1}</td>
                    <td><TicketLink ticketKey={row.issueKey} jiraUrl={jiraUrl} /></td>
                    <td>{row.assignedAt || "-"}</td>
                    <td>{row.resolvedAt || "-"}</td>
                    <td>{row.hoursToResolve ?? "-"}</td>
                    <td>{row.daysToResolve ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {renderRawResponse(payload, "Raw Resolve Time response")}
      </div>
    );
  };

  const renderRawResponse = (payload, title = "Raw response") => (
    <section className="raw-response-section">
      <div className="raw-response-head">
        <div className="raw-response-title">Advanced / Raw payload</div>
        <div className="raw-response-subtitle">Use this section for full backend output and debugging details.</div>
      </div>
      <details className="raw-response-wrap">
        <summary>{title}</summary>
        <pre className="result-box raw-response-box">{JSON.stringify(payload, null, 2)}</pre>
      </details>
    </section>
  );

  const renderAnalyzeSupportTable = (payload) => {
    const ticket = payload?.ticket || {};
    const newRelic = payload?.newRelic || {};
    const execution = payload?.singleAvailExecution || {};
    const jiraComment = payload?.jiraComment || {};
    const attachment = jiraComment.attachment || {};

    const analyzedOk = !payload?.error;
    const apiStatus = payload?.singleAvailResponse?.statusCode;

    return (
      <div className="mcp-result-wrap">
        <div className="mcp-meta-row">
          <span>NR Samples: {newRelic.sampleCount ?? 0}</span>
          <span>API Status: {payload?.singleAvailResponse?.statusCode ?? "-"}</span>
          <span>Comment Posted: {jiraComment.posted ? "Yes" : "No"}</span>
          <span>Attachment Uploaded: {attachment.uploaded ? "Yes" : "No"}</span>
        </div>
        <div className="table-wrap">
          <table className="results-table mcp-results-table analysis-summary-table">
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Summary</th>
                <th>Analyzed</th>
                <th>NR Samples</th>
                <th>API Status</th>
                <th>Comment</th>
                <th>Attachment</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{ticket.key ? <TicketLink ticketKey={ticket.key} jiraUrl={jiraUrl} /> : "-"}</td>
                <td className="mcp-cell-ellipsis" title={ticket.summary || "-"}>{ticket.summary || "-"}</td>
                <td>
                  <span className={`mcp-pill ${analyzedOk ? "ok" : "danger"}`}>{analyzedOk ? "Yes" : "No"}</span>
                </td>
                <td>{newRelic.sampleCount ?? 0}</td>
                <td>
                  <span className={`mcp-pill ${apiStatusTone(apiStatus)}`}>{apiStatus ?? "-"}</span>
                </td>
                <td>
                  <span className={`mcp-pill ${jiraComment.posted ? "ok" : "neutral"}`}>{jiraComment.posted ? "Posted" : "Not Posted"}</span>
                </td>
                <td>
                  <span className={`mcp-pill ${attachment.uploaded ? "ok" : "neutral"}`}>{attachment.uploaded ? "Uploaded" : "No"}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        {renderRawResponse(payload, "Raw Analyze Single Support Ticket response")}
      </div>
    );
  };

  const renderResult = () => {
    if (resultData == null) return <pre className="result-box">{resultText}</pre>;

    const issueRows = rowsFromIssueArray(resultData) || rowsFromIssueObject(resultData);
    if (issueRows) {
      return (
        <div className="mcp-result-wrap">
          {Array.isArray(resultData?.issues) && (
            <div className="mcp-meta-row">
              <span>Count: {resultData.count ?? issueRows.length}</span>
              {resultData.effective_jql && <span>Effective JQL: {resultData.effective_jql}</span>}
            </div>
          )}
          {!Array.isArray(resultData?.issues) && (
            <div className="mcp-meta-row">
              <span>Count: {issueRows.length}</span>
            </div>
          )}
          {renderIssuesTable(issueRows)}
        </div>
      );
    }

    const bulkRows = rowsFromBulkResults(resultData);
    if (bulkRows) {
      return (
        <div className="mcp-result-wrap">
          <div className="mcp-meta-row">
            <span>Matched: {resultData.ticketsMatched ?? bulkRows.length}</span>
            {resultData.sampleSizeConfigured != null && <span>Sample Size: {resultData.sampleSizeConfigured}</span>}
            {resultData.sinceHoursConfigured != null && <span>Since Hours: {resultData.sinceHoursConfigured}</span>}
          </div>
          {renderBulkTable(bulkRows)}
          {renderRawResponse(resultData, "Raw Bulk Analyze response")}
        </div>
      );
    }

    if (resultData && typeof resultData === "object" && Object.prototype.hasOwnProperty.call(resultData, "averageHoursToResolveAfterAssignment")) {
      return renderResolutionTimeTable(resultData);
    }

    if (resultData && typeof resultData === "object" && resultData.ticket && resultData.indicators && resultData.newRelic) {
      return renderAnalyzeSupportTable(resultData);
    }

    if (resultData && typeof resultData === "object" && resultData.key) {
      return (
        <div className="mcp-result-wrap">
          {renderIssuesTable([resultData])}
        </div>
      );
    }

    return <pre className="result-box">{JSON.stringify(resultData, null, 2)}</pre>;
  };

  const runTool = async () => {
    setRunning(true);
    setResultData(null);
    setResultText("Running…");
    try {
      if (tool === "get" && !issueKey.trim()) {
        throw new Error("Issue key/ticket number is required.");
      }
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
      if (tool === "analyze") data = await postJson("/jira/analyze-support-ticket", { issueKey, executeApi: true, enableJiraComment: anComment });
      if (tool === "resolve-time") {
        data = await postJson("/jira/resolution-time-after-assignment", {
          jql: rtJql,
          assignees: rtAssignees.split(",").map((s) => s.trim()).filter(Boolean),
          maxIssues: +rtMaxIssues,
          includePerIssue: rtIncludePerIssue,
        });
      }
      if (tool === "analyze-bulk") {
        data = await postJson("/jira/analyze-bulk-dry-run", {
          project: "CRSUP",
          extraKeywords: abKeywords.split(",").map((s) => s.trim()).filter(Boolean),
          executeApi: true,
          enableJiraComment: abComment,
        });
      }
      setResultData(data);
    } catch (err) {
      setResultData(null);
      setResultText(`Error: ${err.message}`);
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
              <option value="analyze">Analyze Single Support Ticket</option>
              <option value="resolve-time">Resolution Time After Assignment</option>
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
                  <input type="checkbox" checked={anExec} onChange={(e) => setAnExec(e.target.checked)} disabled />
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

          {tool === "resolve-time" && (
            <>
              <div className="field grow">
                <label>JQL</label>
                <input
                  value={rtJql}
                  onChange={(e) => setRtJql(e.target.value)}
                  placeholder='project = SWPSUP AND status IN (Done, Resolved) AND resolved >= -90d ORDER BY resolved DESC'
                />
              </div>
              <div className="field grow">
                <label>Assignees (comma-separated)</label>
                <input
                  value={rtAssignees}
                  onChange={(e) => setRtAssignees(e.target.value)}
                  placeholder="rba50, ksh03, mga50, nsh50, ssi51"
                />
              </div>
              <div className="field" style={{ maxWidth: 120 }}>
                <label>Max Issues</label>
                <input type="number" value={rtMaxIssues} onChange={(e) => setRtMaxIssues(e.target.value)} />
              </div>
              <div className="field" style={{ justifyContent: "flex-end" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={rtIncludePerIssue} onChange={(e) => setRtIncludePerIssue(e.target.checked)} />
                  Include per-issue durations
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
                  <input type="checkbox" checked={abExec} onChange={(e) => setAbExec(e.target.checked)} disabled />
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

        {renderResult()}
      </div>
    </div>
  );
}

// ── Lightweight markdown renderer ────────────────────────────

/** Render inline **bold** and `code` tokens inside a string. */
function inlineText(text) {
  if (!text) return null;
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  const parts = [];
  let lastIdx = 0;
  let k = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) parts.push(text.slice(lastIdx, match.index));
    const tok = match[0];
    if (tok.startsWith("**"))
      parts.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    else
      parts.push(<code key={k++} className="inline-code">{tok.slice(1, -1)}</code>);
    lastIdx = match.index + tok.length;
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx));
  if (parts.length === 0) return null;
  if (parts.length === 1 && typeof parts[0] === "string") return parts[0];
  return parts;
}

/** Parse a markdown table block into a styled <table>. */
function renderMdTable(tableLines, tableKey) {
  const parseRow = (line) =>
    line.split("|").slice(1, -1).map((c) => c.trim());
  const isSep = (row) => row.every((c) => /^[-: ]+$/.test(c));
  const rows = tableLines.map(parseRow);
  if (!rows.length) return null;
  const header = rows[0];
  const body = rows.slice(1).filter((r) => !isSep(r));

  // Assign a tone class based on cell text content
  const cellTone = (text) => {
    const t = text.toLowerCase();
    if (/✅|posted|complete|yes|executed|enabled/.test(t)) return "md-cell-ok";
    if (/⚠️|missing|skip|warning|not posted/.test(t)) return "md-cell-warn";
    if (/❌|error|fail|🔴/.test(t)) return "md-cell-err";
    if (/^—$|^-$|^n\/a$/i.test(t.trim())) return "md-cell-muted";
    return "";
  };

  return (
    <div key={tableKey} className="md-table-wrap">
      <table className="md-table">
        <thead>
          <tr>{header.map((h, i) => <th key={i}>{inlineText(h)}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} className={cellTone(cell)}>{inlineText(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Full markdown-to-JSX renderer for bot chat bubbles. */
function MarkdownBubble({ text }) {
  const lines = (text || "").split("\n");
  const elements = [];
  let i = 0;
  let bk = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("### ")) {
      elements.push(<h3 key={bk++} className="md-h3">{inlineText(line.slice(4))}</h3>);
      i++; continue;
    }
    if (line.startsWith("#### ")) {
      elements.push(<h4 key={bk++} className="md-h4">{inlineText(line.slice(5))}</h4>);
      i++; continue;
    }
    if (line.startsWith("## ")) {
      elements.push(<h3 key={bk++} className="md-h3">{inlineText(line.slice(3))}</h3>);
      i++; continue;
    }
    if (line.startsWith("> ")) {
      elements.push(
        <blockquote key={bk++} className="md-blockquote">
          {inlineText(line.slice(2))}
        </blockquote>
      );
      i++; continue;
    }
    if (line.startsWith("|")) {
      const tableLines = [];
      while (i < lines.length && lines[i].startsWith("|")) { tableLines.push(lines[i]); i++; }
      elements.push(renderMdTable(tableLines, `tbl-${bk++}`));
      continue;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      const items = [];
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("* "))) {
        items.push(<li key={i}>{inlineText(lines[i].slice(2))}</li>);
        i++;
      }
      elements.push(<ul key={bk++} className="md-ul">{items}</ul>);
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    elements.push(<p key={bk++} className="md-p">{inlineText(line)}</p>);
    i++;
  }
  return <div className="md-render">{elements}</div>;
}

/** Returns true if this bot reply contains markdown that should be rendered. */
function hasMarkdown(text) {
  return /(?:^|\n)[|#>]/.test(text || "");
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
        "Analyze Single Support Ticket — single-ticket New Relic + payload analysis",
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
    mcp: <MCPToolsView jiraUrl={jiraUrl} />,
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
