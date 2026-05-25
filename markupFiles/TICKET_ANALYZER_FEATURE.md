# Ticket Analyzer Feature Guide

This guide explains how to run the Ticket Analyzer from CLI and UI, including dry-run behavior, EC2 execution, and Jira comment posting controls.

## What the Analyzer Does

- Reads Jira ticket context
- Extracts investigation fields from description/comments
- Queries New Relic logs
- Builds singleavail payload
- Optionally executes EC2 singleavail API
- Optionally posts Jira comments (or previews what would be posted)

## Required Environment Variables

Set these before running:

- `JIRA_URL`
- `JIRA_PAT`
- `NEW_RELIC_API_KEY`
- `NEW_RELIC_ACCOUNT_ID`

Optional:

- `NEW_RELIC_GRAPHQL_URL`
- `NEW_RELIC_LOG_API_URL`
- `NEW_RELIC_CA_BUNDLE`
- `NEW_RELIC_INSECURE`
- `NEW_RELIC_LOG_TABLES`
- `EC2_SINGLEAVAIL_URL`
- `EC2_BEARER_TOKEN`
- `TICKET_ANALYSIS_KEYWORDS_FILE`
- `ANALYZER_INCLUDE_COMMENTS` (default `false`; when `true`, indicator extraction also reads Jira comments)

## CLI Commands

Run from repo root.

### 1) Analyze single ticket (no EC2 call)

```powershell
python .\support_ticket_analyzer.py --issue-key CRSUP-4421 --since-hours 24
```

### 2) Analyze single ticket and execute EC2 API

```powershell
python .\support_ticket_analyzer.py --issue-key CRSUP-4421 --since-hours 24 --execute-api
```

### 3) Save full output to file

```powershell
python .\support_ticket_analyzer.py --issue-key CRSUP-4421 --since-hours 24 --execute-api --output analysis.json
```

## UI Flow

Start UI:

```powershell
python .\ui_app.py
```

Open:

```text
http://localhost:5000
```

Go to:

- `🔧 Jira MCP Tools`
- Select `📚 Bulk Analyze (CRSUP Dry Run)`

## Bulk Analyze (CRSUP) Options

- **Project**: fixed to `CRSUP`
- **Extra Keywords**: optional comma-separated keywords merged with config keywords
- **Execute API** (toggle): whether EC2 singleavail is called
- **Enable Jira Comment Posting (CRSUP only)** (toggle): whether comments are actually posted

Backend-controlled defaults (not entered in UI):

- `BULK_DRY_RUN_SINCE_HOURS`
- `BULK_DRY_RUN_SAMPLE_SIZE`
- `SINGLE_ANALYZE_SINCE_HOURS`

Helper note in UI:

- `Both off by default for safe production testing.`

## Dry-Run Behavior

For the bulk testing workflow:

- You can keep both toggles OFF for safest testing
- Jira comment preview is included in analysis output when available
- Real posting only happens when comment posting toggle is enabled

## AI Chat Behavior (Current)

- Plain-language prompts are routed to tools automatically (`search_concept`, `search_issues`, `analyze_support_ticket`, `analyze_bulk_dry_run`).
- Follow-up prompts like "for these tickets hit API, do not comment" stay in bulk mode and apply `executeApi=true`, `enableJiraComment=false`.
- Analyzer replies in chat are deterministic and tool-grounded for single/bulk analysis to avoid contradictory summaries.
- Bulk dry-run chat output includes full would-be Jira comment text by default.

Optional chat env control:

- `BULK_REPLY_COMMENT_PREVIEW_MAX_CHARS` (default `0` = no truncation)

## Ticket Keyword Config

Default keyword file:

- `ticket_analysis_keywords.json`

Example:

```json
{
  "availabilityKeywords": [
    "hotel not available",
    "hotel unavailable",
    "hotel not bookable"
  ]
}
```

You can add more phrases to this list without code changes.

## Missing Fields Safeguard

If ticket lacks core filtering fields (such as `hrCode`, `hKey`, `chainId`, `customerKey/kKey`, `companyKey/fKey`), analyzer skips broad NRQL fallback and asks user to add required fields in the ticket.

## Troubleshooting

- If New Relic TLS fails, configure `NEW_RELIC_CA_BUNDLE` or use `NEW_RELIC_INSECURE=true` for testing only.
- If Jira API fails, verify `JIRA_URL` and `JIRA_PAT`.
- If no keywords match, check `ticket_analysis_keywords.json` and optional extra keywords in UI.

