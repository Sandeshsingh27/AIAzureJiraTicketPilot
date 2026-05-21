const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");
const axios = require("axios");

// ---- Jira client setup ----
const jiraClient = axios.create({
    baseURL: process.env.JIRA_HOST,
    headers: {
        Authorization: `Bearer ${process.env.JIRA_PAT}`,
        "Content-Type": "application/json",
        Accept: "application/json",
    },
});

// ---- MCP Server setup ----
const server = new McpServer({ name: "jira-mcp", version: "1.0.0" });

// ---- get_issue tool ----
server.tool(
    "get_issue",
    "Get full Jira issue details by key (e.g., CRSUP-4421)",
    { issueKey: z.string().describe("Jira issue key e.g. CRSUP-4421") },
    async ({ issueKey }) => {
        try {
            const response = await jiraClient.get(`/rest/api/2/issue/${issueKey}`);
            const fields = response.data.fields || {};
            return {
                content: [{
                    type: "text",
                    text: JSON.stringify({
                        key: response.data.key,
                        summary: fields.summary,
                        description: fields.description,
                        status: fields.status?.name,
                        priority: fields.priority?.name,
                        assignee: fields.assignee?.displayName,
                        reporter: fields.reporter?.displayName,
                        created: fields.created,
                        updated: fields.updated,
                        labels: fields.labels,
                    }, null, 2),
                }],
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error fetching issue: ${error.message}` }],
                isError: true,
            };
        }
    }
);

// ---- fetch_jira_issue alias ----
server.tool(
    "fetch_jira_issue",
    "Alias of get_issue for backward compatibility",
    { issueKey: z.string().describe("Jira issue key e.g. CRSUP-4421") },
    async ({ issueKey }) => {
        try {
            const response = await jiraClient.get(`/rest/api/2/issue/${issueKey}`);
            const fields = response.data.fields || {};
            return {
                content: [{
                    type: "text",
                    text: JSON.stringify({
                        key: response.data.key,
                        summary: fields.summary,
                        description: fields.description,
                        status: fields.status?.name,
                        priority: fields.priority?.name,
                        assignee: fields.assignee?.displayName,
                        reporter: fields.reporter?.displayName,
                        created: fields.created,
                        updated: fields.updated,
                        labels: fields.labels,
                    }, null, 2),
                }],
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Error fetching issue: ${error.message}` }],
                isError: true,
            };
        }
    }
);

// ---- search_jira_issues tool ----
server.tool(
    "search_jira_issues",
    "Search Jira issues using JQL query",
    {
        jql: z.string().describe("JQL query e.g. project=CRS AND status=Open"),
        maxResults: z.number().optional().describe("Max results to return (default: 10)"),
    },
    async ({ jql, maxResults = 10 }) => {
        try {
            const response = await jiraClient.get(`/rest/api/2/search`, {
                params: { jql, maxResults },
            });
            const issues = response.data.issues.map((issue) => ({
                key: issue.key,
                summary: issue.fields.summary,
                status: issue.fields.status?.name,
                priority: issue.fields.priority?.name,
                assignee: issue.fields.assignee?.displayName,
            }));
            return { content: [{ type: "text", text: JSON.stringify(issues, null, 2) }] };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Search failed: ${error.message}` }],
                isError: true,
            };
        }
    }
);

// ---- create_jira_issue tool ----
server.tool(
    "create_jira_issue",
    "Create a new Jira issue",
    {
        project: z.string().describe("Project key e.g. CRS"),
        issueType: z.string().describe("Issue type e.g. Task, Bug, Story"),
        summary: z.string().describe("Issue title/summary"),
        description: z.string().optional().describe("Issue description"),
    },
    async ({ project, issueType, summary, description }) => {
        try {
            const response = await jiraClient.post(`/rest/api/2/issue`, {
                fields: {
                    project: { key: project },
                    issuetype: { name: issueType },
                    summary,
                    description,
                },
            });
            return {
                content: [{
                    type: "text",
                    text: `Issue created: ${response.data.key} → ${process.env.JIRA_HOST}/browse/${response.data.key}`,
                }],
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Failed to create issue: ${error.message}` }],
                isError: true,
            };
        }
    }
);

// ---- add_comment tool ----
server.tool(
    "add_comment",
    "Add a comment to an existing Jira issue",
    {
        issueKey: z.string().describe("Jira issue key e.g. CRS-6788"),
        comment: z.string().describe("Comment text to add"),
    },
    async ({ issueKey, comment }) => {
        try {
            await jiraClient.post(`/rest/api/2/issue/${issueKey}/comment`, { body: comment });
            return { content: [{ type: "text", text: `Comment added to ${issueKey} successfully.` }] };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Failed to add comment: ${error.message}` }],
                isError: true,
            };
        }
    }
);

// ---- Start server ----
const transport = new StdioServerTransport();
server.connect(transport).then(() => {
    console.error("Jira MCP Server running (PAT auth)...");
});