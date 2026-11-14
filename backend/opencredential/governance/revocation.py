# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authorised revocation with a reason, and revocation requests (spec §2.3, §7.6, §10.3).

Revocation flips the credential's bit in W4's Bitstring Status List, so a previously downloaded
copy verifies as revoked once the list is republished (scenario 8). Lecturers who are not
revokers can *request* revocation; a revoker approves (which revokes) or declines it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.authz.checks import credential_course, credential_definition
from opencredential.db.models import (
    AchievementVersion,
    Credential,
    CredentialStatus,
    Issuer,
    RevocationRequest,
    User,
)
from opencredential.errors import Conflict, Forbidden, Invalid, NotFound
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient, SignerError
from opencredential.status import service as status_service

REASON_CODES = (
    "issued_in_error",
    "academic_misconduct",
    "requirements_not_met",
    "learner_request",
    "other",
)


@dataclass(frozen=True)
class RevokeResult:
    credential_id: uuid.UUID
    changed: bool
    status_list_published: bool


def issued_credential(db: Session, credential_id: uuid.UUID) -> Credential:
    cred = db.get(Credential, credential_id)
    if cred is None or cred.status != "issued":
        raise NotFound("NOT_FOUND", "No such badge")
    return cred


def can_revoke(db: Session, actor: authz.Actor, cred: Credential) -> bool:
    issuer = db.get(Issuer, cred.issuer_id)
    assert issuer is not None
    rules = authz.institution_policy(db, actor.institution_id)
    return authz.can_revoke(
        db, actor, issuer, credential_course(db, cred), rules, credential_definition(db, cred)
    )


def require_revoke(db: Session, actor: authz.Actor, cred: Credential) -> None:
    if not can_revoke(db, actor, cred):
        raise Forbidden("FORBIDDEN", "You are not allowed to revoke this badge.")


def can_request(db: Session, actor: authz.Actor, cred: Credential) -> bool:
    """Course staff for the badge's course (or anyone who may revoke) can ask for revocation."""
    if can_revoke(db, actor, cred):
        return True
    course = credential_course(db, cred)
    if course is None:
        return False
    definition = credential_definition(db, cred)
    if course.badge_teams:
        # Badge teams: only the badge's own team (and admins over the course) may ask.
        return definition is not None and authz.can_award_definition(db, actor, definition)
    return authz.is_course_staff(db, actor, course)


def _validate(reason_code: str, reason_text: str) -> str:
    if reason_code not in REASON_CODES:
        raise Invalid("REASON_INVALID", f"Choose one of: {', '.join(REASON_CODES)}.")
    text = (reason_text or "").strip()
    if len(text) < 3:
        raise Invalid("REASON_REQUIRED", "Explain why the badge is being revoked.")
    return text


def revoke(
    db: Session,
    actor: authz.Actor,
    credential_id: uuid.UUID,
    *,
    reason_code: str,
    reason_text: str,
    signer: SignerClient | None,
    settings: Settings,
    request_id: str | None = None,
) -> RevokeResult:
    cred = issued_credential(db, credential_id)
    require_revoke(db, actor, cred)
    text = _validate(reason_code, reason_text)
    result = status_service.revoke(
        db,
        cred.id,
        reason_code=reason_code,
        reason_text=text,
        actor_user_id=actor.user_id,
        request_id=request_id,
    )
    published = False
    if result.status_list_id is not None and result.changed:
        published = _publish(db, cred.institution_id, result.status_list_id, signer, settings)
    # Any open request for this credential is settled by the revocation.
    for req in db.scalars(
        select(RevocationRequest).where(
            RevocationRequest.credential_id == cred.id, RevocationRequest.status == "open"
        )
    ):
        req.status = "approved"
        req.decided_by = actor.user_id
    return RevokeResult(cred.id, result.changed, published)


