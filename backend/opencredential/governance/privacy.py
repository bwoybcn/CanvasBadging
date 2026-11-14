# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal-data export and erasure (spec §12.5, §15.2; UK GDPR arts. 15, 17 and 20).

Three things are deliberately **separate operations** (spec §12.5):

* *Erasing a person's data* (this module) removes their name, email, Canvas identifiers, roles,
  Canvas progress snapshots and eligibility history, and cancels awards not yet issued.
* *Revoking a credential* (:mod:`opencredential.governance.revocation`) changes what verifiers
  see. Erasure does **not** revoke: the learner holds the signed credential and may still need
  it, and the credential itself contains no name (only a salted hash of their email).
* *Withdrawing public sharing* (the learner's share links, W6) stops the public page.

Issued credential records are kept because they are immutable signed statements that the
institution must still be able to revoke and answer for (see docs/privacy/erasure.md).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import (
    AchievementVersion,
    AwardDecision,
    Credential,
    CredentialEvidence,
    CredentialStatus,
    EligibilityEvaluation,
    ExternalIdentity,
    LmsModuleProgress,
    LmsSubmission,
    ManualRuleApproval,
    Membership,
    ShareGrant,
    User,
)
from opencredential.errors import Conflict, Forbidden, Invalid, NotFound

ERASED_REASON = "Not issued: the learner's personal data was erased."


def _n(result: Any) -> int:
    """Rows affected by a DML statement."""
    return int(getattr(result, "rowcount", 0) or 0)


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return None
    return value


def _row(obj: Any, exclude: tuple[str, ...] = ("institution_id",)) -> dict[str, Any]:
    return {
        c.key: _plain(getattr(obj, c.key)) for c in obj.__table__.columns if c.key not in exclude
    }


def _user(db: Session, actor: authz.Actor, user_id: uuid.UUID, *, self_ok: bool) -> User:
    if not (actor.is_inst_admin or (self_ok and actor.user_id == user_id)):
        raise Forbidden("FORBIDDEN", "Only institution administrators can do that.")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "No such person.")
    return user


def export(
    db: Session, actor: authz.Actor, user_id: uuid.UUID, request_id: str | None = None
) -> dict[str, Any]:
    """Everything OpenCredential holds about one person, in a portable JSON document."""
    user = _user(db, actor, user_id, self_ok=True)

    def rows(model: Any, *conds: Any) -> list[dict[str, Any]]:
        return [_row(r) for r in db.scalars(select(model).where(*conds))]

    creds = list(db.scalars(select(Credential).where(Credential.user_id == user_id)))
    cred_ids = [c.id for c in creds]
    titles = {
        v.id: v.title
        for v in db.scalars(
            select(AchievementVersion).where(
                AchievementVersion.id.in_({c.version_id for c in creds})
            )
        )
    }
    doc = {
        "format": "opencredential.personal-data-export/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": _row(user),
        "external_identities": rows(ExternalIdentity, ExternalIdentity.user_id == user_id),
        "roles": rows(Membership, Membership.user_id == user_id),
        "canvas_module_progress": rows(LmsModuleProgress, LmsModuleProgress.user_id == user_id),
        "canvas_submissions": rows(LmsSubmission, LmsSubmission.user_id == user_id),
        "eligibility_evaluations": rows(
            EligibilityEvaluation, EligibilityEvaluation.user_id == user_id
        ),
        "requirement_approvals": rows(ManualRuleApproval, ManualRuleApproval.user_id == user_id),
        "award_decisions": rows(AwardDecision, AwardDecision.user_id == user_id),
        "credentials": [
            {
                **_row(c, exclude=("institution_id", "recipient_salt")),
                "badge_title": titles.get(c.version_id),
            }
            for c in creds
        ],
        "credential_status": rows(CredentialStatus, CredentialStatus.credential_id.in_(cred_ids)),
        "evidence": rows(CredentialEvidence, CredentialEvidence.credential_id.in_(cred_ids)),
        "share_links": rows(ShareGrant, ShareGrant.credential_id.in_(cred_ids)),
    }
    audit.record(
        db,
        action="privacy.export",
        resource_type="user",
        resource_id=user.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"user_id": str(user.id)},
    )
    return doc


