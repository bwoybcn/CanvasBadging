# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lighter syncing for staff-awarded courses and ready-made templates (extracurricular, PR 4).

A recognition course whose badges are all awarded by staff reads nothing from Canvas progress,
so it gets a roster refresh every six hours instead of a full sync every 30 minutes, and old
progress data never marks it stale. Administrators can add four ready-made templates for badges
outside modules.
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
from opencredential.db.session import tenant_session
from opencredential.governance.templates import STARTER_TEMPLATES
from opencredential.jobs import tasks
from opencredential.settings import get_settings
from tests.integration.w5_world import World, build_world

pytestmark = pytest.mark.db

MANUAL_RULES = {"mode": "ALL", "rules": [{"type": "manual_approval"}]}
MODULE_RULES = {"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]}
HOUR = 3600


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


def _jobs(owner_conn, course_id: uuid.UUID) -> list[str]:  # type: ignore[no-untyped-def]
    rows = owner_conn.execute(
        "SELECT args->>'kind' FROM jobs.procrastinate_jobs"
        " WHERE task_name = 'oc:sync_course' AND args->>'course_id' = %s ORDER BY id",
        [str(course_id)],
    ).fetchall()
    owner_conn.execute("SET search_path TO jobs, public")  # procrastinate's triggers need it
    owner_conn.execute(
        "DELETE FROM procrastinate_jobs WHERE args->>'course_id' = %s", [str(course_id)]
    )
    owner_conn.execute("RESET search_path")
    owner_conn.commit()
    return [r[0] for r in rows]


def _manual(w: World) -> None:
    w.publish(
        MANUAL_RULES,
        title="Library volunteer",
        category="Participation",
        demonstration_kind="participating",
        award_policy="manual",
    )


def _freshness(w: World) -> dict:  # type: ignore[type-arg]
    rows = w.get("admin", "/api/v1/admin/data-freshness").json()
    return next(r for r in rows if r["course_id"] == str(w.course_id))


def test_staff_awarded_course_gets_a_roster_refresh_every_six_hours(
    client: TestClient,
    owner_conn,  # type: ignore[no-untyped-def]
) -> None:
    w = build_world(client)
    _manual(w)
    _jobs(owner_conn, w.course_id)

    tasks.schedule_course_syncs(0)  # 00:00, a roster slot
    assert _jobs(owner_conn, w.course_id) == ["roster"]
    for ts in (30 * 60, HOUR, 5 * HOUR + 30 * 60):  # every other run in between: nothing
        tasks.schedule_course_syncs(ts)
        assert _jobs(owner_conn, w.course_id) == []
    tasks.schedule_course_syncs(6 * HOUR)
    assert _jobs(owner_conn, w.course_id) == ["roster"]

    # A roster-only run reads no progress and records no sync run.
    out = tasks.sync_course_task(str(w.iid), str(w.course_id), kind="roster")
    assert out == {"status": "roster_only"}
    with tenant_session(w.iid) as db:
        assert db.scalars(select(m.SyncRun).where(m.SyncRun.course_id == w.course_id)).all() == []

    # Old (here: missing) progress data does not mark the course stale.
    row = _freshness(w)
    assert row["needs_canvas_data"] is False and row["stale"] is False


def test_a_badge_that_reads_canvas_brings_back_the_full_sync(
    client: TestClient,
    owner_conn,  # type: ignore[no-untyped-def]
) -> None:
    w = build_world(client)
    _manual(w)
    w.publish(MODULE_RULES)
    _jobs(owner_conn, w.course_id)
    tasks.schedule_course_syncs(HOUR)
    assert _jobs(owner_conn, w.course_id) == ["scheduled"]
    row = _freshness(w)
    assert row["needs_canvas_data"] is True and row["stale"] is True  # never synced


def test_ready_made_templates(client: TestClient) -> None:
    w = build_world(client)
    assert w.post("lecturer", "/api/v1/admin/templates/starters", {}).status_code == 403

    r = w.post("admin", "/api/v1/admin/templates/starters", {})
    assert r.status_code == 201, r.text
    names = [t["name"] for t in r.json()]
    assert names == [t["name"] for t in STARTER_TEMPLATES]
    # Adding them again leaves the existing ones alone.
    assert w.post("admin", "/api/v1/admin/templates/starters", {}).json() == []

    offered = w.get("lecturer", "/api/v1/templates", params={"course_id": w.course_id}).json()
    volunteering = next(t for t in offered if t["name"] == "Volunteering hours")
    defaults = volunteering["defaults"]
    assert defaults["award_policy"] == "manual"
    assert defaults["achievement_type"] == "CoCurricular"

    # A badge started from it is staff-awarded and carries no credit wording.
    fields = {k: v for k, v in defaults.items() if k != "artwork"}
    fields["title"] = "Widening Participation Volunteer: 10 hours"
    d = w.draft(MANUAL_RULES, **fields)
    detail = w.get("lecturer", f"/api/v1/achievements/{d['id']}").json()
    assert detail["review"]["forced_by"] is None
