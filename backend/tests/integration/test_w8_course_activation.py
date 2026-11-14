# SPDX-License-Identifier: AGPL-3.0-or-later
"""Switching micro-credentials on for a course (spec §4.1, RTM R-4.1-06, R-4.4-01).

Found in the W8 run against a real Canvas: a course created by its first launch stayed
``inactive`` for ever, because nothing could activate it, so scheduled reconciliation never
picked it up although the home page told lecturers to "activate the course".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.jobs import tasks
from opencredential.lti import provision
from opencredential.lti.claims import LaunchData
from opencredential.settings import get_settings
from tests.integration.test_w7_governance import _authorised_issuer, _manual_badge
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


def _set_status(w: World, status: str) -> None:
    with owner_session() as db:
        course = db.get(m.Course, w.course_id)
        assert course is not None
        course.status = status
        course.activated_at = None


def _sync_jobs(owner_conn, course_id: uuid.UUID) -> list[str]:  # type: ignore[no-untyped-def]
    rows = owner_conn.execute(
        "SELECT args->>'kind' FROM jobs.procrastinate_jobs"
        " WHERE task_name = 'oc:sync_course' AND args->>'course_id' = %s ORDER BY id",
        [str(course_id)],
    ).fetchall()
    return [r[0] for r in rows]


def _clear_sync_jobs(owner_conn, course_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    """Forget queued syncs, as if the worker had run them (their queueing lock is released)."""
    owner_conn.execute("SET search_path TO jobs, public")
    owner_conn.execute(
        "DELETE FROM procrastinate_jobs WHERE args->>'course_id' = %s", [str(course_id)]
    )
    owner_conn.execute("RESET search_path")
    owner_conn.commit()


def test_lecturer_activates_course_and_an_initial_sync_is_queued(
    client: TestClient, owner_conn
) -> None:  # type: ignore[no-untyped-def]
    w = build_world(client)
    _set_status(w, "inactive")
    path = f"/api/v1/courses/{w.course_id}"

    # students and staff of other courses cannot switch it on
    assert w.post("s1", f"{path}/activate").status_code in (403, 404)
    assert w.post("outsider", f"{path}/activate").status_code == 404
    other = build_world(client)
    assert other.post("admin", f"{path}/activate").status_code == 404

    r = w.post("lecturer", f"{path}/activate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active" and body["activated_at"] and body["sync_queued"] is True
    assert _sync_jobs(owner_conn, w.course_id) == ["initial"]

    # idempotent: a second call changes nothing and queues nothing more
    again = w.post("lecturer", f"{path}/activate").json()
    assert again["status"] == "active" and again["sync_queued"] is False
    assert _sync_jobs(owner_conn, w.course_id) == ["initial"]

    with tenant_session(w.iid) as db:
        course = db.get(m.Course, w.course_id)
        assert course is not None and course.activated_by == w.users["lecturer"]
        actions = list(
            db.scalars(
                select(m.AuditEvent.action).where(m.AuditEvent.resource_id == str(w.course_id))
            )
        )
    assert actions.count("course.activate") == 1

    # the launch profile reports it as active, so the "not switched on" banner goes away
    me = w.get("lecturer", "/api/v1/courses").json()
    assert [c["status"] for c in me if c["id"] == str(w.course_id)] == ["active"]


def test_only_active_courses_join_scheduled_reconciliation(client: TestClient, owner_conn) -> None:  # type: ignore[no-untyped-def]
    w = build_world(client)
    _manual_badge(w, _authorised_issuer(w))
    _set_status(w, "inactive")
    tasks.schedule_course_syncs(0)
    assert "scheduled" not in _sync_jobs(owner_conn, w.course_id)

    assert w.post("admin", f"/api/v1/courses/{w.course_id}/activate").status_code == 200
    _clear_sync_jobs(owner_conn, w.course_id)
    tasks.schedule_course_syncs(0)
    assert _sync_jobs(owner_conn, w.course_id) == ["scheduled"]

    # switching it off again stops scheduled reconciliation; credentials are not touched
    r = w.post("lecturer", f"/api/v1/courses/{w.course_id}/deactivate")
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    _clear_sync_jobs(owner_conn, w.course_id)
    tasks.schedule_course_syncs(0)
    assert _sync_jobs(owner_conn, w.course_id) == []


def test_inactive_course_is_never_read_from_canvas(client: TestClient, owner_conn) -> None:  # type: ignore[no-untyped-def]
    """Review finding C2: a student's on-demand refresh, or a sync job queued before the course
    was switched off, must not read Canvas and so cannot evaluate or award."""
    w = build_world(client)
    _manual_badge(w, _authorised_issuer(w))
    _set_status(w, "inactive")
    _clear_sync_jobs(owner_conn, w.course_id)

    r = w.post("s1", f"/api/v1/courses/{w.course_id}/sync")
    assert r.status_code == 409 and r.json()["code"] == "COURSE_NOT_ACTIVE"
    assert _sync_jobs(owner_conn, w.course_id) == []

    out = tasks.sync_course_task(str(w.iid), str(w.course_id), kind="on_demand")
    assert out == {"status": "course_inactive"}
    with tenant_session(w.iid) as db:
        runs = db.scalars(select(m.SyncRun).where(m.SyncRun.course_id == w.course_id)).all()
    assert all(run.kind != "on_demand" for run in runs)
    jobs = owner_conn.execute(
        "SELECT count(*) FROM jobs.procrastinate_jobs"
        " WHERE task_name = 'oc:evaluate_course' AND args->>'course_id' = %s"
        " AND status = 'todo'",
        [str(w.course_id)],
    ).fetchone()
    assert jobs is not None and jobs[0] == 0

    # once switched on, a student can ask for a refresh again
    assert w.post("lecturer", f"/api/v1/courses/{w.course_id}/activate").status_code == 200
    _clear_sync_jobs(owner_conn, w.course_id)
    assert w.post("s1", f"/api/v1/courses/{w.course_id}/sync").status_code == 202


def test_archived_course_cannot_be_switched_on(client: TestClient) -> None:
    w = build_world(client)
    _set_status(w, "archived")
    r = w.post("lecturer", f"/api/v1/courses/{w.course_id}/activate")
    assert r.status_code == 409


@pytest.mark.parametrize(("required", "expected"), [(True, "inactive"), (False, "active")])
def test_first_launch_follows_the_institution_activation_policy(
    client: TestClient, required: bool, expected: str
) -> None:
    w = build_world(client, policy={"course_activation_required": required})
    with tenant_session(w.iid) as db:
        integration = db.scalar(select(m.CanvasIntegration))
        assert integration is not None
        launch = LaunchData(
            issuer=integration.lti_issuer or "",
            client_id="c",
            deployment_id="d",
            subject="sub",
            roles=(),
            course_roles=frozenset({"lecturer"}),
            context_id=f"ctx-{uuid.uuid4().hex}",
            context_title="New Course",
            context_label=None,
            resource_link_id="rl",
            canvas_course_id=f"new-{uuid.uuid4().hex[:6]}",
            canvas_user_id=None,
            sis_user_id=None,
            name=None,
            given_name=None,
            family_name=None,
            email=None,
            nrps_url=None,
            is_test_user=False,
            target_link_uri="https://tool.example/lti/launch",
        )
        course, created = provision.upsert_course(db, w.iid, integration.id, launch)
        assert created
        assert course.status == expected
        assert (course.activated_at is not None) is (not required)


def test_activation_policy_is_set_by_an_institution_administrator(client: TestClient) -> None:
    w = build_world(client)
    url = "/api/v1/institutions/current/policy"
    assert w.get("admin", url).json()["course_activation_required"] is True
    assert w.patch("lecturer", url, {"course_activation_required": False}).status_code in (403, 404)
    r = w.patch("admin", url, {"course_activation_required": False})
    assert r.status_code == 200 and r.json()["course_activation_required"] is False


def test_course_staff_see_and_export_their_course_award_history(client: TestClient) -> None:
    """Spec §2.2: lecturers review award history and export course-level issuance records."""
    from tests.integration.test_w7_governance import _issue_to

    w = build_world(client)
    definition_id = _manual_badge(w, _authorised_issuer(w))
    cred_id = _issue_to(w, definition_id, "s1")
    path = f"/api/v1/courses/{w.course_id}/credentials"

    rows = w.get("lecturer", path).json()
    assert [r["credential_id"] for r in rows] == [cred_id]
    assert rows[0]["award_kind"] == "manual" and rows[0]["status"] == "active"

    csv = w.get("lecturer", f"{path}.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("credential_id,") and len(lines) == 2 and cred_id in lines[1]
    assert "@" not in csv.text  # no email addresses

    # students, staff of other courses and other institutions see nothing
    assert w.get("s1", path).status_code == 404
    assert w.get("outsider", f"{path}.csv").status_code == 404
    assert build_world(client).get("admin", path).status_code == 404
    with tenant_session(w.iid) as db:
        assert db.scalar(
            select(m.AuditEvent.id).where(m.AuditEvent.action == "course.report_export")
        )
