# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic, explainable rule evaluation (spec §6.1, §6.4).

Three-valued (Kleene) logic:

* ``met``: the data confirms the requirement.
* ``not_met``: the data confirms the requirement is *incomplete* (for example the module is not
  complete yet, or a released mark is below the threshold).
* ``unknown``: the data cannot establish the answer safely (missing, stale, excused,
  unreleased, source changed, awaiting a lecturer). Nothing is ever issued on ``unknown``.

ALL is Kleene AND (any ``not_met`` → ``not_met``, else any ``unknown`` → ``unknown``); ANY is the
dual. The engine is pure: the same rule set and snapshot always give the same result and the
same ``inputs_hash``. ``now`` only enters through staleness flags, which are part of the hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from opencredential.rules.schema import (
    SCHEMA_VERSION,
    AssignmentScore,
    AssignmentSubmitted,
    Group,
    ManualApproval,
    ModuleCompleted,
    ModulesCompleted,
    RuleSet,
)
from opencredential.rules.snapshot import MODULES, SUBMISSIONS, LearnerSnapshot

MET, NOT_MET, UNKNOWN = "met", "not_met", "unknown"

#: Stable explanation codes → learner/staff-facing explanation (actionable where possible).
MESSAGES: dict[str, str] = {
    "MODULE_COMPLETED": "Canvas reports this module as complete.",
    "MODULE_NOT_COMPLETED": "Canvas does not yet report this module as complete.",
    "MODULES_COMPLETED": "Canvas reports every module in this set as complete.",
    "MODULES_NOT_COMPLETED": "Some modules in this set are not complete yet.",
    "MODULE_NOT_FOUND": "This module is no longer in the Canvas course. Course staff need to "
    "update the badge rules.",
    "MODULE_HAS_NO_REQUIREMENTS": "This module has no completion requirements in Canvas, so "
    "Canvas cannot report completion. Course staff need to add requirements in Canvas.",
    "SUBMITTED": "Canvas has a submission for this assignment.",
    "NOT_SUBMITTED": "There is no submission for this assignment yet.",
    "GRADED_WITHOUT_SUBMISSION": "A mark exists but Canvas has no submission. Course staff can "
    "confirm this manually.",
    "ASSIGNMENT_NOT_FOUND": "This assignment is no longer in the Canvas course. Course staff "
    "need to update the badge rules.",
    "ASSIGNMENT_UNPUBLISHED": "This assignment is not published in Canvas.",
    "NO_POINTS_POSSIBLE": "This assignment has no points possible in Canvas, so a percentage "
    "cannot be calculated.",
    "EXCUSED": "This assignment is excused. Course staff can decide on the award manually.",
    "AWAITING_GRADE": "This assignment has not been marked yet.",
    "AWAITING_RELEASE": "Awaiting published result: the mark has not been released.",
    "GRADE_OUTDATED": "The mark is for an earlier submission. Waiting for the current "
    "submission to be marked.",
    "SCORE_MET": "The released mark meets the required score.",
    "SCORE_BELOW_THRESHOLD": "The released mark is below the required score.",
    "AWAITING_APPROVAL": "Waiting for course staff to confirm this requirement.",
    "APPROVED": "A member of staff confirmed this requirement.",
    "APPROVAL_DECLINED": "A member of staff recorded that this requirement is not yet met.",
    "DATA_NOT_SYNCED": "Course data has not been read from Canvas yet.",
    "DATA_UNAVAILABLE": "The last attempt to read this from Canvas failed. It will be retried.",
    "DATA_STALE": "The course data from Canvas is out of date. It will refresh shortly.",
    "RULE_SOURCE_MISSING": "The Canvas item this requirement uses was removed. Awards are "
    "paused until course staff review the badge.",
    "RULE_SOURCE_CHANGED": "The Canvas item this requirement uses has changed. Awards are "
    "paused until course staff review the badge.",
    "GROUP_MET": "Requirements in this group are met.",
    "GROUP_NOT_MET": "Requirements in this group are not met yet.",
    "GROUP_UNKNOWN": "Some requirements in this group cannot be confirmed yet.",
}


@dataclass(frozen=True)
class RuleResult:
    rule_id: str | None
    type: str
    outcome: str
    code: str
    source: dict[str, Any] = field(default_factory=dict)
    children: tuple[RuleResult, ...] = ()

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, self.code)

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "rule_id": self.rule_id,
            "type": self.type,
            "outcome": self.outcome,
            "explanation_code": self.code,
            "message": self.message,
            "source": self.source,
        }
        if self.children:
            d["children"] = [c.as_dict() for c in self.children]
        return d


@dataclass(frozen=True)
class Evaluation:
    outcome: str
    mode: str
    results: tuple[RuleResult, ...]
    inputs_hash: str

    @property
    def completed(self) -> int:
        return sum(1 for r in self.results if r.outcome == MET)

    @property
    def total(self) -> int:
        return len(self.results)

    def pending_codes(self) -> list[str]:
        return [r.code for r in _flatten(self.results) if r.outcome == UNKNOWN]

    def as_detail(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "outcome": self.outcome,
            "progress": {"completed": self.completed, "total": self.total},
            "rules": [r.as_dict() for r in self.results],
        }


