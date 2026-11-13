# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rules engine: semantics, explanations, determinism and agreement with the seed oracle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from opencredential.rules import MET, NOT_MET, UNKNOWN, evaluate, parse
from opencredential.rules.engine import combine
from opencredential.rules.snapshot import (
    MODULES,
    SUBMISSIONS,
    Approval,
    AssignmentInfo,
    LearnerSnapshot,
    ModuleInfo,
    ModuleProgress,
    Submission,
)
from opencredential.seed import load_passport
from opencredential.seed.expected import evaluate_demo

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
FRESH = NOW - timedelta(minutes=5)


def snap(**kw) -> LearnerSnapshot:  # type: ignore[no-untyped-def]
    base = {
        "learner_ref": "u1",
        "now": NOW,
        "max_age": timedelta(hours=2),
        "synced_at": FRESH,
        "modules": {"m1": ModuleInfo("m1", "Module 1", "active", True, FRESH)},
        "assignments": {"a1": AssignmentInfo("a1", "Essay", 20.0, True, False, FRESH)},
    }
    base.update(kw)
    return LearnerSnapshot(**base)


def sub(**kw) -> Submission:  # type: ignore[no-untyped-def]
    base = {
        "assignment_id": "a1",
        "workflow_state": "graded",
        "submitted_at": FRESH - timedelta(days=1),
        "score": 15.0,
        "excused": False,
        "posted_at": FRESH,
        "grade_matches_current_submission": True,
        "missing": False,
        "fetched_at": FRESH,
    }
    base.update(kw)
    return Submission(**base)


MOD = parse({"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]})
SCORE = parse(
    {
        "mode": "ALL",
        "rules": [{"type": "assignment_score", "assignment_id": "a1", "threshold_percent": 70}],
    }
)
SUBMIT = parse({"mode": "ALL", "rules": [{"type": "assignment_submitted", "assignment_id": "a1"}]})


def code(ev) -> str:  # type: ignore[no-untyped-def]
    return ev.results[0].code


# ---- schema --------------------------------------------------------------------------------


def test_spec_example_parses() -> None:
    rs = parse(
        {
            "mode": "ALL",
            "rules": [
                {"type": "module_completed", "module_id": "12345"},
                {
                    "type": "assignment_score",
                    "assignment_id": "67890",
                    "operator": ">=",
                    "threshold_percent": 70,
                },
            ],
        }
    )
    assert rs.has_score_rule() and rs.module_ids() == {"12345"}


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "ALL", "rules": []},
        {"mode": "XOR", "rules": [{"type": "manual_approval"}]},
        {"mode": "ALL", "rules": [{"type": "module_completed"}]},
        {"mode": "ALL", "rules": [{"type": "assignment_score", "assignment_id": "1"}]},
        {
            "mode": "ALL",
            "rules": [{"type": "assignment_score", "assignment_id": "1", "threshold_percent": 101}],
        },
        {"mode": "ALL", "rules": [{"type": "modules_completed", "module_ids": ["1", "1"]}]},
        {"mode": "ALL", "rules": [{"type": "unknown_type"}]},
        # nesting deeper than one group level is refused
        {
            "mode": "ALL",
            "rules": [
                {
                    "type": "group",
                    "mode": "ANY",
                    "rules": [
                        {
                            "type": "group",
                            "mode": "ALL",
                            "rules": [{"type": "manual_approval"}, {"type": "manual_approval"}],
                        },
                        {"type": "manual_approval"},
                    ],
                }
            ],
        },
        {"mode": "ALL", "rules": [{"type": "manual_approval", "surprise": 1}]},
    ],
)
def test_invalid_rule_sets_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        parse(bad)


# ---- module completion (A, B) ----------------------------------------------------------------


def test_module_completed() -> None:
    s = snap(module_progress={"m1": ModuleProgress("m1", "completed", FRESH, FRESH)})
    ev = evaluate(MOD, s)
    assert ev.outcome == MET and code(ev) == "MODULE_COMPLETED"
    assert ev.results[0].source["canvas_module_id"] == "m1"
    assert ev.results[0].source["fetched_at"] == FRESH.isoformat()


def test_module_incomplete_is_not_met_not_unknown() -> None:
    s = snap(module_progress={"m1": ModuleProgress("m1", "started", None, FRESH)})
    assert evaluate(MOD, s).outcome == NOT_MET
    assert evaluate(MOD, snap()).outcome == NOT_MET  # no progress row for a known module


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"modules": {}}, "MODULE_NOT_FOUND"),
        ({"modules": {}, "synced_at": None}, "DATA_NOT_SYNCED"),
        (
            {"modules": {"m1": ModuleInfo("m1", "M", "active", False, FRESH)}},
            "MODULE_HAS_NO_REQUIREMENTS",
        ),
        ({"modules": {"m1": ModuleInfo("m1", "M", "deleted", True, FRESH)}}, "MODULE_NOT_FOUND"),
        ({"unavailable": frozenset({MODULES})}, "DATA_UNAVAILABLE"),
        (
            {
                "module_progress": {
                    "m1": ModuleProgress("m1", "completed", FRESH, NOW - timedelta(hours=3))
                }
            },
            "DATA_STALE",
        ),
        ({"rule_source_status": {"r1": "source_missing"}}, "RULE_SOURCE_MISSING"),
    ],
)
def test_module_unknown_states(kw: dict, expected: str) -> None:
    rs = parse(
        {"mode": "ALL", "rules": [{"id": "r1", "type": "module_completed", "module_id": "m1"}]}
    )
    ev = evaluate(rs, snap(**kw))
    assert ev.outcome == UNKNOWN and code(ev) == expected


