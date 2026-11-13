# SPDX-License-Identifier: AGPL-3.0-or-later
"""The seed oracle follows the three-valued semantics in architecture.md §5."""

from hypothesis import given
from hypothesis import strategies as st

from opencredential.seed.expected import MET, NOT_MET, UNKNOWN, _combine, evaluate_demo

outcomes = st.lists(st.sampled_from([MET, NOT_MET, UNKNOWN]), min_size=1, max_size=6)


@given(outcomes)
def test_all_is_kleene_and(xs: list[str]) -> None:
    expected = NOT_MET if NOT_MET in xs else UNKNOWN if UNKNOWN in xs else MET
    assert _combine("ALL", xs) == expected


@given(outcomes)
def test_any_is_kleene_or(xs: list[str]) -> None:
    expected = MET if MET in xs else UNKNOWN if UNKNOWN in xs else NOT_MET
    assert _combine("ANY", xs) == expected


POINTS = {"a": 20.0}
SCORE = {
    "mode": "ALL",
    "rules": [
        {"type": "assignment_score", "assignment": "a", "operator": ">=", "threshold_percent": 60}
    ],
}


def _student(sub: dict | None) -> dict:
    return {"completed": [], "submissions": {"a": sub} if sub is not None else {}}


def test_unreleased_grade_is_unknown_not_met() -> None:
    outcome, detail = evaluate_demo(SCORE, _student({"score": 19, "posted": False}), POINTS)
    assert outcome == UNKNOWN
    assert detail["rules"][0]["explanation_code"] == "AWAITING_RELEASE"


def test_excused_is_unknown() -> None:
    assert evaluate_demo(SCORE, _student({"excused": True}), POINTS)[0] == UNKNOWN


def test_threshold_is_inclusive() -> None:
    assert evaluate_demo(SCORE, _student({"score": 12}), POINTS)[0] == MET
    assert evaluate_demo(SCORE, _student({"score": 11.9}), POINTS)[0] == NOT_MET


def test_missing_submission_is_not_met() -> None:
    assert evaluate_demo(SCORE, _student(None), POINTS)[0] == NOT_MET