def erase(
    db: Session,
    actor: authz.Actor,
    user_id: uuid.UUID,
    *,
    confirm: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Erase a person's personal data. ``confirm`` must be the literal word ``ERASE``."""
    user = _user(db, actor, user_id, self_ok=False)
    if confirm != "ERASE":
        raise Invalid("CONFIRMATION_REQUIRED", "Type ERASE to confirm.")
    if user.id == actor.user_id:
        raise Conflict("SELF_ERASURE", "Ask another administrator to erase your own data.")
    if user.status == "deleted":
        raise Conflict("ALREADY_ERASED", "This person's data has already been erased.")
    now = datetime.now(UTC)
    counts: dict[str, int] = {}

    # Cancel awards that have not become credentials yet: nothing new is issued afterwards.
    pending = list(
        db.scalars(
            select(AwardDecision).where(
                AwardDecision.user_id == user_id,
                AwardDecision.status.in_(("awaiting_confirmation", "ready")),
                ~select(Credential.id)
                .where(
                    Credential.award_decision_id == AwardDecision.id,
                    Credential.status == "issued",
                )
                .exists(),
            )
        )
    )
    for d in pending:
        d.status = "rejected"
        d.rejection_reason = ERASED_REASON
    counts["awards_cancelled"] = len(pending)
    # A credential row may already be waiting for its signature (signer outage): abandon it so
    # neither the issuing job nor reconciliation can sign it after the erasure.
    counts["unsigned_credentials_cancelled"] = _n(
        db.execute(
            update(Credential)
            .where(Credential.user_id == user_id, Credential.status == "pending_signature")
            .values(status="failed", last_error="award cancelled: personal data erased")
        )
    )

    referenced = select(AwardDecision.evaluation_id).where(AwardDecision.evaluation_id.is_not(None))
    counts["evaluations_deleted"] = _n(
        db.execute(
            delete(EligibilityEvaluation).where(
                EligibilityEvaluation.user_id == user_id,
                EligibilityEvaluation.id.not_in(referenced),
            )
        )
    )
    counts["evaluations_minimised"] = _n(
        db.execute(
            update(EligibilityEvaluation)
            .where(EligibilityEvaluation.user_id == user_id)
            .values(detail={})
        )
    )
    counts["canvas_progress_deleted"] = _n(
        db.execute(delete(LmsModuleProgress).where(LmsModuleProgress.user_id == user_id))
    )
    counts["canvas_submissions_deleted"] = _n(
        db.execute(delete(LmsSubmission).where(LmsSubmission.user_id == user_id))
    )
    counts["approval_notes_cleared"] = _n(
        db.execute(
            update(ManualRuleApproval)
            .where(ManualRuleApproval.user_id == user_id, ManualRuleApproval.note.is_not(None))
            .values(note=None)
        )
    )
    counts["identities_deleted"] = _n(
        db.execute(delete(ExternalIdentity).where(ExternalIdentity.user_id == user_id))
    )
    counts["roles_ended"] = _n(
        db.execute(
            update(Membership)
            .where(Membership.user_id == user_id, Membership.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    )
    user.display_name = None
    user.given_name = None
    user.family_name = None
    user.email = None
    user.email_verified_by = None
    user.status = "deleted"
    user.deleted_at = now

    creds = list(db.scalars(select(Credential.id).where(Credential.user_id == user_id)))
    counts["credentials_kept"] = len(creds)
    # Public share pages are withdrawn: after erasure the person can no longer sign in to do it
    # themselves. The credentials stay valid and downloaded copies still verify.
    counts["share_links_withdrawn"] = _n(
        db.execute(
            update(ShareGrant)
            .where(ShareGrant.credential_id.in_(creds), ShareGrant.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    )
    audit.record(
        db,
        action="privacy.erase",
        resource_type="user",
        resource_id=user.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"user_id": str(user.id), "counts": counts},
    )
    return counts