def test_multiple_modules() -> None:
    rs = parse(
        {"mode": "ALL", "rules": [{"type": "modules_completed", "module_ids": ["m1", "m2"]}]}
    )
    mods = {
        "m1": ModuleInfo("m1", "One", "active", True, FRESH),
        "m2": ModuleInfo("m2", "Two", "active", True, FRESH),
    }
    one = {"m1": ModuleProgress("m1", "completed", FRESH, FRESH)}
    both = one | {"m2": ModuleProgress("m2", "completed", FRESH, FRESH)}
    ev = evaluate(rs, snap(modules=mods, module_progress=one))
    assert ev.outcome == NOT_MET and ev.results[0].source["completed"] == 1
    assert evaluate(rs, snap(modules=mods, module_progress=both)).outcome == MET
    gone = {"m1": mods["m1"]}
    assert evaluate(rs, snap(modules=gone, module_progress=both)).outcome == UNKNOWN


# ---- submission (C) ------------------------------------------------------------------------


def test_submission_states() -> None:
    assert evaluate(SUBMIT, snap()).outcome == NOT_MET
    assert (
        evaluate(
            SUBMIT,
            snap(submissions={"a1": sub(workflow_state="submitted", score=None, posted_at=None)}),
        ).outcome
        == MET
    )
    unsub = sub(workflow_state="unsubmitted", submitted_at=None, score=None, posted_at=None)
    assert evaluate(SUBMIT, snap(submissions={"a1": unsub})).outcome == NOT_MET
    excused = sub(excused=True, submitted_at=None)
    ev = evaluate(SUBMIT, snap(submissions={"a1": excused}))
    assert ev.outcome == UNKNOWN and code(ev) == "EXCUSED"
    paper = sub(submitted_at=None)
    assert code(evaluate(SUBMIT, snap(submissions={"a1": paper}))) == "GRADED_WITHOUT_SUBMISSION"
    ev = evaluate(SUBMIT, snap(unavailable=frozenset({SUBMISSIONS})))
    assert ev.outcome == UNKNOWN and code(ev) == "DATA_UNAVAILABLE"


# ---- score (D) -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("submission", "outcome", "expected"),
    [
        (sub(score=14.0), MET, "SCORE_MET"),  # exactly 70% is enough
        (sub(score=13.99), NOT_MET, "SCORE_BELOW_THRESHOLD"),
        (sub(posted_at=None), UNKNOWN, "AWAITING_RELEASE"),
        (sub(score=None, workflow_state="submitted", posted_at=None), UNKNOWN, "AWAITING_GRADE"),
        (sub(excused=True), UNKNOWN, "EXCUSED"),
        (sub(grade_matches_current_submission=False), UNKNOWN, "GRADE_OUTDATED"),
        (
            sub(workflow_state="unsubmitted", submitted_at=None, score=None, posted_at=None),
            NOT_MET,
            "NOT_SUBMITTED",
        ),
        (sub(fetched_at=NOW - timedelta(hours=5)), UNKNOWN, "DATA_STALE"),
    ],
)
def test_score_rule(submission: Submission, outcome: str, expected: str) -> None:
    ev = evaluate(SCORE, snap(submissions={"a1": submission}))
    assert (ev.outcome, code(ev)) == (outcome, expected)


def test_unreleased_mark_is_not_recorded() -> None:
    ev = evaluate(SCORE, snap(submissions={"a1": sub(posted_at=None)}))
    assert "score_percent" not in ev.results[0].source


def test_score_needs_points_possible() -> None:
    a = {"a1": AssignmentInfo("a1", "Essay", 0.0, True, False, FRESH)}
    ev = evaluate(SCORE, snap(assignments=a, submissions={"a1": sub()}))
    assert (ev.outcome, code(ev)) == (UNKNOWN, "NO_POINTS_POSSIBLE")


def test_decimal_threshold_has_no_float_error() -> None:
    rs = parse(
        {
            "mode": "ALL",
            "rules": [{"type": "assignment_score", "assignment_id": "a1", "threshold_percent": 70}],
        }
    )
    a = {"a1": AssignmentInfo("a1", "Quiz", 3.0, True, False, FRESH)}
    # 2.1 / 3 * 100 is 69.99999999999999 in binary floating point.
    assert evaluate(rs, snap(assignments=a, submissions={"a1": sub(score=2.1)})).outcome == MET


# ---- manual (E) and combinations (F) ----------------------------------------------------------


