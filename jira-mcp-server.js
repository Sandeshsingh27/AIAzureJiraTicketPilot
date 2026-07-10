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

function normalizeUserValue(value) {
    return String(value || "").trim().toLowerCase();
}

function parseJiraDate(dateText) {
    const date = new Date(dateText);
    if (Number.isNaN(date.getTime())) {
        throw new Error(`Invalid Jira date value: ${dateText}`);
    }
    return date;
}

async function fetchIssuesByJqlPaginated(jql, limit) {
    const issues = [];
    const pageSize = Math.min(100, Math.max(1, limit));
    let startAt = 0;

    while (issues.length < limit) {
        const response = await jiraClient.get(`/rest/api/2/search`, {
            params: {
                jql,
                startAt,
                maxResults: Math.min(pageSize, limit - issues.length),
                fields: "resolutiondate,created",
            },
        });

        const batch = response.data?.issues || [];
        issues.push(...batch);

        if (!batch.length) break;

        startAt += batch.length;
        const total = Number(response.data?.total || 0);
        if (startAt >= total) break;
    }

    return issues;
}

async function fetchIssueChangelog(issueKey) {
    const histories = [];
    let startAt = 0;
    const maxResults = 100;
    const endpoints = [
        `/rest/api/3/issue/${issueKey}/changelog`,
        `/rest/api/2/issue/${issueKey}/changelog`,
    ];
    let activeEndpoint = null;

    while (true) {
        let response = null;
        let endpointUsed = activeEndpoint;

        if (activeEndpoint) {
            response = await jiraClient.get(activeEndpoint, { params: { startAt, maxResults } });
        } else {
            let lastError = null;
            for (const endpoint of endpoints) {
                try {
                    response = await jiraClient.get(endpoint, { params: { startAt, maxResults } });
                    endpointUsed = endpoint;
                    break;
                } catch (error) {
                    lastError = error;
                }
            }
            if (!response) {
                throw lastError || new Error(`Unable to fetch changelog for ${issueKey}`);
            }
        }

        activeEndpoint = endpointUsed;
        const data = response.data || {};
        const values = data.values || data.histories || [];

        histories.push(...values);
        if (!values.length) break;

        startAt += values.length;
        const total = Number(data.total || 0);
        if (total > 0 && startAt >= total) break;
        if (!Number.isFinite(total) || total === 0) break;
    }

    return histories;
}

function findFirstAssignmentDate(histories, targetAssignees) {
    const matches = [];

    for (const history of histories || []) {
        const changeDateRaw = history?.created;
        if (!changeDateRaw) continue;

        const changeDate = parseJiraDate(changeDateRaw);
        const items = history?.items || [];

        for (const item of items) {
            if (normalizeUserValue(item?.field) !== "assignee") continue;

            const toValue = normalizeUserValue(item?.to);
            const toStringValue = normalizeUserValue(item?.toString);
            if (targetAssignees.has(toValue) || targetAssignees.has(toStringValue)) {
                matches.push(changeDate);
            }
        }
    }

    if (!matches.length) return null;
    matches.sort((a, b) => a.getTime() - b.getTime());
    return matches[0];
}

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

// ---- resolution-time-from-assignment tool ----
server.tool(
    "calculate_resolution_time_after_assignment",
    "Calculate per-issue and average resolution time after assignment to selected assignees",
    {
        jql: z.string().describe("JQL used to fetch issues (should include resolved issues)."),
        assignees: z.array(z.string()).nonempty().describe("Assignee identifiers (username/accountId/display value as seen in changelog)."),
        maxIssues: z.number().int().positive().max(1000).optional().describe("Maximum issues to analyze (default: 500)."),
        includePerIssue: z.boolean().optional().describe("Include per-issue durations in output (default: true)."),
    },
    async ({ jql, assignees, maxIssues = 500, includePerIssue = true }) => {
        try {
            const targetAssignees = new Set(assignees.map((value) => normalizeUserValue(value)).filter(Boolean));
            if (!targetAssignees.size) {
                return {
                    content: [{ type: "text", text: "No valid assignees provided." }],
                    isError: true,
                };
            }

            const issues = await fetchIssuesByJqlPaginated(jql, maxIssues);
            const issueDurations = [];
            const skipped = [];

            for (const issue of issues) {
                const issueKey = issue?.key;
                const resolutionDateRaw = issue?.fields?.resolutiondate;
                if (!issueKey) continue;

                try {
                    if (!resolutionDateRaw) {
                        skipped.push({ issueKey, reason: "Missing resolutiondate" });
                        continue;
                    }

                    const resolvedAt = parseJiraDate(resolutionDateRaw);
                    const changelog = await fetchIssueChangelog(issueKey);
                    const assignedAt = findFirstAssignmentDate(changelog, targetAssignees);

                    if (!assignedAt) {
                        skipped.push({ issueKey, reason: "No assignment to target assignees in changelog" });
                        continue;
                    }

                    const durationMs = resolvedAt.getTime() - assignedAt.getTime();
                    if (durationMs < 0) {
                        skipped.push({ issueKey, reason: "Resolution date is earlier than assignment date" });
                        continue;
                    }

                    issueDurations.push({
                        issueKey,
                        assignedAt: assignedAt.toISOString(),
                        resolvedAt: resolvedAt.toISOString(),
                        hoursToResolve: Number((durationMs / (1000 * 60 * 60)).toFixed(2)),
                        daysToResolve: Number((durationMs / (1000 * 60 * 60 * 24)).toFixed(2)),
                    });
                } catch (issueError) {
                    skipped.push({ issueKey, reason: issueError.message });
                }
            }

            const totalHours = issueDurations.reduce((sum, item) => sum + item.hoursToResolve, 0);
            const analyzedCount = issueDurations.length;
            const averageHours = analyzedCount ? Number((totalHours / analyzedCount).toFixed(2)) : null;
            const averageDays = averageHours === null ? null : Number((averageHours / 24).toFixed(2));

            const result = {
                jql,
                assignees: Array.from(targetAssignees),
                matchedIssueCount: issues.length,
                analyzedIssueCount: analyzedCount,
                skippedIssueCount: skipped.length,
                averageHoursToResolveAfterAssignment: averageHours,
                averageDaysToResolveAfterAssignment: averageDays,
                skippedIssues: skipped,
            };

            if (includePerIssue) {
                result.issueDurations = issueDurations;
            }

            return {
                content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
            };
        } catch (error) {
            return {
                content: [{ type: "text", text: `Failed to calculate resolution timing: ${error.message}` }],
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