def _flatten(results: tuple[RuleResult, ...]) -> list[RuleResult]:
    out: list[RuleResult] = []
    for r in results:
        out.append(r)
        out.extend(_flatten(r.children))
    return out


def combine(mode: str, outcomes: list[str]) -> str:
    if mode == "ALL":
        if NOT_MET in outcomes:
            return NOT_MET
        return UNKNOWN if UNKNOWN in outcomes else MET
    if mode == "ANY":
        if MET in outcomes:
            return MET
        return UNKNOWN if UNKNOWN in outcomes else NOT_MET
    raise ValueError(f"unknown mode {mode!r}")


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


# ---- leaves -------------------------------------------------------------------------------


def _module_state(mid: str, s: LearnerSnapshot) -> tuple[str, str, dict[str, Any]]:
    src: dict[str, Any] = {"kind": "canvas_module_progress", "canvas_module_id": mid}
    if MODULES in s.unavailable:
        return UNKNOWN, "DATA_UNAVAILABLE", src
    mod = s.modules.get(mid)
    if mod is None:
        return UNKNOWN, ("DATA_NOT_SYNCED" if s.synced_at is None else "MODULE_NOT_FOUND"), src
    src["module_name"] = mod.name
    if mod.workflow_state == "deleted":
        return UNKNOWN, "MODULE_NOT_FOUND", src
    if not mod.has_requirements:
        return UNKNOWN, "MODULE_HAS_NO_REQUIREMENTS", src
    prog = s.module_progress.get(mid)
    fetched = prog.fetched_at if prog else mod.fetched_at
    src["fetched_at"] = _iso(fetched)
    src["state"] = prog.state if prog else None
    src["completed_at"] = _iso(prog.completed_at) if prog else None
    if s.is_stale(fetched):
        return UNKNOWN, "DATA_STALE", src
    if prog is not None and prog.state == "completed":
        return MET, "MODULE_COMPLETED", src
    return NOT_MET, "MODULE_NOT_COMPLETED", src


def _assignment_common(
    aid: str, s: LearnerSnapshot
) -> tuple[str, str, dict[str, Any]] | tuple[None, None, dict[str, Any]]:
    src: dict[str, Any] = {"kind": "canvas_submission", "canvas_assignment_id": aid}
    if SUBMISSIONS in s.unavailable:
        return UNKNOWN, "DATA_UNAVAILABLE", src
    a = s.assignments.get(aid)
    if a is None:
        return UNKNOWN, ("DATA_NOT_SYNCED" if s.synced_at is None else "ASSIGNMENT_NOT_FOUND"), src
    src["assignment_name"] = a.name
    if a.deleted:
        return UNKNOWN, "ASSIGNMENT_NOT_FOUND", src
    if not a.published:
        return UNKNOWN, "ASSIGNMENT_UNPUBLISHED", src
    sub = s.submissions.get(aid)
    fetched = sub.fetched_at if sub else a.fetched_at
    src["fetched_at"] = _iso(fetched)
    if sub is not None:
        src.update(
            workflow_state=sub.workflow_state,
            submitted_at=_iso(sub.submitted_at),
            excused=sub.excused,
            posted=sub.posted_at is not None,
        )
    if s.is_stale(fetched):
        return UNKNOWN, "DATA_STALE", src
    return None, None, src


def _submitted(rule: AssignmentSubmitted, s: LearnerSnapshot) -> tuple[str, str, dict[str, Any]]:
    outcome, code, src = _assignment_common(rule.assignment_id, s)
    if outcome is not None and code is not None:
        return outcome, code, src
    sub = s.submissions.get(rule.assignment_id)
    if sub is None:
        return NOT_MET, "NOT_SUBMITTED", src
    if sub.excused:
        return UNKNOWN, "EXCUSED", src
    if sub.submitted_at is not None:
        return MET, "SUBMITTED", src
    if sub.workflow_state == "graded":
        return UNKNOWN, "GRADED_WITHOUT_SUBMISSION", src
    return NOT_MET, "NOT_SUBMITTED", src


