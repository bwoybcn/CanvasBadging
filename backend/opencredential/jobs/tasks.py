# SPDX-License-Identifier: AGPL-3.0-or-later
"""Task definitions. Every task must be idempotent (ADR-0011).

Tenant-scoped tasks must carry ``institution_id`` in their arguments and open their DB session
with :func:`opencredential.db.session.tenant_session`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import procrastinate
from sqlalchemy import delete, select

from opencredential.db.models import LtiLaunchState, LtiNonceUsed
from opencredential.db.session import tenant_session
from opencredential.jobs.defer import defer
from opencredential.logging import get_logger
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient

log = get_logger("jobs")
blueprint = procrastinate.Blueprint()

RETRY = procrastinate.RetryStrategy(max_attempts=8, wait=5, exponential_wait=2)


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


# ---- issuance and status (W4) -------------------------------------------------------------


def _signer() -> SignerClient:
    return SignerClient(get_settings())


@blueprint.task(name="issue_credential", queue="issuance", retry=RETRY)
def issue_credential(institution_id: str, award_decision_id: str) -> str:
    """Issue the credential for an award decision. Idempotent; safe to retry (ADR-0012)."""
    from opencredential.issuance.service import IssuanceError, issue

    signer = _signer()
    try:
        result = issue(
            uuid.UUID(institution_id),
            uuid.UUID(award_decision_id),
            signer=signer,
            settings=get_settings(),
        )
    except IssuanceError as exc:
        # Permanent: retrying won't help. The pending row and decision stay for reconciliation.
        log.error("issuance_refused", award_decision_id=award_decision_id, error=str(exc))
        return "refused"
    finally:
        signer.close()
    if result.status_list_id is not None:
        _publish_if_unpublished(uuid.UUID(institution_id), result.status_list_id)
    return result.outcome


def _publish_if_unpublished(institution_id: uuid.UUID, status_list_id: uuid.UUID) -> None:
    from opencredential.db.models import StatusList

    with tenant_session(institution_id) as db:
        sl = db.get(StatusList, status_list_id)
        needed = sl is not None and sl.published_credential is None
    if needed:
        defer_publish(institution_id, status_list_id)


def defer_publish(institution_id: uuid.UUID, status_list_id: uuid.UUID) -> None:
    """Queue a republish; the queueing lock collapses bursts of revocations into one job."""
    defer(
        "publish_status_list",
        lock=f"publish:{status_list_id}",
        schedule_in={"seconds": 10},
        institution_id=str(institution_id),
        status_list_id=str(status_list_id),
    )


@blueprint.task(name="publish_status_list", queue="status", retry=RETRY)
def publish_status_list(institution_id: str, status_list_id: str) -> None:
    from opencredential.status.service import publish

    signer = _signer()
    try:
        with tenant_session(uuid.UUID(institution_id)) as db:
            publish(db, uuid.UUID(status_list_id), signer, get_settings())
    finally:
        signer.close()


def _each_institution() -> list[uuid.UUID]:
    from opencredential.db.models import Institution

    with tenant_session(None) as db:
        return list(db.scalars(select(Institution.id).where(Institution.status == "active")))


@blueprint.periodic(cron="17 * * * *", periodic_id="republish_status_lists")
@blueprint.task(
    name="republish_status_lists", queue="maintenance", queueing_lock="republish_status_lists"
)
def republish_status_lists(timestamp: int) -> int:
    """Re-sign lists that are unpublished or due (daily), well before their 30-day validUntil."""
    from opencredential.status.service import lists_due

    count = 0
    for iid in _each_institution():
        with tenant_session(iid) as db:
            due = lists_due(db)
        for list_id in due:
            defer_publish(iid, list_id)
            count += 1
    log.info("republish_status_lists", queued=count)
    return count


@blueprint.periodic(cron="*/15 * * * *", periodic_id="reconcile_issuance")
@blueprint.task(name="reconcile_issuance", queue="maintenance", queueing_lock="reconcile_issuance")
def reconcile_issuance(timestamp: int) -> int:
    """Re-queue issuance for credentials stuck in ``pending_signature`` (spec §17.2)."""
    from opencredential.issuance.service import pending

    count = 0
    for iid in _each_institution():
        with tenant_session(iid) as db:
            stuck = [d.id for d in pending(db)]
        for decision_id in stuck:
            defer(
                "issue_credential",
                lock=f"issue:{decision_id}",
                institution_id=str(iid),
                award_decision_id=str(decision_id),
            )
            count += 1
    return count


@blueprint.periodic(cron="41 3 * * *", periodic_id="destroy_retired_keys")
@blueprint.task(
    name="destroy_retired_keys", queue="maintenance", queueing_lock="destroy_retired_keys"
)
def destroy_retired_keys(timestamp: int) -> int:
    """Erase private material of keys retired more than 30 days ago (public keys stay)."""
    from opencredential.institutions.keys import keys_due_for_destruction

    signer = _signer()
    count = 0
    try:
        for iid in _each_institution():
            with tenant_session(iid) as db:
                ids = [k.id for k in keys_due_for_destruction(db)]
            for key_id in ids:
                signer.destroy_key(key_id)
                count += 1
    finally:
        signer.close()
    return count
