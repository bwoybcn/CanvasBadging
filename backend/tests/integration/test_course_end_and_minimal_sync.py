# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read less from Canvas, and stop reading a course after it ends (whole-product review,
finding 2).

* Submissions and marks are read and kept only for assignments a live badge rule uses.
* A mark Canvas has not released to the student is never stored.
* A course that ended in Canvas is read for a while longer (late marks still count), then
  archived; its snapshots are deleted a set time after it ended.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import owner_session
from opencredential.integrations import registry
from opencredential.integrations.base import CourseStateRecord, LmsPermissionError
from opencredential.jobs import tasks
from opencredential.settings import get_settings
from tests.integration.w5_world import COURSE_REF, World, build_world

pytestmark = pytest.mark.db

SCORE_A1 = {
    "mode": "ALL",
    "rules": [{"type": "assignment_score", "assignment_id": "a1", "threshold_percent": 70}],
}
SUBMIT_A1 = {"mode": "ALL", "rules": [{"type": "assignment_submitted", "assignment_id": "a1"}]}
MODULE_M1 = {"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]}


@pytest.fixture
def world(database: None, tmp_path: Path) -> Iterator[World]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        w = build_world(c)
        w.lms.add_assignment(COURSE_REF, "a2", "Reflective journal", points_possible=10.0)
        # Every test world uses the same Canvas course id. Give this one its own, so that
        # "this course has ended" is not also said about courses other tests left behind.
        w.ref = f"course-{uuid.uuid4().hex[:8]}"  # type: ignore[attr-defined]
        w.lms.courses[w.ref] = w.lms.courses.pop(COURSE_REF)
        with owner_session() as db:
            course = db.get(m.Course, w.course_id)
            assert course is not None
            course.canvas_course_id = w.ref
        with registry.override(w.lms):
            yield w


def _submissions(w: World) -> dict[tuple[str, str], m.LmsSubmission]:
    names = {uid: key for key, uid in w.users.items()}
    with w.db() as db:
        rows = db.scalars(select(m.LmsSubmission).where(m.LmsSubmission.course_id == w.course_id))
        return {(names[s.user_id], s.canvas_assignment_id): s for s in rows}


def _synced(w: World) -> dict[str, bool]:
    with w.db() as db:
        rows = db.scalars(select(m.LmsAssignment).where(m.LmsAssignment.course_id == w.course_id))
        return {a.canvas_assignment_id: a.submissions_synced for a in rows}


def _course(w: World) -> m.Course:
    with w.db() as db:
        course = db.get(m.Course, w.course_id)
        assert course is not None
        db.expunge(course)
        return course


def _reason(w: World, user: str) -> str:
    return str(w.evaluations(user)[-1].detail["rules"][0]["explanation_code"])


def _audit(w: World) -> list[str]:
    with w.db() as db:
        return list(db.scalars(select(m.AuditEvent.action).order_by(m.AuditEvent.at)))


# ---- only what a badge needs -----------------------------------------------------------------


def test_only_assignments_a_live_badge_uses_have_submissions_read_and_kept(world: World) -> None:
    w = world
    asked: list[list[str]] = []
    real = w.lms.list_submissions

    def spy(course_ref: str, assignment_ids: Any, lms_user_ids: Any) -> Any:
        asked.append(sorted(assignment_ids))
        return real(course_ref, assignment_ids, lms_user_ids)

    w.lms.list_submissions = spy  # type: ignore[method-assign]
    for aid in ("a1", "a2"):
        w.lms.set_submission(
            w.ref,
            "lms-s1",
            aid,
            workflow_state="graded",
            score=9.0,
            posted_at=datetime.now(UTC),
        )
    w.publish(SCORE_A1, award_policy="lecturer_confirmed")
    w.sync()

    # Canvas was asked for the essay only, and only the essay's submissions are held.
    assert asked == [["a1"]]
    assert {aid for _, aid in _submissions(w)} == {"a1"}
    # The journal is still listed for the badge editor, with no student data behind it.
    assert _synced(w) == {"a1": True, "a2": False}
    r = w.get("lecturer", f"/api/v1/courses/{w.course_id}/canvas/assignments")
    assert {a["id"] for a in r.json()["items"]} == {"a1", "a2"}


def test_a_course_with_no_assignment_rules_reads_no_submissions_at_all(world: World) -> None:
    w = world
    w.lms.set_submission(w.ref, "lms-s1", "a1", workflow_state="submitted")
    w.publish(MODULE_M1)
    w.sync()
    assert ("submissions",) not in w.lms.calls
    assert _submissions(w) == {}
    assert _synced(w) == {"a1": False, "a2": False}


def test_an_unreleased_mark_is_never_stored(world: World) -> None:
    w = world
    w.lms.set_submission(w.ref, "lms-s1", "a1", workflow_state="graded", score=18.0, posted_at=None)
    w.publish(SCORE_A1, award_policy="lecturer_confirmed")
    w.sync_and_evaluate()
    held = _submissions(w)[("s1", "a1")]
    assert held.score is None and held.workflow_state == "graded" and held.posted_at is None
    # The student still gets the right explanation: marked, not yet released.
    assert _reason(w, "s1") == "AWAITING_RELEASE"

    # Once the lecturer releases the mark in Canvas it is stored and counts.
    w.lms.set_submission(w.ref, "lms-s1", "a1", posted_at=datetime.now(UTC))
    w.sync_and_evaluate()
    assert _submissions(w)[("s1", "a1")].score == 18.0
    assert _reason(w, "s1") == "SCORE_MET"


def test_submissions_are_deleted_once_no_badge_uses_the_assignment(world: World) -> None:
    w = world
    w.lms.set_submission(w.ref, "lms-s1", "a1", workflow_state="submitted")
    did = w.publish(SUBMIT_A1)["id"]
    w.sync()
    assert ("s1", "a1") in _submissions(w)

    # The badge is archived, so nothing reads that assignment any more. The course is no
    # longer synced for it; the daily retention job removes what was held.
    assert w.post("lecturer", f"/api/v1/achievements/{did}/archive").status_code == 200
    r = w.post("admin", "/api/v1/admin/retention/run")
    assert r.status_code == 200, r.text
    assert r.json()["unused_submissions"] == 3  # one row per student
    assert _submissions(w) == {}
    assert _synced(w)["a1"] is False


def test_a_sync_drops_submissions_for_assignments_no_longer_used(world: World) -> None:
    w = world
    w.lms.set_submission(w.ref, "lms-s1", "a1", workflow_state="submitted")
    did = w.publish(SUBMIT_A1)["id"]
    w.publish(MODULE_M1, title="Writing module complete")
    w.sync()
    assert ("s1", "a1") in _submissions(w)
    assert w.post("lecturer", f"/api/v1/achievements/{did}/archive").status_code == 200
    w.sync()  # the module badge keeps the course syncing
    assert _submissions(w) == {}
    assert _synced(w)["a1"] is False


def test_a_newly_used_assignment_is_unknown_until_read_and_a_refresh_is_queued(
    world: World,
) -> None:
    w = world
    w.publish(MODULE_M1, title="Writing module complete")
    w.sync()
    assert w.jobs("oc:sync_course") == []  # a module rule needs nothing new from Canvas

    w.lms.set_submission(w.ref, "lms-s1", "a1", workflow_state="submitted")
    w.publish(SUBMIT_A1)
    # Nobody's submission for the essay is held yet. Saying "not submitted" would be a guess.
    w.evaluate()
    assert {_reason(w, s) for s in ("s1", "s2")} == {"DATA_NOT_SYNCED"}
    # Publishing queued a refresh from Canvas, so students do not wait for the next scheduled one.
    assert [j["args"]["kind"] for j in w.jobs("oc:sync_course")] == ["hint"]

    w.sync_and_evaluate()
    assert _reason(w, "s1") == "SUBMITTED" and _reason(w, "s2") == "NOT_SUBMITTED"


# ---- a course that has ended -------------------------------------------------------------------


def _ended(w: World, days_ago: int | None) -> None:
    if days_ago is None:
        w.lms.course_states.pop(w.ref, None)
    else:
        w.lms.course_states[w.ref] = CourseStateRecord(
            concluded=True, ended_at=datetime.now(UTC) - timedelta(days=days_ago)
        )


def _check_ends(w: World) -> str | None:
    """Run the daily job and say what it did to this world's course. (Courses left behind by
    other tests are checked too; the fake Canvas says they are still running.)"""
    before = _course(w)
    tasks.check_course_ends(0)
    after = _course(w)
    if after.status == "archived" and before.status != "archived":
        return "archived"
    if after.ended_at is None and before.ended_at is not None:
        return "reopened"
    if after.ended_at is not None and before.ended_at is None:
        return "ended"
    return None


def test_an_ended_course_is_still_read_for_a_while_then_archived(world: World) -> None:
    w = world
    w.publish(MODULE_M1)
    w.sync()

    assert _check_ends(w) is None  # still running: nothing changes
    assert _course(w).ended_at is None

    _ended(w, 10)
    assert _check_ends(w) == "ended"
    course = _course(w)
    assert course.status == "active" and course.ended_at is not None
    # Marks released after the end date still count: the course is still read.
    assert w.sync()["status"] == "ok"
    assert _check_ends(w) is None

    _ended(w, 61)  # past the 60 days an ended course is still read by default
    assert _check_ends(w) == "archived"
    course = _course(w)
    assert course.status == "archived" and course.archived_at is not None
    assert w.sync()["status"] == "course_inactive"
    _ended(w, None)
    assert _check_ends(w) is None  # archived courses are left alone, whatever Canvas says
    assert _course(w).status == "archived"
    assert {"course.ended", "course.archive"} <= set(_audit(w))


def test_a_course_that_reopens_before_it_is_archived_carries_on(world: World) -> None:
    w = world
    w.publish(MODULE_M1)
    _ended(w, 5)
    assert _check_ends(w) == "ended"
    _ended(w, None)  # the end date was moved in Canvas
    assert _check_ends(w) == "reopened"
    course = _course(w)
    assert course.ended_at is None and course.status == "active"


def test_nothing_is_decided_when_canvas_cannot_be_read(world: World) -> None:
    w = world
    w.publish(MODULE_M1)
    _ended(w, 400)
    w.lms.failures[("course_state",)] = LmsPermissionError("no access")
    counts = tasks.check_course_ends(0)
    assert (counts["ended"], counts["archived"]) == (0, 0)
    assert _course(w).ended_at is None and _course(w).status == "active"


def test_the_institution_sets_how_long_an_ended_course_is_still_read(world: World) -> None:
    w = world
    r = w.patch(
        "admin", "/api/v1/institutions/current/retention", {"sync_days_after_course_end": 7}
    )
    assert r.status_code == 200 and r.json()["sync_days_after_course_end"] == 7
    r = w.patch(
        "admin", "/api/v1/institutions/current/retention", {"sync_days_after_course_end": 900}
    )
    assert r.status_code == 422
    w.publish(MODULE_M1)
    _ended(w, 8)
    assert _check_ends(w) == "archived"


def test_an_archived_course_comes_back_only_if_canvas_says_it_is_running(world: World) -> None:
    w = world
    w.publish(MODULE_M1)
    _ended(w, 90)
    assert _check_ends(w) == "archived"

    r = w.post("lecturer", f"/api/v1/courses/{w.course_id}/activate")
    assert r.status_code == 409 and r.json()["code"] == "COURSE_ARCHIVED"
    assert "ended in Canvas" in r.json()["title"]

    _ended(w, None)  # opened again in Canvas
    r = w.post("lecturer", f"/api/v1/courses/{w.course_id}/activate")
    assert r.status_code == 200 and r.json()["sync_queued"] is True
    course = _course(w)
    assert (course.status, course.ended_at, course.archived_at) == ("active", None, None)


def test_snapshots_are_deleted_a_set_time_after_the_course_ended(world: World) -> None:
    w = world
    w.lms.complete_module(w.ref, "lms-s1", "m1")
    w.lms.set_submission(w.ref, "lms-s1", "a1", workflow_state="submitted")
    w.publish(
        {"mode": "ALL", "rules": [MODULE_M1["rules"][0], SUBMIT_A1["rules"][0]]},
    )
    w.sync()

    def held() -> tuple[int, int]:
        with w.db() as db:
            progress = db.scalars(
                select(m.LmsModuleProgress).where(m.LmsModuleProgress.course_id == w.course_id)
            ).all()
        return len(progress), len(_submissions(w))

    assert held()[0] > 0 and held()[1] > 0

    def archive(ended_days_ago: int) -> None:
        with owner_session() as db:
            course = db.get(m.Course, w.course_id)
            assert course is not None
            course.status = "archived"
            course.ended_at = datetime.now(UTC) - timedelta(days=ended_days_ago)
            course.archived_at = course.ended_at + timedelta(days=60)

    archive(200)  # ended, archived, but inside the year snapshots are kept
    r = w.post("admin", "/api/v1/admin/retention/run")
    assert r.status_code == 200, r.text
    assert (r.json()["module_progress"], r.json()["submissions"]) == (0, 0)
    assert held()[0] > 0 and held()[1] > 0

    archive(366)
    r = w.post("admin", "/api/v1/admin/retention/run")
    assert r.json()["module_progress"] > 0 and r.json()["submissions"] > 0
    assert held() == (0, 0)
