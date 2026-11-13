# SPDX-License-Identifier: AGPL-3.0-or-later
"""Expected eligibility outcomes for the synthetic learners in the demo seed.

This is a reference oracle for *seed data only*, written against the semantics in
docs/architecture/architecture.md §5 (three-valued Kleene logic, released-grade rules). The
production rules engine (``opencredential.rules``, W5) evaluates LMS snapshots and must agree
with these outcomes; tests/integration/test_seed.py pins them so W5 has golden data.
"""

from __future__ import annotations

from typing import Any

MET, NOT_MET, UNKNOWN = "met", "not_met", "unknown"


def _combine(mode: str, outcomes: list[str]) -> str:
    if mode == "ALL":
        if NOT_MET in outcomes:
            return NOT_MET
        return UNKNOWN if UNKNOWN in outcomes else MET
    if MET in outcomes:
        return MET
    return UNKNOWN if UNKNOWN in outcomes else NOT_MET


def _rule(rule: dict[str, Any], s: dict[str, Any], points: dict[str, float]) -> tuple[str, str]:
    t = rule["type"]
    if t == "module_completed":
        return (
            (MET, "MODULE_COMPLETED")
            if rule["module"] in s["completed"]
            else (
                NOT_MET,
                "MODULE_NOT_COMPLETED",
            )
        )
    if t == "modules_completed":
        done = all(k in s["completed"] for k in rule["modules"])
        return (MET, "MODULES_COMPLETED") if done else (NOT_MET, "MODULES_NOT_COMPLETED")
    if t == "manual_approval":
        return UNKNOWN, "AWAITING_APPROVAL"
    sub = s["submissions"].get(rule["assignment"])
    if t == "assignment_submitted":
        if sub is None:
            return NOT_MET, "NOT_SUBMITTED"
        if sub.get("excused"):
            return UNKNOWN, "EXCUSED"
        return MET, "SUBMITTED"
    if t == "assignment_score":
        if sub is None:
            return NOT_MET, "NOT_SUBMITTED"
        if sub.get("excused"):
            return UNKNOWN, "EXCUSED"
        if not sub.get("posted", True) or sub.get("score") is None:
            return UNKNOWN, "AWAITING_RELEASE"
        pct = sub["score"] / points[rule["assignment"]] * 100
        return (
            (MET, "SCORE_MET")
            if pct >= rule["threshold_percent"]
            else (
                NOT_MET,
                "SCORE_BELOW_THRESHOLD",
            )
        )
    raise ValueError(f"unknown rule type {t}")


def evaluate_demo(
    rules: dict[str, Any], student: dict[str, Any], points: dict[str, float]
) -> tuple[str, dict[str, Any]]:
    results = [_rule(r, student, points) for r in rules["rules"]]
    outcome = _combine(rules["mode"], [o for o, _ in results])
    return outcome, {
        "mode": rules["mode"],
        "rules": [
            {"position": i, "type": r["type"], "outcome": o, "explanation_code": code}
            for i, (r, (o, code)) in enumerate(zip(rules["rules"], results, strict=True))
        ],
        "source": "dev_seed",
        "note": "Seeded demonstration result. The rules engine recomputes it from snapshots.",
    }