def _publish(
    db: Session,
    institution_id: uuid.UUID,
    status_list_id: uuid.UUID,
    signer: SignerClient | None,
    settings: Settings,
) -> bool:
    """Republish now if the signer is reachable; otherwise queue it (the job retries)."""
    if signer is not None:
        try:
            with db.begin_nested():
                status_service.publish(db, status_list_id, signer, settings)
            return True
        except (SignerError, status_service.StatusError):
            pass
    from opencredential.jobs.tasks import defer_publish

    defer_publish(institution_id, status_list_id)
    return False


# ---- requests ------------------------------------------------------------------------------


def request_revocation(
    db: Session,
    actor: authz.Actor,
    credential_id: uuid.UUID,
    *,
    reason: str,
    request_id: str | None = None,
) -> RevocationRequest:
    cred = issued_credential(db, credential_id)
    if not can_request(db, actor, cred):
        raise NotFound("NOT_FOUND", "No such badge")  # no disclosure to outsiders
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Invalid("REASON_REQUIRED", "Explain why this badge should be revoked.")
    status = db.scalar(select(CredentialStatus).where(CredentialStatus.credential_id == cred.id))
    if status is not None and status.state == "revoked":
        raise Conflict("ALREADY_REVOKED", "This badge is already revoked.")
    existing = db.scalar(
        select(RevocationRequest).where(
            RevocationRequest.credential_id == cred.id, RevocationRequest.status == "open"
        )
    )
    if existing is not None:
        return existing
    req = RevocationRequest(
        institution_id=actor.institution_id,
        credential_id=cred.id,
        requested_by=actor.user_id,
        reason=reason,
        status="open",
    )
    db.add(req)
    db.flush()
    audit.record(
        db,
        action="revocation.request",
        resource_type="credential",
        resource_id=cred.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"request_id": str(req.id)},
    )
    return req


def list_requests(db: Session, actor: authz.Actor, status: str | None = "open") -> list[dict]:  # type: ignore[type-arg]
    q = select(RevocationRequest).order_by(RevocationRequest.created_at.desc()).limit(500)
    if status:
        q = q.where(RevocationRequest.status == status)
    out = []
    for req in db.scalars(q):
        cred = db.get(Credential, req.credential_id)
        if cred is None:
            continue
        decidable = can_revoke(db, actor, cred)
        if not decidable and req.requested_by != actor.user_id:
            continue
        version = db.get(AchievementVersion, cred.version_id)
        learner = db.get(User, cred.user_id)
        requester = db.get(User, req.requested_by)
        course = credential_course(db, cred)
        out.append(
            {
                "id": str(req.id),
                "credential_id": str(cred.id),
                "badge_title": version.title if version else None,
                "course_title": course.title if course else None,
                "learner_name": learner.display_name if learner else None,
                "requested_by": requester.display_name if requester else None,
                "reason": req.reason,
                "status": req.status,
                "requested_at": req.created_at,
                "can_decide": decidable,
            }
        )
    return out


def decide_request(
    db: Session,
    actor: authz.Actor,
    request_uuid: uuid.UUID,
    *,
    approve: bool,
    reason_code: str = "other",
    note: str | None = None,
    signer: SignerClient | None,
    settings: Settings,
    request_id: str | None = None,
) -> RevocationRequest:
    req = db.get(RevocationRequest, request_uuid, with_for_update=True)
    if req is None:
        raise NotFound("NOT_FOUND", "No such request.")
    cred = db.get(Credential, req.credential_id)
    assert cred is not None
    require_revoke(db, actor, cred)
    if req.status != "open":
        raise Conflict("INVALID_STATE", f"This request is already {req.status}.")
    if approve:
        revoke(
            db,
            actor,
            cred.id,
            reason_code=reason_code,
            reason_text=note or req.reason,
            signer=signer,
            settings=settings,
            request_id=request_id,
        )
        req.status = "approved"
    else:
        req.status = "rejected"
    req.decided_by = actor.user_id
    audit.record(
        db,
        action=f"revocation.request_{req.status}",
        resource_type="credential",
        resource_id=cred.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"request_id": str(req.id), "decided_at": datetime.now(UTC).isoformat()},
    )
    return req
