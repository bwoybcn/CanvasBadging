# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reconciliation of failed or stuck issuance (spec §10.5 "failed issuance jobs", §17.2).

Shows, for an institution administrator, everything that should have become a credential but
has not: awards that are ready with no credential, credentials stuck before signing or failed,
failed issuance jobs, and status lists that are overdue for republishing. Each item has a safe
action: re-queue issuance (idempotent on the award decision), or cancel the award with a reason
when it should never be issued.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementVersion,
    AwardDecision,
    Credential,
    StatusList,
    User,
    background_jobs,
)
from opencredential.errors import Conflict, Invalid, NotFound
from opencredential.jobs import enqueue

STUCK_AFTER = timedelta(minutes=10)


def overview(db: Session, actor: authz.Actor, now: datetime | None = None) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    now = now or datetime.now(UTC)
    cutoff = now - STUCK_AFTER
    done = aliased(Credential)
    issued = select(done.id).where(
        done.award_decision_id == AwardDecision.id, done.status == "issued"
    )
    decisions = db.execute(
        select(AwardDecision, Credential, AchievementVersion, User)
        .outerjoin(Credential, Credential.award_decision_id == AwardDecision.id)
        .join(AchievementVersion, AchievementVersion.id == AwardDecision.version_id)
        .join(User, User.id == AwardDecision.user_id)
        .where(
            AwardDecision.status == "ready",
            AwardDecision.decided_at < cutoff,
            ~issued.exists(),
        )
        .order_by(AwardDecision.decided_at)
        .limit(500)
    ).all()
    stuck = [
        {
            "decision_id": str(d.id),
            "badge_title": v.title,
            "learner_name": u.display_name,
            "decided_at": d.decided_at,
            "kind": d.kind,
            "credential_status": c.status if c else None,
            "attempts": c.attempts if c else 0,
            "last_error": (c.last_error or None) if c else None,
            "problem": (
                "never_started"
                if c is None
                else "signing_failed"
                if c.status == "failed"
                else "stuck_before_signing"
            ),
        }
        for d, c, v, u in decisions
    ]
    jobs = db.execute(
        select(background_jobs)
        .where(
            background_jobs.c.status == "failed",
            background_jobs.c.task_name.in_(("oc:issue_credential", "oc:publish_status_list")),
        )
        .order_by(background_jobs.c.id.desc())
        .limit(200)
    ).mappings()
    lists = db.scalars(
        select(StatusList).where(
            (StatusList.published_credential.is_(None))
            | (StatusList.next_publish_due < now - timedelta(hours=1))
        )
    ).all()
    return {
        "awards_not_issued": stuck,
        "failed_jobs": [
            {
                "id": j["id"],
                "task": j["task_name"],
                "attempts": j["attempts"],
                "scheduled_at": j["scheduled_at"],
                "subject_type": j["subject_type"],
                "subject_id": j["subject_id"],
            }
            for j in jobs
        ],
        "status_lists_overdue": [
            {
                "id": str(sl.id),
                "issuer_id": str(sl.issuer_id),
                "published_at": sl.published_at,
                "next_publish_due": sl.next_publish_due,
            }
            for sl in lists
        ],
    }


def _decision(db: Session, decision_id: uuid.UUID) -> AwardDecision:
    d = db.get(AwardDecision, decision_id, with_for_update=True)
    if d is None:
        raise NotFound("NOT_FOUND", "No such award.")
    return d


def _issued(db: Session, d: AwardDecision) -> bool:
    return (
        db.scalar(
            select(Credential.id).where(
                Credential.award_decision_id == d.id, Credential.status == "issued"
            )
        )
        is not None
    )


def requeue(
    db: Session, actor: authz.Actor, decision_id: uuid.UUID, request_id: str | None = None
) -> dict[str, Any]:
    """Queue issuance again. Safe to repeat: issuance is idempotent on the decision."""
    authz.require_inst_admin(actor)
    d = _decision(db, decision_id)
    if d.status != "ready" or _issued(db, d):
        raise Conflict(
            "INVALID_STATE", "Only awards that are ready and not yet issued can be retried."
        )
    job = enqueue.defer(
        db,
        enqueue.ISSUE_CREDENTIAL,
        queue="issuance",
        institution_id=d.institution_id,
        args={"decision_id": str(d.id)},
        subject_type="award_decision",
        subject_id=d.id,
        queueing_lock=f"issue:{d.id}",
    )
    audit.record(
        db,
        action="reconciliation.requeue",
        resource_type="award_decision",
        resource_id=d.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"decision_id": str(d.id)},
    )
    return {"decision_id": str(d.id), "queued": job is not None}


def cancel(
    db: Session,
    actor: authz.Actor,
    decision_id: uuid.UUID,
    *,
    reason: str,
    request_id: str | None = None,
) -> AwardDecision:
    """Stop an award that should never be issued (for example, made in error)."""
    authz.require_inst_admin(actor)
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Invalid("REASON_REQUIRED", "Explain why this award is being cancelled.")
    d = _decision(db, decision_id)
    if d.status not in ("ready", "awaiting_confirmation") or _issued(db, d):
        raise Conflict(
            "INVALID_STATE", "Issued awards cannot be cancelled. Revoke the credential instead."
        )
    d.status = "rejected"
    d.rejection_reason = reason
    audit.record(
        db,
        action="reconciliation.cancel",
        resource_type="award_decision",
        resource_id=d.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"decision_id": str(d.id)},
    )
    return d