def _score(rule: AssignmentScore, s: LearnerSnapshot) -> tuple[str, str, dict[str, Any]]:
    outcome, code, src = _assignment_common(rule.assignment_id, s)
    if outcome is not None and code is not None:
        return outcome, code, src
    a = s.assignments[rule.assignment_id]
    src["threshold_percent"] = rule.threshold_percent
    if not a.points_possible or a.points_possible <= 0:
        return UNKNOWN, "NO_POINTS_POSSIBLE", src
    sub = s.submissions.get(rule.assignment_id)
    if sub is None:
        return NOT_MET, "NOT_SUBMITTED", src
    if sub.excused:
        return UNKNOWN, "EXCUSED", src
    if sub.score is None or sub.workflow_state != "graded":
        if sub.submitted_at is None and sub.workflow_state == "unsubmitted":
            return NOT_MET, "NOT_SUBMITTED", src
        return UNKNOWN, "AWAITING_GRADE", src
    if sub.posted_at is None:
        # Never record the unreleased mark itself (it is not yet the learner's result).
        return UNKNOWN, "AWAITING_RELEASE", src
    if not sub.grade_matches_current_submission:
        return UNKNOWN, "GRADE_OUTDATED", src
    # Exact decimal comparison: score / points * 100 >= threshold.
    score = Decimal(str(sub.score))
    points = Decimal(str(a.points_possible))
    pct = score * 100 / points
    src["score_percent"] = float(round(pct, 2))
    if pct >= Decimal(str(rule.threshold_percent)):
        return MET, "SCORE_MET", src
    return NOT_MET, "SCORE_BELOW_THRESHOLD", src


def _manual(rule: ManualApproval, s: LearnerSnapshot) -> tuple[str, str, dict[str, Any]]:
    src: dict[str, Any] = {"kind": "manual_approval"}
    appr = s.approvals.get(rule.id or "")
    if appr is None:
        return UNKNOWN, "AWAITING_APPROVAL", src
    src.update(decided_at=_iso(appr.decided_at), decided_by=appr.decided_by)
    if appr.decision == "approve":
        return MET, "APPROVED", src
    return NOT_MET, "APPROVAL_DECLINED", src


def _leaf(rule: Any, s: LearnerSnapshot) -> RuleResult:
    flag = s.rule_source_status.get(rule.id or "", "ok")
    if flag != "ok":
        code = "RULE_SOURCE_MISSING" if flag == "source_missing" else "RULE_SOURCE_CHANGED"
        return RuleResult(rule.id, rule.type, UNKNOWN, code, {"kind": "rule_source"})
    if isinstance(rule, ModuleCompleted):
        o, c, src = _module_state(rule.module_id, s)
        return RuleResult(rule.id, rule.type, o, c, src)
    if isinstance(rule, ModulesCompleted):
        parts = [(mid, *_module_state(mid, s)) for mid in rule.module_ids]
        outcome = combine("ALL", [p[1] for p in parts])
        done = sum(1 for p in parts if p[1] == MET)
        if outcome == MET:
            code = "MODULES_COMPLETED"
        elif outcome == NOT_MET:
            code = "MODULES_NOT_COMPLETED"
        else:
            code = next(p[2] for p in parts if p[1] == UNKNOWN)
        src = {
            "kind": "canvas_module_progress",
            "completed": done,
            "total": len(parts),
            "modules": [{"canvas_module_id": p[0], "outcome": p[1], **p[3]} for p in parts],
        }
        return RuleResult(rule.id, rule.type, outcome, code, src)
    if isinstance(rule, AssignmentSubmitted):
        o, c, src = _submitted(rule, s)
        return RuleResult(rule.id, rule.type, o, c, src)
    if isinstance(rule, AssignmentScore):
        o, c, src = _score(rule, s)
        return RuleResult(rule.id, rule.type, o, c, src)
    if isinstance(rule, ManualApproval):
        o, c, src = _manual(rule, s)
        return RuleResult(rule.id, rule.type, o, c, src)
    raise TypeError(f"unsupported rule {type(rule).__name__}")


def _rule(rule: Any, s: LearnerSnapshot) -> RuleResult:
    if isinstance(rule, Group):
        children = tuple(_leaf(r, s) for r in rule.rules)
        outcome = combine(rule.mode, [c.outcome for c in children])
        code = {MET: "GROUP_MET", NOT_MET: "GROUP_NOT_MET", UNKNOWN: "GROUP_UNKNOWN"}[outcome]
        return RuleResult(rule.id, "group", outcome, code, {"mode": rule.mode}, children)
    return _leaf(rule, s)


def _without_fetch_times(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_fetch_times(v) for k, v in value.items() if k != "fetched_at"}
    if isinstance(value, list):
        return [_without_fetch_times(v) for v in value]
    return value


def _hash(rule_set: RuleSet, results: tuple[RuleResult, ...]) -> str:
    """Hash of the rules and the *values* they used. Fetch times are left out, so re-reading
    unchanged Canvas data gives the same hash (staleness still shows up as ``DATA_STALE``)."""
    payload = {
        "rules": rule_set.model_dump(mode="json"),
        "results": [_without_fetch_times(r.as_dict()) for r in results],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def evaluate(rule_set: RuleSet, snapshot: LearnerSnapshot) -> Evaluation:
    """Evaluate ``rule_set`` for one learner. Pure and deterministic."""
    results = tuple(_rule(r, snapshot) for r in rule_set.rules)
    outcome = combine(rule_set.mode, [r.outcome for r in results])
    return Evaluation(
        outcome=outcome,
        mode=rule_set.mode,
        results=results,
        inputs_hash=_hash(rule_set, results),
    )
