const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");
const axios = require("axios");
const https = require("https");
const fs = require("fs");

const DEFAULT_NEW_RELIC_GRAPHQL_URL = "https://api.newrelic.com/graphql";

function nrqlEscape(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function buildNrql({ hrCode, hKey, museId, chainId, bookingSource, customerKey, sinceHours }) {
  const tokens = ["hotel unavailable", "singleavail"];
  const identifiers = [hrCode, hKey, museId, chainId, bookingSource, customerKey].filter(Boolean);

  const whereParts = [];
  whereParts.push("(" + tokens.map((t) => `message LIKE '%${nrqlEscape(t)}%'`).join(" OR ") + ")");

  if (identifiers.length) {
    whereParts.push("(" + identifiers.map((v) => `message LIKE '%${nrqlEscape(v)}%'`).join(" OR ") + ")");
  }

  return (
    "SELECT timestamp, message, statusCode, responseStatus, level, museId, hrCode, hKey, chainId, " +
    "bookingSource, customerKey, arrivalDate, departureDate FROM Log " +
    `WHERE ${whereParts.join(" AND ")} SINCE ${Math.max(1, Number(sinceHours || 24))} hours ago LIMIT 200`
  );
}

function isSuccessLog(log) {
  const statusCandidates = [log.statusCode, log.responseStatus, log.status];
  for (const status of statusCandidates) {
    if (status == null) continue;
    const raw = String(status).trim().toUpperCase();
    if (raw === "200" || raw === "OK" || raw === "SUCCESS") return true;
    const parsed = Number(raw);
    if (!Number.isNaN(parsed) && parsed === 200) return true;
  }
  const msg = String(log.message || "").toLowerCase();
  return msg.includes("success") || msg.includes("availableforsale");
}

function firstNonEmpty(values) {
  for (const value of values) {
    if (value == null) continue;
    if (typeof value === "string" && value.trim() === "") continue;
    return value;
  }
  return null;
}

function resolveNewRelicGraphqlUrl() {
  const configuredGraphql = (process.env.NEW_RELIC_GRAPHQL_URL || "").trim();
  if (configuredGraphql) return configuredGraphql;

  const logApiUrl = (process.env.NEW_RELIC_LOG_API_URL || "").trim();
  if (logApiUrl) {
    try {
      const parsed = new URL(logApiUrl);
      if (parsed.hostname.startsWith("log-api.")) {
        parsed.hostname = parsed.hostname.replace("log-api.", "api.");
        parsed.pathname = "/graphql";
        parsed.search = "";
        parsed.hash = "";
        return parsed.toString();
      }
    } catch (_) {
      // Ignore invalid URL and fall back to default.
    }
  }

  return DEFAULT_NEW_RELIC_GRAPHQL_URL;
}

function envFlag(value) {
  return String(value || "").trim().toLowerCase().match(/^(1|true|yes|y|on)$/) !== null;
}

function buildHttpsAgent() {
  const insecure = envFlag(process.env.NEW_RELIC_INSECURE);
  const caBundlePath = String(process.env.NEW_RELIC_CA_BUNDLE || "").trim();

  if (insecure) {
    return { httpsAgent: new https.Agent({ rejectUnauthorized: false }), tlsVerify: false };
  }

  if (caBundlePath) {
    const ca = fs.readFileSync(caBundlePath);
    return {
      httpsAgent: new https.Agent({ rejectUnauthorized: true, ca }),
      tlsVerify: caBundlePath,
    };
  }

  return { httpsAgent: undefined, tlsVerify: true };
}

function summarizeLogs(logs) {
  const sorted = [...logs].sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0));
  const successCount = sorted.filter(isSuccessLog).length;

  const derived = {
    museId: firstNonEmpty(sorted.map((l) => l.museId)),
    hrCode: firstNonEmpty(sorted.map((l) => l.hrCode)),
    hKey: firstNonEmpty(sorted.map((l) => l.hKey)),
    chainId: firstNonEmpty(sorted.map((l) => l.chainId)),
    bookingSource: firstNonEmpty(sorted.map((l) => l.bookingSource)),
    customerKey: firstNonEmpty(sorted.map((l) => l.customerKey)),
    arrivalDate: firstNonEmpty(sorted.map((l) => l.arrivalDate)),
    departureDate: firstNonEmpty(sorted.map((l) => l.departureDate)),
  };

  return {
    matched: sorted.length,
    successful: successCount > 0,
    successCount,
    failureCount: sorted.length - successCount,
    latest: sorted[0] || null,
    derived,
  };
}

async function queryNerdGraph({ accountId, apiKey, nrql }) {
  const gql =
    "query($accountId:Int!, $nrql:String!) { actor { account(id: $accountId) { nrql(query: $nrql) { results } } } }";

  const graphqlUrl = resolveNewRelicGraphqlUrl();
  const { httpsAgent, tlsVerify } = buildHttpsAgent();
  const response = await axios.post(
    graphqlUrl,
    {
      query: gql,
      variables: { accountId: Number(accountId), nrql },
    },
    {
      headers: {
        "API-Key": apiKey,
        "Content-Type": "application/json",
      },
      timeout: 45000,
      httpsAgent,
    }
  );

  if (response.data && response.data.errors) {
    throw new Error(JSON.stringify(response.data.errors));
  }

  const results = (((response.data || {}).data || {}).actor || {}).account?.nrql?.results || [];
  return { results, graphqlUrl, tlsVerify };
}

const server = new McpServer({ name: "newrelic-log-check-mcp", version: "1.0.0" });

server.tool(
  "check_hotel_unavailable_logs",
  "Query New Relic logs for hotel-unavailable investigation keys and report success/failure summary.",
  {
    hrCode: z.string().optional().describe("Hotel hrCode, e.g. TG;XWH;539"),
    hKey: z.string().optional().describe("Hotel hKey"),
    museId: z.string().optional().describe("museId, e.g. AMADEUS"),
    chainId: z.string().optional().describe("chainId"),
    bookingSource: z.string().optional().describe("bookingSource"),
    customerKey: z.string().optional().describe("customerKey"),
    sinceHours: z.number().optional().describe("Lookback window in hours (default: 24)"),
  },
  async (args) => {
    try {
      const accountId = process.env.NEW_RELIC_ACCOUNT_ID;
      const apiKey = process.env.NEW_RELIC_API_KEY;
      if (!accountId || !apiKey) {
        throw new Error("NEW_RELIC_ACCOUNT_ID and NEW_RELIC_API_KEY are required in environment");
      }

      const nrql = buildNrql({ ...args, sinceHours: args.sinceHours || 24 });
      const { results: logs, graphqlUrl, tlsVerify } = await queryNerdGraph({ accountId, apiKey, nrql });
      const summary = summarizeLogs(logs);

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ graphqlUrl, tlsVerify, nrql, summary, sampleCount: logs.length, sample: logs.slice(0, 5) }, null, 2),
          },
        ],
      };
    } catch (error) {
      const maybeTls = String(error && error.message ? error.message : "");
      const guidance = maybeTls.toLowerCase().includes("certificate") || maybeTls.toLowerCase().includes("ssl")
        ? " Set NEW_RELIC_CA_BUNDLE to your corporate root CA path, or NEW_RELIC_INSECURE=true for test-only bypass."
        : "";
      return {
        content: [{ type: "text", text: `New Relic log check failed: ${error.message}.${guidance}` }],
        isError: true,
      };
    }
  }
);

const transport = new StdioServerTransport();
server.connect(transport).then(() => {
  console.error("New Relic Log Check MCP Server running...");
});