def test_manual_approval() -> None:
    rs = parse({"mode": "ALL", "rules": [{"id": "r9", "type": "manual_approval"}]})
    assert code(evaluate(rs, snap())) == "AWAITING_APPROVAL"
    ok = {"r9": Approval("r9", "approve", FRESH, "lecturer")}
    no = {"r9": Approval("r9", "decline", FRESH, "lecturer")}
    assert evaluate(rs, snap(approvals=ok)).outcome == MET
    assert evaluate(rs, snap(approvals=no)).outcome == NOT_MET


def test_nested_group() -> None:
    rs = parse(
        {
            "mode": "ALL",
            "rules": [
                {"type": "module_completed", "module_id": "m1"},
                {
                    "type": "group",
                    "mode": "ANY",
                    "rules": [
                        {"type": "assignment_submitted", "assignment_id": "a1"},
                        {"id": "r2", "type": "manual_approval"},
                    ],
                },
            ],
        }
    )
    done = {"m1": ModuleProgress("m1", "completed", FRESH, FRESH)}
    ev = evaluate(rs, snap(module_progress=done))
    assert ev.outcome == UNKNOWN  # not submitted, approval pending
    assert ev.results[1].children[0].outcome == NOT_MET
    approved = {"r2": Approval("r2", "approve", FRESH, "x")}
    assert evaluate(rs, snap(module_progress=done, approvals=approved)).outcome == MET
    assert ev.completed == 1 and ev.total == 2


outcomes = st.lists(st.sampled_from([MET, NOT_MET, UNKNOWN]), min_size=1, max_size=6)


@given(outcomes)
def test_combine_is_kleene(xs: list[str]) -> None:
    assert combine("ALL", xs) == (NOT_MET if NOT_MET in xs else UNKNOWN if UNKNOWN in xs else MET)
    assert combine("ANY", xs) == (MET if MET in xs else UNKNOWN if UNKNOWN in xs else NOT_MET)


@given(st.floats(min_value=0, max_value=20), st.floats(min_value=1, max_value=100))
def test_never_met_without_release(score: float, threshold: float) -> None:
    rs = parse(
        {
            "mode": "ALL",
            "rules": [
                {"type": "assignment_score", "assignment_id": "a1", "threshold_percent": threshold}
            ],
        }
    )
    assert evaluate(rs, snap(submissions={"a1": sub(score=score, posted_at=None)})).outcome != MET


def test_deterministic_hash() -> None:
    s = snap(submissions={"a1": sub()})
    a, b = evaluate(SCORE, s), evaluate(SCORE, s)
    assert a.inputs_hash == b.inputs_hash
    changed = evaluate(SCORE, snap(submissions={"a1": sub(score=10.0)}))
    assert changed.inputs_hash != a.inputs_hash
    assert a.as_detail()["progress"] == {"completed": 1, "total": 1}


# ---- agreement with the W2 seed oracle ----------------------------------------------------------


def _passport_snapshot(student: dict, data: dict) -> LearnerSnapshot:
    """Mirror of how seed/__init__.py writes LMS rows, using seed keys as Canvas ids."""
    modules = {
        m["key"]: ModuleInfo(m["key"], m["name"], "active", True, FRESH) for m in data["modules"]
    }
    progress = {k: ModuleProgress(k, "completed", FRESH, FRESH) for k in student["completed"]}
    assignments = {
        a["key"]: AssignmentInfo(a["key"], a["name"], a["points_possible"], True, False, FRESH)
        for a in data["assignments"]
    }
    subs = {}
    for k, s in student["submissions"].items():
        excused = s.get("excused", False)
        graded = s.get("score") is not None or excused
        posted = s.get("posted", True) and not excused
        subs[k] = Submission(
            k,
            "graded" if graded else "submitted",
            None if excused else FRESH,
            s.get("score"),
            excused,
            FRESH if posted and graded else None,
            True,
            False,
            FRESH,
        )
    return snap(
        modules=modules, module_progress=progress, assignments=assignments, submissions=subs
    )


def _engine_rules(rules: dict) -> dict:
    out = []
    for r in rules["rules"]:
        r2 = {k: v for k, v in r.items() if k not in ("module", "modules", "assignment")}
        if "module" in r:
            r2["module_id"] = r["module"]
        if "modules" in r:
            r2["module_ids"] = r["modules"]
        if "assignment" in r:
            r2["assignment_id"] = r["assignment"]
        out.append(r2)
    return {"mode": rules["mode"], "rules": out}


def test_engine_agrees_with_seed_oracle_for_every_learner_and_badge() -> None:
    data = load_passport()
    points = {a["key"]: a["points_possible"] for a in data["assignments"]}
    checked = 0
    for student in data["students"]:
        s = _passport_snapshot(student, data)
        for badge in data["badges"]:
            expected, _ = evaluate_demo(badge["rules"], student, points)
            got = evaluate(parse(_engine_rules(badge["rules"])), s).outcome
            assert got == expected, (student["given_name"], badge["title"])
            checked += 1
    assert checked == 108
