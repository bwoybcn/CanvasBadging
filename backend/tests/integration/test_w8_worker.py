# SPDX-License-Identifier: AGPL-3.0-or-later
"""Jobs run by the real procrastinate worker, not called inline.

W8 regression: inside ``oc worker`` every ``issue_credential`` job signed the credential and
then failed while queueing the first publication of its status list (procrastinate refused a
second, synchronous ``open()`` of the already-open app), so newly issued credentials reported
"unable to verify" until the hourly republish. The inline tests could not see it.
"""

from __future__ import annotations

import pytest

from opencredential.db import models as m
from opencredential.db.session import tenant_session
from opencredential.issuance import decisions
from opencredential.settings import get_settings
from tests.integration.w4_factory import build_tenant

pytestmark = pytest.mark.db


def test_worker_issues_and_queues_status_list_publication(
    database: None, signer_available: bool, owner_conn
) -> None:  # type: ignore[no-untyped-def]
    from opencredential.jobs import defer as defer_module
    from opencredential.jobs.app import build_app

    t = build_tenant(get_settings())
    with tenant_session(t.institution_id) as db:
        d, _ = decisions.decide(
            db,
            institution_id=t.institution_id,
            user_id=t.student_ids[0],
            version_id=t.version_id,
            kind="manual",
            justification="Completed all modules (worker test)",
            decided_by=t.admin_id,
        )
        decision_id = d.id

    defer_module.reset()  # a fresh worker process has not deferred anything yet
    app = build_app()
    with app.open():
        job_id = app.configure_task("oc:issue_credential").defer(
            decision_id=str(decision_id),
            institution_id=str(t.institution_id),
            subject_type="award_decision",
            subject_id=str(decision_id),
        )
        app.run_worker(queues=["issuance"], wait=False, install_signal_handlers=False)
    defer_module.reset()

    status = owner_conn.execute(
        "SELECT status FROM jobs.procrastinate_jobs WHERE id = %s", [job_id]
    ).fetchone()[0]
    assert status == "succeeded"
    with tenant_session(t.institution_id) as db:
        assert db.get(m.AwardDecision, decision_id).status == "issued"  # type: ignore[union-attr]
    queued = owner_conn.execute(
        "SELECT count(*) FROM jobs.procrastinate_jobs WHERE task_name = 'oc:publish_status_list'"
        " AND args->>'institution_id' = %s",
        [str(t.institution_id)],
    ).fetchone()[0]
    assert queued == 1
