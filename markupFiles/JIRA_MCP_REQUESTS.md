# Jira MCP Request JSON Inputs

This reference lists the request JSON payloads for all Jira MCP tools defined in `jira-mcp-server.js`.

## 1) get_issue

Purpose: Get full Jira issue details by key.

```json
{
  "issueKey": "CRSUP-4421"
}
```

## 2) fetch_jira_issue

Purpose: Alias of `get_issue` (backward compatibility).

```json
{
  "issueKey": "CRSUP-4421"
}
```

## 3) search_jira_issues

Purpose: Search issues with JQL.

```json
{
  "jql": "project=CRS AND status=Open",
  "maxResults": 10
}
```

Minimal form (uses default `maxResults`):

```json
{
  "jql": "project=CRS AND status=Open"
}
```

## 4) create_jira_issue

Purpose: Create a new Jira issue.

```json
{
  "project": "CRS",
  "issueType": "Task",
  "summary": "Sample issue title",
  "description": "Sample issue description"
}
```

Minimal form (`description` optional):

```json
{
  "project": "CRS",
  "issueType": "Bug",
  "summary": "Login fails on APAC tenant"
}
```

## 5) add_comment

Purpose: Add a comment to an existing issue.

```json
{
  "issueKey": "CRS-6788",
  "comment": "This is a test comment from MCP."
}
```

---

## Quick copy set (all tools)

```json
{
  "issueKey": "CRSUP-4421"
}
```

```json
{
  "issueKey": "CRSUP-4421"
}
```

```json
{
  "jql": "project=CRS AND status=Open",
  "maxResults": 10
}
```

```json
{
  "project": "CRS",
  "issueType": "Task",
  "summary": "Sample issue title",
  "description": "Sample issue description"
}
```

```json
{
  "issueKey": "CRS-6788",
  "comment": "This is a test comment from MCP."
}
```
