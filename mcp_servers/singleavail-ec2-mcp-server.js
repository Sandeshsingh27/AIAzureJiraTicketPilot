const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");
const axios = require("axios");

const DEFAULT_URL = "http://iut1-crsng-tester-backend.iec.hrs.cc/crsng/singleavail";

function toIsoDateStart(value, fallbackDays) {
  if (value) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      parsed.setUTCHours(0, 0, 0, 0);
      return parsed.toISOString();
    }
  }
  const now = new Date();
  now.setUTCDate(now.getUTCDate() + fallbackDays);
  now.setUTCHours(0, 0, 0, 0);
  return now.toISOString();
}

function buildPayload(input) {
  const customerKey = String(input.customerKey || "29908");
  const companyId = Number(customerKey);

  return {
    environment: input.environment || "PROD",
    museId: input.museId || "AMADEUS",
    hotels: [
      {
        hrCode: input.hrCode || null,
        hKey: input.hKey || null,
        priority: null,
        multisource: Boolean(input.multisource || false),
        chainId: String(input.chainId || "123"),
        ciWhitelisted: Boolean(input.ciWhitelisted || false),
      },
    ],
    arrivalDate: toIsoDateStart(input.arrivalDate, 7),
    departureDate: toIsoDateStart(input.departureDate, 8),
    singleRooms: Number(input.singleRooms || 1),
    doubleRooms: Number(input.doubleRooms || 0),
    adults: Number(input.adults || 1),
    children: Number(input.children || 0),
    rateAccessCodes: (input.rateAccessCodes && input.rateAccessCodes.length) ? input.rateAccessCodes : ["HRQ", "SIE"],
    companyIds: Number.isNaN(companyId) ? [29908] : [companyId],
    corporateDiscountFlag: Boolean(input.corporateDiscountFlag || false),
    bookingSource: String(input.bookingSource || "13"),
    customerKey,
  };
}

async function callSingleAvail(endpointUrl, payload) {
  const token = process.env.EC2_BEARER_TOKEN;
  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await axios.post(endpointUrl, payload, { headers, timeout: 60000 });
  return {
    statusCode: response.status,
    ok: response.status >= 200 && response.status < 300,
    responseHeaders: response.headers,
    body: response.data,
  };
}

const server = new McpServer({ name: "singleavail-ec2-mcp", version: "1.0.0" });

server.tool(
  "build_singleavail_payload",
  "Build a singleavail request payload from extracted New Relic/Jira variables.",
  {
    environment: z.string().optional(),
    museId: z.string().optional(),
    hrCode: z.string().optional(),
    hKey: z.string().nullable().optional(),
    chainId: z.string().optional(),
    multisource: z.boolean().optional(),
    ciWhitelisted: z.boolean().optional(),
    arrivalDate: z.string().optional(),
    departureDate: z.string().optional(),
    singleRooms: z.number().optional(),
    doubleRooms: z.number().optional(),
    adults: z.number().optional(),
    children: z.number().optional(),
    rateAccessCodes: z.array(z.string()).optional(),
    bookingSource: z.string().optional(),
    customerKey: z.string().optional(),
    corporateDiscountFlag: z.boolean().optional(),
  },
  async (args) => {
    try {
      const payload = buildPayload(args);
      return { content: [{ type: "text", text: JSON.stringify(payload, null, 2) }] };
    } catch (error) {
      return {
        content: [{ type: "text", text: `Failed to build payload: ${error.message}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "call_singleavail_endpoint",
  "Call EC2 singleavail endpoint using investigation variables (or a prebuilt payload).",
  {
    endpointUrl: z.string().optional().describe("EC2 endpoint URL. Defaults from EC2_SINGLEAVAIL_URL env."),
    payload: z.any().optional().describe("Optional full payload. If omitted, payload is built from other args."),
    environment: z.string().optional(),
    museId: z.string().optional(),
    hrCode: z.string().optional(),
    hKey: z.string().nullable().optional(),
    chainId: z.string().optional(),
    multisource: z.boolean().optional(),
    ciWhitelisted: z.boolean().optional(),
    arrivalDate: z.string().optional(),
    departureDate: z.string().optional(),
    singleRooms: z.number().optional(),
    doubleRooms: z.number().optional(),
    adults: z.number().optional(),
    children: z.number().optional(),
    rateAccessCodes: z.array(z.string()).optional(),
    bookingSource: z.string().optional(),
    customerKey: z.string().optional(),
    corporateDiscountFlag: z.boolean().optional(),
  },
  async (args) => {
    try {
      const endpointUrl = args.endpointUrl || process.env.EC2_SINGLEAVAIL_URL || DEFAULT_URL;
      const payload = args.payload || buildPayload(args);
      const result = await callSingleAvail(endpointUrl, payload);
      return { content: [{ type: "text", text: JSON.stringify({ endpointUrl, payload, result }, null, 2) }] };
    } catch (error) {
      return {
        content: [{ type: "text", text: `singleavail call failed: ${error.message}` }],
        isError: true,
      };
    }
  }
);

const transport = new StdioServerTransport();
server.connect(transport).then(() => {
  console.error("SingleAvail EC2 MCP Server running...");
});

