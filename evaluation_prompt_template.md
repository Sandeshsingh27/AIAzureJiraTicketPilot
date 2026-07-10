# NAGAS Evaluation Prompt Template

Use this template to evaluate a single agent run or a batch of runs for Jira / New Relic / EC2 workflows.

## System / Judge Instructions

You are an evaluation agent. Your job is to score the provided run strictly from the evidence in the input.

Rules:
- Do **not** invent missing facts.
- Mark a claim as unsupported if it is not backed by tool output or explicit evidence.
- Favor `NEEDS_INPUT` over guessing when required fields are missing.
- Check whether the tool route matched the user intent.
- Verify that final responses cite evidence from Jira, New Relic, or EC2 payloads when applicable.
- If the same input is replayed, check for consistency of the final answer.

## Scoring Dimensions

Score each dimension from `0.0` to `1.0`.

- `tool_selection_accuracy`
- `tool_grounding_rate`
- `unsupported_claim_rate`
- `evidence_citation_coverage`
- `abstention_correctness`
- `parameter_fidelity`
- `deterministic_replay_consistency`
- `policy_violation_rate`

## Evaluation Tasks

1. Determine whether the agent chose the correct workflow:
   - `search-only`
   - `single-ticket-analysis`
   - `bulk-dry-run`
   - `comment-only`
   - `orchestrator`

2. Check each tool call:
   - Was the tool necessary?
   - Were the arguments correct?
   - Did the tool output support the final claim?

3. Inspect the final response:
   - Are all factual statements grounded in evidence?
   - Are ticket keys, counts, HTTP statuses, and skip reasons correct?
   - Does the response mention when data was not available?

4. Produce a JSON result that matches `metrics_schema.json`.

## Required Output Format

Return only valid JSON with this shape:

```json
{
  "schema_version": "1.0.0",
  "run_id": "run-001",
  "timestamp_utc": "2026-06-02T12:00:00Z",
  "workflow": "bulk-dry-run",
  "source": {
    "model": "gpt-4o-mini",
    "agent": "chat_agent",
    "tools": ["search_concept", "analyze_bulk_dry_run"]
  },
  "metrics": {
    "tool_selection_accuracy": 1.0,
    "tool_grounding_rate": 0.95,
    "unsupported_claim_rate": 0.05,
    "evidence_citation_coverage": 1.0,
    "abstention_correctness": 0.9,
    "parameter_fidelity": 1.0,
    "deterministic_replay_consistency": 0.98,
    "policy_violation_rate": 0.0
  },
  "tickets": [
    {
      "issue_key": "CRSUP-4421",
      "intent": "room category issue",
      "expected_path": "search-only",
      "observed_path": "search-only",
      "terminal_state": "DONE",
      "evidence": [
        {"source": "jira", "field": "summary", "value": "Room Category Issue"}
      ],
      "notes": ""
    }
  ],
  "notes": ""
}
```

## Suggested Final Checks

- If `unsupported_claim_rate > 0.05`, flag the run.
- If `tool_selection_accuracy < 0.95`, flag routing regression.
- If `terminal_state != DONE` for important tickets, flag for manual review.


Our Score:
| Metric | Value |
|---|---:|
| NAGAS Composite Score | 67.65 |
| Ticket Terminal Coverage | 0.0% |
| Tool Selection Accuracy | 0.800 |
| Tool Grounding Rate | 0.700 |
| Unsupported Claim Rate | 0.200 |
| Evidence Citation Coverage | 0.600 |
| Abstention Correctness | 0.900 |
| Parameter Fidelity | 0.850 |
| Deterministic Replay Consistency | 0.950 |
| Policy Violation Rate | 0.000 |
