# SPDX-License-Identifier: AGPL-3.0-or-later
"""The procrastinate queue is installed in schema ``jobs`` and a worker consumes it."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def test_worker_runs_a_deferred_job(database: None, owner_conn) -> None:  # type: ignore[no-untyped-def]
    import opencredential.jobs.tasks as tasks
    from opencredential.jobs.app import build_app

    app = build_app()
    with app.open():
        job_id = app.configure_task("oc:ping").defer(message="hello")
        app.run_worker(queues=["default"], wait=False, install_signal_handlers=False)
    status = owner_conn.execute(
        "SELECT status FROM jobs.procrastinate_jobs WHERE id = %s", [job_id]
    ).fetchone()[0]
    assert status == "succeeded"
    assert tasks.ping("x") == "x"
