const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");
const axios = require("axios");

function flattenAdf(node) {
  if (node == null) return "";
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(flattenAdf).filter(Boolean).join(" ");
  if (typeof node === "object") {
    const parts = [];
    if (typeof node.text === "string") parts.push(node.text);
    if (node.content) parts.push(flattenAdf(node.content));
    if (node.attrs) parts.push(flattenAdf(node.attrs));
    return parts.filter(Boolean).join(" ");
  }
  return String(node);
}

function extractFirst(pattern, text) {
  const match = text.match(pattern);
  if (!match || !match[1]) return null;
  const val = String(match[1]).trim();
  return val.length ? val : null;
}

function extractRateAccessCodes(text) {
  const match = text.match(/(?:rate\s*access\s*codes?|RAC_LIST)\s*[:=]\s*([A-Z0-9,;\s-]+)/i);
  if (!match) return [];
  const codes = match[1]
    .split(/[\s,;]+/)
    .map((v) => v.trim().toUpperCase())
    .filter(Boolean);
  return [...new Set(codes)];
}

function buildContext(issue) {
  const fields = issue.fields || {};
  const summary = fields.summary || "";
  const description = flattenAdf(fields.description);
  const comments = ((fields.comment && fields.comment.comments) || []).map((c) => flattenAdf(c.body));
  const blob = [summary, description, ...comments].join("\n");

  return {
    issueKey: issue.key,
    summary,
    museId: extractFirst(/muse\s*id\s*[:=]\s*([A-Z0-9_-]+)/i, blob) || "AMADEUS",
    hrCode: extractFirst(/hr\s*code\s*[:=]\s*([A-Za-z0-9;_-]+)/i, blob),
    hKey: extractFirst(/h\s*key\s*[:=]\s*([A-Za-z0-9_-]+)/i, blob),
    chainId: extractFirst(/chain\s*id\s*[:=]\s*([A-Za-z0-9_-]+)/i, blob),
    bookingSource: extractFirst(/booking\s*source(?:\s*id)?\s*[:=]\s*([0-9]+)/i, blob),
    customerKey: extractFirst(/customer\s*key\s*[:=]\s*([0-9]+)/i, blob),
    arrivalDate: extractFirst(/arrival\s*date\s*[:=]\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})/i, blob),
    departureDate: extractFirst(/departure\s*date\s*[:=]\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})/i, blob),
    rateAccessCodes: extractRateAccessCodes(blob),
    matchedHotelUnavailable: /hotel\s+unavailable/i.test(blob),
    textSample: blob.slice(0, 3000),
  };
}

const jiraClient = axios.create({
  baseURL: process.env.JIRA_HOST,
  headers: {
    Authorization: `Bearer ${process.env.JIRA_PAT}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  },
  timeout: 30000,
});

const server = new McpServer({ name: "jira-ticket-context-mcp", version: "1.0.0" });

server.tool(
  "extract_hotel_unavailable_context",
  "Fetch Jira issue and extract hotel-unavailable investigation fields (museId, hrCode, hKey, dates, etc.)",
  { issueKey: z.string().describe("Jira issue key, e.g. CRSUP-4421") },
  async ({ issueKey }) => {
    try {
      const response = await jiraClient.get(`/rest/api/2/issue/${issueKey}`);
      const context = buildContext(response.data || {});
      return {
        content: [{ type: "text", text: JSON.stringify(context, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text", text: `Failed to extract Jira ticket context: ${error.message}` }],
        isError: true,
      };
    }
  }
);

const transport = new StdioServerTransport();
server.connect(transport).then(() => {
  console.error("Jira Ticket Context MCP Server running...");
});

