# SPDX-License-Identifier: AGPL-3.0-or-later
"""Credential download, revocation and issuer key management (W4 slice of the v1 API)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from opencredential.api.deps import (
    ActorDep,
    ClaimsDep,
    RequestIdDep,
    SettingsDep,
    SignerDep,
    TenantDb,
)
from opencredential.api.errors import ApiError
from opencredential.authz.checks import may_revoke, require_key_manager
from opencredential.db.models import (
    AchievementVersion,
    Credential,
    CredentialStatus,
    Issuer,
    IssuerKey,
)
from opencredential.governance import revocation
from opencredential.institutions import keys as key_service
from opencredential.status.compromise import respond_to_compromise

router = APIRouter(prefix="/api/v1", tags=["credentials"])


class CredentialSummary(BaseModel):
    id: uuid.UUID
    credential_id: str
    name: str
    issuer_name: str
    issued_at: datetime | None
    valid_until: datetime | None
    status: Literal["active", "revoked", "expired"]


def _state(cred: Credential, status: CredentialStatus | None) -> str:
    if status is not None and status.state == "revoked":
        return "revoked"
    if cred.valid_until is not None and cred.valid_until < datetime.now(UTC):
        return "expired"
    return "active"


@router.get("/learners/me/credentials", response_model=list[CredentialSummary])
def my_credentials(claims: ClaimsDep, db: TenantDb) -> list[CredentialSummary]:
    rows = db.execute(
        select(Credential, CredentialStatus, AchievementVersion, Issuer)
        .join(AchievementVersion, AchievementVersion.id == Credential.version_id)
        .join(Issuer, Issuer.id == Credential.issuer_id)
        .outerjoin(CredentialStatus, CredentialStatus.credential_id == Credential.id)
        .where(Credential.user_id == claims.user_id, Credential.status == "issued")
        .order_by(Credential.issued_at.desc())
    ).all()
    return [
        CredentialSummary(
            id=c.id,
            credential_id=c.credential_uri,
            name=v.title,
            issuer_name=i.name,
            issued_at=c.issued_at,
            valid_until=c.valid_until,
            status=_state(c, s),  # type: ignore[arg-type]
        )
        for c, s, v, i in rows
    ]


@router.get(
    "/credentials/{credential_id}/export",
    summary="Download the signed Open Badges 3.0 credential",
    response_class=Response,
    responses={200: {"content": {"application/ld+json": {}}}},
)
def export(credential_id: uuid.UUID, claims: ClaimsDep, db: TenantDb) -> Response:
    cred = db.get(Credential, credential_id)
    if cred is None or cred.status != "issued" or cred.signed_json is None:
        raise ApiError(404, "NOT_FOUND", "No such credential")
    if cred.user_id != claims.user_id and not may_revoke(db, claims.user_id, cred):
        # Scenario 10: someone else's credential looks exactly like a missing one.
        raise ApiError(404, "NOT_FOUND", "No such credential")
    version = db.get(AchievementVersion, cred.version_id)
    stem = "".join(ch if ch.isalnum() else "-" for ch in (version.title if version else "badge"))
    date = cred.issued_at.date().isoformat() if cred.issued_at else "credential"
    return Response(
        json.dumps(cred.signed_json, indent=2, ensure_ascii=False),
        media_type="application/ld+json",
        headers={
            "Content-Disposition": f'attachment; filename="{stem.strip("-").lower()}-{date}.json"',
            "Cache-Control": "no-store",
        },
    )


class RevokeIn(BaseModel):
    reason_code: Literal[
        "issued_in_error",
        "academic_misconduct",
        "requirements_not_met",
        "learner_request",
        "other",
    ]
    reason_text: str = Field(min_length=3, max_length=2000)


class RevokeOut(BaseModel):
    credential_id: uuid.UUID
    state: str
    changed: bool
    status_list_published: bool


@router.post("/credentials/{credential_id}/revoke", response_model=RevokeOut)
def revoke(
    credential_id: uuid.UUID,
    body: RevokeIn,
    db: TenantDb,
    actor: ActorDep,
    rid: RequestIdDep,
    signer: SignerDep,
    settings: SettingsDep,
) -> RevokeOut:
    """Authorised revocation with a reason (spec §10.3: roles in the institution policy)."""
    result = revocation.revoke(
        db,
        actor,
        credential_id,
        reason_code=body.reason_code,
        reason_text=body.reason_text,
        signer=signer,
        settings=settings,
        request_id=rid,
    )
    return RevokeOut(
        credential_id=result.credential_id,
        state="revoked",
        changed=result.changed,
        status_list_published=result.status_list_published,
    )


class KeyOut(BaseModel):
    id: uuid.UUID
    verification_method_id: str
    public_key_multibase: str
    state: str
    activated_at: datetime | None
    retired_at: datetime | None
    revoked_at: datetime | None
    is_dev: bool


def _key_out(k: IssuerKey) -> KeyOut:
    return KeyOut(
        id=k.id,
        verification_method_id=k.verification_method_id,
        public_key_multibase=k.public_key_multibase,
        state=k.state,
        activated_at=k.activated_at,
        retired_at=k.retired_at,
        revoked_at=k.revoked_at,
        is_dev=k.is_dev,
    )


def _issuer(db: TenantDb, issuer_id: uuid.UUID) -> Issuer:
    issuer = db.get(Issuer, issuer_id)
    if issuer is None:
        raise ApiError(404, "NOT_FOUND", "No such issuer")
    return issuer


@router.get("/issuers/{issuer_id}/keys", response_model=list[KeyOut], tags=["issuers"])
def list_keys(issuer_id: uuid.UUID, claims: ClaimsDep, db: TenantDb) -> list[KeyOut]:
    require_key_manager(db, claims.user_id)
    _issuer(db, issuer_id)
    keys = db.scalars(
        select(IssuerKey).where(IssuerKey.issuer_id == issuer_id).order_by(IssuerKey.created_at)
    )
    return [_key_out(k) for k in keys]


@router.post("/issuers/{issuer_id}/keys/rotate", response_model=KeyOut, tags=["issuers"])
def rotate_key(issuer_id: uuid.UUID, claims: ClaimsDep, db: TenantDb, signer: SignerDep) -> KeyOut:
    require_key_manager(db, claims.user_id)
    issuer = _issuer(db, issuer_id)
    try:
        key = key_service.rotate(db, issuer, signer, actor_user_id=claims.user_id)
    except key_service.KeyLifecycleError as exc:
        raise ApiError(409, "KEY_LIFECYCLE", str(exc)) from exc
    return _key_out(key)


class CompromiseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class CompromiseOut(BaseModel):
    revoked_key_id: uuid.UUID
    replacement_key_id: uuid.UUID | None
    credentials_revoked: int
    status_lists_republished: int


@router.post(
    "/issuers/{issuer_id}/keys/{key_id}/compromise",
    response_model=CompromiseOut,
    tags=["issuers"],
    summary="Key-compromise response (docs/security/key-compromise.md)",
)
def compromise_key(
    issuer_id: uuid.UUID,
    key_id: uuid.UUID,
    body: CompromiseIn,
    claims: ClaimsDep,
    db: TenantDb,
    signer: SignerDep,
    settings: SettingsDep,
) -> CompromiseOut:
    require_key_manager(db, claims.user_id)
    _issuer(db, issuer_id)
    key = db.get(IssuerKey, key_id)
    if key is None or key.issuer_id != issuer_id:
        raise ApiError(404, "NOT_FOUND", "No such key")
    try:
        r = respond_to_compromise(
            db, key, signer, settings, reason=body.reason, actor_user_id=claims.user_id
        )
    except key_service.KeyLifecycleError as exc:
        raise ApiError(409, "KEY_LIFECYCLE", str(exc)) from exc
    return CompromiseOut(
        revoked_key_id=r.revoked_key_id,
        replacement_key_id=r.replacement_key_id,
        credentials_revoked=r.credentials_revoked,
        status_lists_republished=r.status_lists_republished,
    )
