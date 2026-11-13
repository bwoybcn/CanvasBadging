# SPDX-License-Identifier: AGPL-3.0-or-later
"""Task definitions. Every task must be idempotent (ADR-0011).

Tenant-scoped tasks must carry ``institution_id`` in their arguments and open their DB session
with :func:`opencredential.db.session.tenant_session`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import procrastinate
from sqlalchemy import delete

from opencredential.db.models import LtiLaunchState, LtiNonceUsed
from opencredential.db.session import tenant_session
from opencredential.logging import get_logger

log = get_logger("jobs")
blueprint = procrastinate.Blueprint()

RETRY = {"max_attempts": 8, "wait": 5, "exponential_wait": 2}


@blueprint.task(name="ping", queue="default")
def ping(message: str = "pong") -> str:
    """Health task used by tests and operators to prove the worker consumes the queue."""
    log.info("ping", message=message)
    return message


@blueprint.periodic(cron="*/10 * * * *", periodic_id="purge_lti_state")
@blueprint.task(name="purge_lti_state", queue="maintenance", queueing_lock="purge_lti_state")
def purge_lti_state(timestamp: int) -> int:
    """Delete OIDC state and nonce rows past their TTL (data-model.md retention)."""
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    with tenant_session(None) as db:
        a = db.execute(delete(LtiLaunchState).where(LtiLaunchState.created_at < cutoff))
        b = db.execute(delete(LtiNonceUsed).where(LtiNonceUsed.expires_at < datetime.now(UTC)))
    removed = (a.rowcount or 0) + (b.rowcount or 0)  # type: ignore[attr-defined]
    log.info("purge_lti_state", removed=removed)
    return removed
