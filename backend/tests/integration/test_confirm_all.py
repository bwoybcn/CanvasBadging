# SPDX-License-Identifier: AGPL-3.0-or-later
"""Confirming every waiting award at once (product review, 14 Nov 2026).

Score-based badges default to "staff confirm each award", and the page had one button per
student: a cohort of 200 was 200 clicks. ``POST /api/v1/awards/confirm-all`` confirms a list of
waiting awards. Each one still gets the checks of a single confirm, and one that fails is left
waiting with its reason while the rest go through.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.integrations import registry
from opencredential.settings import get_settings
from tests.integration.w5_world import COURSE_REF, World, build_world

pytestmark = pytest.mark.db

SCORE_RULES = {
    "mode": "ALL",
    "rules": [
        {"type": "module_completed", "module_id": "m1"},
        {"type": "assignment_score", "assignment_id": "a1", "threshold_percent": 70},
    ],
}
ISSUE = "oc:issue_credential"
ALL = "/api/v1/awards/confirm-all"


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    w = build_world(client)
    with registry.override(w.lms):
        yield w


def _three_waiting(world: World) -> dict[str, str]:
    """Three students pass a score badge that staff must confirm; returns award id by student."""
    world.sync()
    world.publish(SCORE_RULES)
    for s in ("s1", "s2", "s3"):
        world.lms.complete_module(COURSE_REF, f"lms-{s}", "m1")
        world.lms.set_submission(
            COURSE_REF,
            f"lms-{s}",
            "a1",
            workflow_state="graded",
            score=15.0,
            posted_at=datetime.now(UTC),
        )
    world.sync_and_evaluate()
    by_user = {str(d.user_id): str(d.id) for d in world.decisions()}
    assert len(by_user) == 3
    return {s: by_user[str(world.users[s])] for s in ("s1", "s2", "s3")}


def test_confirms_everyone_who_still_qualifies_and_leaves_the_rest(world: World) -> None:
    ids = _three_waiting(world)
    # One mark is lowered after the award started waiting.
    world.lms.set_submission(COURSE_REF, "lms-s3", "a1", score=10.0)
    world.sync()

    r = world.post("lecturer", ALL, {"decision_ids": list(ids.values())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["confirmed"], body["left"]) == (2, 1)
    rows = {row["id"]: row for row in body["rows"]}
    assert rows[ids["s1"]]["confirmed"] and rows[ids["s2"]]["confirmed"]
    left = rows[ids["s3"]]
    assert left["confirmed"] is False and left["code"] == "ELIGIBILITY_CHANGED"
    assert left["message"] and left["learner_name"] and left["badge_title"]

    # Two credentials are requested; the third award is still waiting, untouched.
    assert len(world.jobs(ISSUE)) == 2
    waiting = world.get("lecturer", "/api/v1/awards").json()
    assert [w["id"] for w in waiting] == [ids["s3"]]

    # Doing it again changes nothing (a double click, or two colleagues at once).
    again = world.post("lecturer", ALL, {"decision_ids": list(ids.values())}).json()
    assert (again["confirmed"], again["left"]) == (2, 1)
    assert len(world.jobs(ISSUE)) == 2


def test_only_staff_who_could_confirm_one_can_confirm_all(world: World) -> None:
    ids = _three_waiting(world)
    for who in ("outsider", "s1"):
        r = world.post(who, ALL, {"decision_ids": list(ids.values())})
        # Nothing is confirmed and nothing about the awards is given away.
        assert r.status_code == 200 and r.json() == {"confirmed": 0, "left": 0, "rows": []}
    assert world.jobs(ISSUE) == []
    assert len(world.get("lecturer", "/api/v1/awards").json()) == 3


def test_unknown_awards_are_skipped_and_the_list_has_limits(world: World) -> None:
    ids = _three_waiting(world)
    r = world.post("lecturer", ALL, {"decision_ids": [str(uuid.uuid4()), ids["s1"], ids["s1"]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confirmed"] == 1 and [row["id"] for row in body["rows"]] == [ids["s1"]]

    assert world.post("lecturer", ALL, {"decision_ids": []}).status_code == 422
    too_many = [str(uuid.uuid4()) for _ in range(501)]
    r = world.post("lecturer", ALL, {"decision_ids": too_many})
    assert r.status_code == 422
    assert r.json()["errors"][0]["limits"]["max_length"] == 500


def test_a_manual_award_is_never_swept_up_with_the_rest(client: TestClient) -> None:
    w = build_world(client, policy={"manual_awards_require_second_approval": True})
    with registry.override(w.lms):
        badge = w.publish(
            {"mode": "ALL", "rules": [{"type": "manual_approval"}]},
            category="Participation",
            demonstration_kind="participating",
            award_policy="manual",
        )["id"]
        manual = w.post(
            "lecturer",
            "/api/v1/awards/manual",
            {
                "definition_id": badge,
                "user_id": str(w.users["s1"]),
                "justification": "Led the group presentation preparation sessions.",
            },
        ).json()
        assert manual["status"] == "awaiting_confirmation"

        # A second approver reads the justification first, so "confirm all" leaves it waiting.
        r = w.post("reviewer", ALL, {"decision_ids": [manual["id"]]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["confirmed"], body["left"]) == (0, 1)
        assert body["rows"][0]["code"] == "CONFIRM_ONE_AT_A_TIME"
        assert w.jobs(ISSUE) == []
        # Someone with no say over the badge is told nothing about it.
        assert w.post("outsider", ALL, {"decision_ids": [manual["id"]]}).json()["rows"] == []
        # On its own it still goes through.
        one = w.post("reviewer", f"/api/v1/awards/{manual['id']}/confirm", {})
        assert one.json()["status"] == "ready" and len(w.jobs(ISSUE)) == 1
