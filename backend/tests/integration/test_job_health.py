# SPDX-License-Identifier: AGPL-3.0-or-later
"""Someone is told when background work fails (whole-product review, finding 6).

``GET /healthz/jobs`` is for a monitoring tool to poll; ``alert_failed_jobs`` posts to a chat
channel webhook. Both count across the installation and carry no personal data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from opencredential.api.app import create_app
from opencredential.jobs import health, tasks
from opencredential.settings import get_settings

pytestmark = pytest.mark.db


def _fail_a_job(conn, task: str) -> int:  # type: ignore[no-untyped-def]
    job_id = conn.execute(
        "INSERT INTO jobs.procrastinate_jobs (queue_name, task_name, args)"
        " VALUES ('issuance', %s, '{}') RETURNING id",
        [task],
    ).fetchone()[0]
    # the same two steps a worker takes, so procrastinate's own triggers write the events
    conn.execute("UPDATE jobs.procrastinate_jobs SET status = 'doing' WHERE id = %s", [job_id])
    conn.execute("UPDATE jobs.procrastinate_jobs SET status = 'failed' WHERE id = %s", [job_id])
    conn.commit()
    return int(job_id)


@pytest.fixture
def clean_jobs(app_conn):  # type: ignore[no-untyped-def]
    app_conn.execute("DELETE FROM jobs.procrastinate_jobs WHERE status = 'failed'")
    app_conn.execute("DELETE FROM jobs.procrastinate_workers")
    app_conn.commit()
    yield app_conn
    app_conn.execute("DELETE FROM jobs.procrastinate_jobs WHERE task_name LIKE 'oc:health_test%'")
    app_conn.execute("DELETE FROM jobs.procrastinate_workers")
    app_conn.commit()


def test_monitor_endpoint_reports_a_stopped_worker_and_recent_failures(clean_jobs) -> None:  # type: ignore[no-untyped-def]
    conn = clean_jobs
    with TestClient(create_app(get_settings())) as c:
        # no worker has ever run: that alone needs attention
        r = c.get("/healthz/jobs")
        assert r.status_code == 503
        assert r.json()["checks"]["worker"].startswith("no worker")
        assert r.json()["checks"]["failed_jobs"] == "ok"

        conn.execute("INSERT INTO jobs.procrastinate_workers DEFAULT VALUES")
        conn.commit()
        r = c.get("/healthz/jobs")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "status": "ok",
            "checks": {"worker": "ok", "failed_jobs": "ok"},
            "failed_last_24_hours": 0,
            "failed_waiting": 0,
        }

        _fail_a_job(conn, "oc:health_test_issue")
        r = c.get("/healthz/jobs")
        assert r.status_code == 503
        assert r.json()["failed_last_24_hours"] == 1
        assert r.json()["checks"]["failed_jobs"] == "1 failed in the last 24 hours"
        # the load balancer's probe does not look at background work
        assert c.get("/healthz").status_code == 200

        # a worker that went quiet five minutes ago counts as stopped
        conn.execute(
            "UPDATE jobs.procrastinate_workers SET last_heartbeat = now() - interval '5 minutes'"
        )
        conn.commit()
        assert c.get("/healthz/jobs").json()["checks"]["worker"].startswith("no worker")


def test_alert_task_reports_new_failures_once_and_reminds_daily(clean_jobs, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    conn = clean_jobs
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        health, "send_alert", lambda url, message, fmt, **_: sent.append((url, message, fmt))
    )
    settings = get_settings()
    now = datetime.now(UTC)
    tick = int((now + timedelta(minutes=1)).timestamp())

    # nothing is sent, and the job tables are not even read, until a webhook is configured
    monkeypatch.setattr(settings, "alert_webhook_url", None)
    _fail_a_job(conn, "oc:health_test_issue")
    _fail_a_job(conn, "oc:health_test_issue")
    _fail_a_job(conn, "oc:health_test_sync")
    assert tasks.alert_failed_jobs(tick) == 0
    assert sent == []

    monkeypatch.setattr(settings, "alert_webhook_url", "https://chat.example/hooks/abc")
    monkeypatch.setattr(settings, "public_base_url", "https://badges.example.ac.uk")
    assert tasks.alert_failed_jobs(tick) == 3
    (url, message, fmt) = sent.pop()
    assert url == "https://chat.example/hooks/abc" and fmt == "text"
    assert message == (
        "OpenCredential (https://badges.example.ac.uk): 3 background jobs failed in the last "
        "10 minutes (health_test_issue x2, health_test_sync x1). In total, 3 background jobs "
        "waiting for an administrator: open Badges in Canvas, then Administration, "
        "Reconciliation."
    )

    # the next tick has no new failure: silence, except at the daily reminder tick
    later = tick + 600
    assert tasks.alert_failed_jobs(later) == 0
    assert sent == []
    eight_am = (later // 86400 + 1) * 86400 + 8 * 3600
    assert tasks.alert_failed_jobs(eight_am) == 0
    assert "daily reminder. There are 3 background jobs waiting" in sent.pop()[1]

    # once an administrator has dealt with them, the reminder stops too
    conn.execute("DELETE FROM jobs.procrastinate_jobs WHERE task_name LIKE 'oc:health_test%'")
    conn.commit()
    assert tasks.alert_failed_jobs(eight_am + 86400) == 0
    assert sent == []


def test_alert_delivery_formats_and_never_raises() -> None:
    seen: list[dict] = []

    def receiver(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(receiver)) as client:
        assert health.send_alert("https://chat.example/h", "One job failed", "text", client=client)
        assert seen.pop() == {"text": "One job failed"}
        assert health.send_alert("https://chat.example/h", "One job failed", "teams", client=client)
        card = seen.pop()["attachments"][0]
        assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert card["content"]["body"][0]["text"] == "One job failed"

    def refuses(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    for handler in (refuses, unreachable):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            assert health.send_alert("https://chat.example/h", "x", "text", client=client) is False


def test_alert_wording() -> None:
    one = health.JobHealth(failed_total=1, failed_recent={"issue_credential": 1})
    text = health.alert_text(one, site="https://b.example", minutes=10, reminder=False)
    assert text is not None and "1 background job failed in the last 10 minutes" in text
    quiet = health.JobHealth(failed_total=0)
    assert health.alert_text(quiet, site="s", minutes=10, reminder=True) is None
    waiting = health.JobHealth(failed_total=1)
    assert health.alert_text(waiting, site="s", minutes=10, reminder=False) is None
    reminder = health.alert_text(waiting, site="s", minutes=10, reminder=True)
    assert reminder is not None and "There is 1 background job waiting" in reminder
