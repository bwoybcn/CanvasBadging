# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether background work is healthy, and telling someone when it is not.

Two things can go wrong without anyone seeing: a job fails for good (a badge is not issued, a
course is not refreshed), or the worker stops altogether. Both used to be visible only to an
administrator who opened the Reconciliation page. This module gives:

* :func:`snapshot`, read by ``GET /healthz/jobs`` for a monitoring tool to poll, and
* :func:`alert_text` and :func:`send_alert`, used by the ``alert_failed_jobs`` task to post to a
  chat channel webhook (``OC_ALERT_WEBHOOK_URL``).

Everything here counts across the whole installation and carries task names and numbers only:
no institution, course or person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Connection, text

from opencredential.logging import get_logger

log = get_logger("jobs.health")

#: A worker that has not reported for this long is treated as stopped. Workers report every
#: few seconds while they run.
WORKER_SILENT_AFTER_SECONDS = 120
#: ``GET /healthz/jobs`` stays unhealthy this long after a job fails, then clears by itself.
RECENT_FAILURE_SECONDS = 24 * 3600

ADMIN_PLACE = "Administration, Reconciliation"


@dataclass
class JobHealth:
    failed_total: int
    #: Jobs that failed inside the window asked for, by task name.
    failed_recent: dict[str, int] = field(default_factory=dict)
    #: Seconds since any worker last reported, or ``None`` when none ever has.
    worker_silent_seconds: float | None = None

    @property
    def failed_recent_count(self) -> int:
        return sum(self.failed_recent.values())

    @property
    def worker_ok(self) -> bool:
        return (
            self.worker_silent_seconds is not None
            and self.worker_silent_seconds < WORKER_SILENT_AFTER_SECONDS
        )


def _task(name: str) -> str:
    return name.split(":", 1)[-1].rsplit(".", 1)[-1]


def snapshot(
    conn: Connection, *, since: datetime, until: datetime | None = None, now: datetime | None = None
) -> JobHealth:
    """Counts across every institution. ``conn`` is a plain application connection: the job
    tables carry no personal data and are not under row-level security."""
    now = now or datetime.now(UTC)
    until = until or now
    failed_total = int(
        conn.execute(
            text("SELECT count(*) FROM jobs.procrastinate_jobs WHERE status = 'failed'")
        ).scalar()
        or 0
    )
    recent: dict[str, int] = {}
    if failed_total:
        rows = conn.execute(
            text(
                """
                SELECT j.task_name, count(DISTINCT j.id)
                  FROM jobs.procrastinate_jobs j
                  JOIN jobs.procrastinate_events e ON e.job_id = j.id AND e.type = 'failed'
                 WHERE j.status = 'failed' AND e.at >= :since AND e.at < :until
                 GROUP BY j.task_name
                """
            ),
            {"since": since, "until": until},
        )
        recent = {_task(str(name)): int(n) for name, n in rows}
    beat = conn.execute(text("SELECT max(last_heartbeat) FROM jobs.procrastinate_workers")).scalar()
    silent = None if beat is None else max(0.0, (now - beat).total_seconds())
    return JobHealth(failed_total=failed_total, failed_recent=recent, worker_silent_seconds=silent)


def _jobs(n: int) -> str:
    return "1 background job" if n == 1 else f"{n} background jobs"


def alert_text(health: JobHealth, *, site: str, minutes: int, reminder: bool) -> str | None:
    """The message to post, or ``None`` when there is nothing to say.

    ``reminder`` is the once-a-day nudge: it speaks up while failed jobs are still waiting,
    even if none failed in this window.
    """
    waiting = (
        f"{_jobs(health.failed_total)} waiting for an administrator: "
        f"open Badges in Canvas, then {ADMIN_PLACE}."
    )
    if health.failed_recent_count:
        tasks = ", ".join(f"{name} x{n}" for name, n in sorted(health.failed_recent.items()))
        return (
            f"OpenCredential ({site}): {_jobs(health.failed_recent_count)} failed in the last "
            f"{minutes} minutes ({tasks}). In total, {waiting}"
        )
    if reminder and health.failed_total:
        return (
            f"OpenCredential ({site}): daily reminder. "
            f"There {_is_are(health.failed_total)} {waiting}"
        )
    return None


def _is_are(n: int) -> str:
    return "is" if n == 1 else "are"


def payload(message: str, fmt: str) -> dict[str, Any]:
    """``text``: Slack, Mattermost and other "incoming webhook" receivers. ``teams``: a
    Microsoft Teams workflow webhook, which takes an Adaptive Card."""
    if fmt == "teams":
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [{"type": "TextBlock", "text": message, "wrap": True}],
                    },
                }
            ],
        }
    return {"text": message}


def send_alert(url: str, message: str, fmt: str, *, client: httpx.Client | None = None) -> bool:
    """Post the message. Never raises: an alert that cannot be delivered must not become one
    more failed job. Returns whether the receiver accepted it."""
    try:
        post = client.post if client is not None else httpx.post
        response = post(url, json=payload(message, fmt), timeout=10.0)
    except httpx.HTTPError as exc:
        log.warning("alert.not_sent", error=type(exc).__name__)
        return False
    if response.status_code >= 300:
        log.warning("alert.not_sent", status=response.status_code)
        return False
    log.info("alert.sent")
    return True
