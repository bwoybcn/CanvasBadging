# SPDX-License-Identifier: AGPL-3.0-or-later
"""Student collection, credential detail, sharing and LinkedIn (spec §8, §9; W6).

Only the holder sees or shares their own credentials. Any other credential id, including one in
another institution, is reported as "not found" so nothing is disclosed (spec scenario 10).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.api.deps import ClaimsDep, SettingsDep, SignerDep, TenantDb
from opencredential.api.errors import ApiError
from opencredential.authoring.preview import asset_data_url
from opencredential.credentials import linkedin
from opencredential.credentials import sharing as svc
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    BadgeAsset,
    Course,
    Credential,
    CredentialStatus,
    Institution,
    Issuer,
)
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient
from opencredential.verification.service import Verifier
from opencredential.verification.sources import DefaultSources, own_origins

router = APIRouter(prefix="/api/v1", tags=["student collection"])

CredentialState = Literal["active", "revoked", "suspended", "expired"]


class ImageOut(BaseModel):
    data_url: str | None
    alt_text: str


class CourseRef(BaseModel):
    id: uuid.UUID
    title: str


class ShareState(BaseModel):
    shared: bool
    url: str | None = None
    show_name: bool = False
    show_evidence: bool = False
    shared_since: datetime | None = None


class CredentialSummary(BaseModel):
    id: uuid.UUID
    credential_id: str
    name: str
    issuer_name: str
    issued_at: datetime | None
    valid_until: datetime | None
    status: CredentialState
    course: CourseRef | None
    image: ImageOut
    share: ShareState


def _image(db: Session, version: AchievementVersion) -> ImageOut:
    asset = db.get(BadgeAsset, version.asset_id) if version.asset_id else None
    return ImageOut(
        data_url=asset_data_url(asset),
        alt_text=asset.alt_text if asset else f"Badge image for {version.title}",
    )


def _course(db: Session, version: AchievementVersion) -> CourseRef | None:
    definition = db.get(AchievementDefinition, version.definition_id)
    course = db.get(Course, definition.course_id) if definition and definition.course_id else None
    return CourseRef(id=course.id, title=course.title) if course else None


def _share_state(db: Session, cred: Credential, settings: Settings) -> ShareState:
    grant = svc.active_grant(db, cred.id)
    if grant is None:
        return ShareState(shared=False)
    institution = db.get(Institution, cred.institution_id)
    assert institution is not None
    return ShareState(
        shared=True,
        url=svc.share_url(institution, settings, grant.share_id),
        show_name=grant.show_name,
        show_evidence=grant.show_evidence,
        shared_since=grant.created_at,
    )


def _summary(db: Session, cred: Credential, settings: Settings) -> CredentialSummary:
    version = db.get(AchievementVersion, cred.version_id)
    issuer = db.get(Issuer, cred.issuer_id)
    status = db.scalar(select(CredentialStatus).where(CredentialStatus.credential_id == cred.id))
    assert version is not None and issuer is not None
    return CredentialSummary(
        id=cred.id,
        credential_id=cred.credential_uri,
        name=version.title,
        issuer_name=issuer.name,
        issued_at=cred.issued_at,
        valid_until=cred.valid_until,
        status=svc.credential_state(cred, status),  # type: ignore[arg-type]
        course=_course(db, version),
        image=_image(db, version),
        share=_share_state(db, cred, settings),
    )


@router.get(
    "/learners/me/credentials",
    response_model=list[CredentialSummary],
    tags=["learners"],
    summary="My credential collection across all courses",
)
def my_credentials(
    claims: ClaimsDep, db: TenantDb, settings: SettingsDep
) -> list[CredentialSummary]:
    creds = db.scalars(
        select(Credential)
        .where(Credential.user_id == claims.user_id, Credential.status == "issued")
        .order_by(Credential.issued_at.desc())
    ).all()
    return [_summary(db, c, settings) for c in creds]


def _owned(db: Session, credential_id: uuid.UUID, user_id: uuid.UUID) -> Credential:
    try:
        return svc.owned_credential(db, credential_id, user_id)
    except svc.SharingError as exc:
        raise ApiError(404, exc.code, str(exc)) from exc


def verify_signed(signer: SignerClient, settings: Settings, vc: dict[str, Any]) -> dict[str, Any]:
    verifier = Verifier(signer, DefaultSources(own_origins(settings.public_base_url)))
    return verifier.verify(vc, now=datetime.now(UTC)).to_dict()


class CredentialDetail(CredentialSummary):
    description: str
    criteria: str
    achievement_type: str | None
    learning_outcomes: list[str]
    skills: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    issuer: dict[str, Any]
    verification: dict[str, Any]
    linkedin: dict[str, Any]


@router.get(
    "/credentials/{credential_id}",
    response_model=CredentialDetail,
    summary="Credential detail for its holder (spec §8.3)",
)
def detail(
    credential_id: uuid.UUID,
    claims: ClaimsDep,
    db: TenantDb,
    settings: SettingsDep,
    signer: SignerDep,
) -> CredentialDetail:
    cred = _owned(db, credential_id, claims.user_id)
    summary = _summary(db, cred, settings)
    version = db.get(AchievementVersion, cred.version_id)
    assert version is not None and cred.signed_json is not None
    # The holder sees every piece of evidence in their own credential.
    view = svc.public_view(db, cred, svc.ShareOptions(show_evidence=True), settings)
    return CredentialDetail(
        **summary.model_dump(),
        description=view["description"],
        criteria=view["criteria"],
        achievement_type=view["achievement_type"],
        learning_outcomes=list(version.learning_outcomes or []),
        skills=view["skills"],
        evidence=view["evidence"],
        issuer=view["issuer"],
        verification=verify_signed(signer, settings, cred.signed_json),
        linkedin=_linkedin(db, cred, view, summary.share, settings),
    )


def _linkedin(
    db: Session, cred: Credential, view: dict[str, Any], share: ShareState, settings: Settings
) -> dict[str, Any]:
    institution = db.get(Institution, cred.institution_id)
    org_id = (institution.policy or {}).get("linkedin_organization_id") if institution else None
    return {
        "fields": linkedin.fields(view, share.url),
        "add_to_profile_url": (
            linkedin.add_to_profile_url(view, share.url, organization_id=org_id)
            if share.url
            else None
        ),
        "needs_share": share.url is None,
        "note": (
            "LinkedIn opens its own 'Add license or certification' form with these values "
            "filled in where LinkedIn supports it. Check each field before saving. LinkedIn "
            "does not import the credential file itself; the Credential URL lets anyone verify it."
        ),
    }


class ShareIn(BaseModel):
    show_name: bool = False
    show_evidence: bool = False


class SharePreview(BaseModel):
    public: dict[str, Any]
    visible: list[dict[str, str]]
    never_shared: list[str]
    search_engines: str
    withdrawing: str


def _preview(db: Session, cred: Credential, body: ShareIn, settings: Settings) -> SharePreview:
    view = svc.public_view(db, cred, svc.ShareOptions(body.show_name, body.show_evidence), settings)
    return SharePreview(
        public=view,
        visible=svc.preview_fields(view),
        never_shared=list(svc.NEVER_SHARED),
        search_engines=(
            "The page asks search engines not to index it. Anyone you give the link to can open "
            "it and pass it on."
        ),
        withdrawing=(
            "You can stop sharing at any time. The link then stops working. Your badge stays "
            "valid, and copies of the credential file you have downloaded keep verifying."
        ),
    )


@router.post(
    "/credentials/{credential_id}/share/preview",
    response_model=SharePreview,
    summary="Exactly what a public link would show, before turning it on",
)
def share_preview(
    credential_id: uuid.UUID,
    body: ShareIn,
    claims: ClaimsDep,
    db: TenantDb,
    settings: SettingsDep,
) -> SharePreview:
    return _preview(db, _owned(db, credential_id, claims.user_id), body, settings)


class ShareOut(BaseModel):
    share: ShareState
    linkedin: dict[str, Any]
    preview: SharePreview


def _share_out(db: Session, cred: Credential, settings: Settings) -> ShareOut:
    state = _share_state(db, cred, settings)
    body = ShareIn(show_name=state.show_name, show_evidence=state.show_evidence)
    view = svc.public_view(db, cred, svc.ShareOptions(body.show_name, body.show_evidence), settings)
    return ShareOut(
        share=state,
        linkedin=_linkedin(db, cred, view, state, settings),
        preview=_preview(db, cred, body, settings),
    )


@router.get("/credentials/{credential_id}/share", response_model=ShareOut)
def get_share(
    credential_id: uuid.UUID, claims: ClaimsDep, db: TenantDb, settings: SettingsDep
) -> ShareOut:
    return _share_out(db, _owned(db, credential_id, claims.user_id), settings)


@router.put(
    "/credentials/{credential_id}/share",
    response_model=ShareOut,
    summary="Turn on public sharing, or change what the public link shows",
)
def put_share(
    credential_id: uuid.UUID,
    body: ShareIn,
    request: Request,
    claims: ClaimsDep,
    db: TenantDb,
    settings: SettingsDep,
) -> ShareOut:
    cred = _owned(db, credential_id, claims.user_id)
    try:
        svc.share(
            db,
            cred,
            svc.ShareOptions(body.show_name, body.show_evidence),
            actor_user_id=claims.user_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except svc.SharingError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    return _share_out(db, cred, settings)


@router.delete(
    "/credentials/{credential_id}/share",
    response_model=ShareOut,
    summary="Stop sharing. The link stops working; the credential is not revoked",
)
def delete_share(
    credential_id: uuid.UUID,
    request: Request,
    claims: ClaimsDep,
    db: TenantDb,
    settings: SettingsDep,
) -> ShareOut:
    cred = _owned(db, credential_id, claims.user_id)
    svc.unshare(
        db,
        cred,
        actor_user_id=claims.user_id,
        request_id=getattr(request.state, "request_id", None),
    )
    return _share_out(db, cred, settings)
