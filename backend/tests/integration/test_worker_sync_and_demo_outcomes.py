# SPDX-License-Identifier: AGPL-3.0-or-later
"""The real worker runs W5 jobs, and the engine reproduces the seeded golden outcomes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential import seed
from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import tenant_session
from opencredential.integrations import registry
from opencredential.jobs import tasks
from opencredential.settings import get_settings
from tests.integration.test_seed_and_api import GOLDEN
from tests.integration.world import COURSE_REF, World, build_world

pytestmark = pytest.mark.db


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


def test_worker_consumes_sync_and_evaluation_jobs(client: TestClient, owner_conn) -> None:  # type: ignore[no-untyped-def]
    from opencredential.jobs.app import build_app

    w: World = build_world(client)
    with registry.override(w.lms):
        w.sync()
        w.publish({"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]})
        w.lms.complete_module(COURSE_REF, "lms-s1", "m1")
        r = w.post("s1", f"/api/v1/courses/{w.course_id}/sync")
        assert r.status_code == 202 and r.json()["queued"]
        app = build_app()
        with app.open():
            app.run_worker(
                queues=["sync", "eligibility"], wait=False, install_signal_handlers=False
            )
    owner_conn.execute("SET search_path TO app, jobs, public")
    rows = owner_conn.execute(
        "SELECT task_name, status FROM jobs.procrastinate_jobs"
        " WHERE args->>'institution_id' = %s AND queue_name IN ('sync', 'eligibility')",
        [str(w.iid)],
    ).fetchall()
    assert rows and all(status == "succeeded" for _, status in rows), rows
    assert {t for t, _ in rows} == {"oc:sync_course", "oc:evaluate_course"}
    (decision,) = w.decisions()
    assert decision.status == "ready"
    # Rate limit: an immediate second on-demand refresh is refused.
    assert w.post("s1", f"/api/v1/courses/{w.course_id}/sync").status_code == 429


@pytest.fixture(scope="module")
def seeded(database: None, signer_available: bool) -> seed.SeedResult:
    return seed.run()


def test_engine_reproduces_seed_golden_outcomes_after_dev_sync(seeded: seed.SeedResult) -> None:
    with tenant_session(seeded.institution_id) as db:
        course = db.scalars(select(m.Course)).one()
    tasks.sync_course_task(str(seeded.institution_id), str(course.id), kind="on_demand")
    tasks.evaluate_course_task(str(seeded.institution_id), str(course.id))
    with tenant_session(seeded.institution_id) as db:
        rows = db.execute(
            select(m.User.given_name, m.AchievementVersion.title, m.EligibilityEvaluation)
            .join(m.User, m.User.id == m.EligibilityEvaluation.user_id)
            .join(
                m.AchievementVersion, m.AchievementVersion.id == m.EligibilityEvaluation.version_id
            )
            .where(m.EligibilityEvaluation.triggered_by == "sync")
        ).all()
        decisions = db.scalars(select(m.AwardDecision)).all()
    engine = {(g, t): e.outcome for g, t, e in rows}
    assert len(engine) == 108
    for key, expected in GOLDEN.items():
        assert engine[key] == expected, key
    # Automatic badges issue on met; lecturer-confirmed ones wait; manual ones never auto-award.
    assert decisions and {d.kind for d in decisions} <= {"automatic", "confirmed"}
    assert any(d.status == "awaiting_confirmation" for d in decisions)
