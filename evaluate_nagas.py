#!/usr/bin/env python
"""Score NAGAS-style agent evaluation payloads for Ticket Orchestrator workflows.

Usage:
    python evaluate_nagas.py path/to/evaluation.json
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

WEIGHTS = {
    "tool_selection_accuracy": 0.20,
    "tool_grounding_rate": 0.25,
    "unsupported_claim_rate": 0.15,
    "evidence_citation_coverage": 0.15,
    "abstention_correctness": 0.10,
    "parameter_fidelity": 0.10,
    "deterministic_replay_consistency": 0.05,
    "policy_violation_rate": 0.00,
}


def _pct(value: float | int | None) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _score(payload: dict) -> dict:
    metrics = payload.get("metrics", {}) or {}
    normalized = {k: _pct(metrics.get(k)) for k in WEIGHTS}

    accuracy_block = (
        normalized["tool_grounding_rate"]
        * (1.0 - normalized["unsupported_claim_rate"])
        * normalized["evidence_citation_coverage"]
    )
    governance_block = normalized["abstention_correctness"] * (1.0 - normalized["policy_violation_rate"])

    composite = (
        normalized["tool_selection_accuracy"] * WEIGHTS["tool_selection_accuracy"]
        + accuracy_block * WEIGHTS["tool_grounding_rate"]
        + (1.0 - normalized["unsupported_claim_rate"]) * WEIGHTS["unsupported_claim_rate"]
        + normalized["evidence_citation_coverage"] * WEIGHTS["evidence_citation_coverage"]
        + governance_block * WEIGHTS["abstention_correctness"]
        + normalized["parameter_fidelity"] * WEIGHTS["parameter_fidelity"]
        + normalized["deterministic_replay_consistency"] * WEIGHTS["deterministic_replay_consistency"]
    )
    nagas = round(max(0.0, min(100.0, composite * 100.0)), 2)

    tickets = payload.get("tickets", []) or []
    done_count = sum(1 for t in tickets if str(t.get("terminal_state", "")).upper() == "DONE")
    coverage = round((done_count / len(tickets) * 100.0) if tickets else 0.0, 2)

    return {
        "nagas_score": nagas,
        "ticket_terminal_coverage_pct": coverage,
        "normalized_metrics": normalized,
        "total_tickets": len(tickets),
        "done_tickets": done_count,
    }


def _render(payload: dict, score: dict) -> str:
    metrics = score["normalized_metrics"]
    lines = []
    lines.append("# NAGAS Evaluation Report")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| NAGAS Composite Score | {score['nagas_score']} |")
    lines.append(f"| Ticket Terminal Coverage | {score['ticket_terminal_coverage_pct']}% |")
    lines.append(f"| Tool Selection Accuracy | {metrics['tool_selection_accuracy']:.3f} |")
    lines.append(f"| Tool Grounding Rate | {metrics['tool_grounding_rate']:.3f} |")
    lines.append(f"| Unsupported Claim Rate | {metrics['unsupported_claim_rate']:.3f} |")
    lines.append(f"| Evidence Citation Coverage | {metrics['evidence_citation_coverage']:.3f} |")
    lines.append(f"| Abstention Correctness | {metrics['abstention_correctness']:.3f} |")
    lines.append(f"| Parameter Fidelity | {metrics['parameter_fidelity']:.3f} |")
    lines.append(f"| Deterministic Replay Consistency | {metrics['deterministic_replay_consistency']:.3f} |")
    lines.append(f"| Policy Violation Rate | {metrics['policy_violation_rate']:.3f} |")
    lines.append("")

    tickets = payload.get("tickets", []) or []
    if tickets:
        lines.append("## Tickets")
        lines.append("")
        lines.append("| Ticket | Intent | Expected Path | Observed Path | Terminal State |")
        lines.append("|---|---|---|---|---|")
        for ticket in tickets:
            lines.append(
                f"| {ticket.get('issue_key', '')} | {ticket.get('intent', '')} | {ticket.get('expected_path', '')} | {ticket.get('observed_path', '')} | {ticket.get('terminal_state', '')} |"
            )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python evaluate_nagas.py path/to/evaluation.json", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    payload = _load(path)
    score = _score(payload)
    print(_render(payload, score))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))



