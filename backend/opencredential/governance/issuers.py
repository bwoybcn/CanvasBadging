# SPDX-License-Identifier: AGPL-3.0-or-later
"""Issuer records at university, faculty and department level, with explicit delegated
authority (spec §10.2).

Creating an issuer makes a *draft* record only: it cannot sign anything and is not offered to
authors. An institution administrator must then **authorise** it, recording the basis of its
authority (for example a Senate resolution). Authorisation creates the issuer's identity: a
``did:web`` on the institution's verification host, or a development ``did:key`` when no host
is configured outside production. Delegations then say which courses and org units may use it.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import (
    Course,
    Institution,
    Issuer,
    IssuerDelegation,
    IssuerKey,
    OrgUnit,
)
from opencredential.db.models.issuers import ISSUER_LEVELS
from opencredential.errors import Conflict, Forbidden, Invalid, NotFound
from opencredential.institutions import keys as key_service
from opencredential.institutions.identity import did_web_for
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
PENDING_DID_PREFIX = "urn:opencredential:issuer-pending:"
#: Levels a department administrator may create (within their own org units).
DEPT_LEVELS = ("department", "programme")


def get(db: Session, issuer_id: uuid.UUID) -> Issuer:
    issuer = db.get(Issuer, issuer_id)
    if issuer is None:
        raise NotFound("NOT_FOUND", "No such issuer.")
    return issuer


def can_manage(db: Session, actor: authz.Actor, issuer: Issuer) -> bool:
    if actor.is_inst_admin:
        return True
    return issuer.org_unit_id is not None and authz.is_dept_admin_over(
        db, actor, issuer.org_unit_id
    )


def require_manage(db: Session, actor: authz.Actor, issuer: Issuer) -> None:
    if not can_manage(db, actor, issuer):
        raise Forbidden(
            "OUT_OF_SCOPE", "This issuer is outside the part of the institution you manage."
        )


def out(db: Session, issuer: Issuer) -> dict[str, Any]:
    unit = db.get(OrgUnit, issuer.org_unit_id) if issuer.org_unit_id else None
    key = key_service.active_key(db, issuer.id)
    delegations = db.scalars(
        select(IssuerDelegation).where(
            IssuerDelegation.issuer_id == issuer.id, IssuerDelegation.revoked_at.is_(None)
        )
    ).all()
    return {
        "id": str(issuer.id),
        "name": issuer.name,
        "slug": issuer.slug,
        "level": issuer.level,
        "org_unit_id": str(issuer.org_unit_id) if issuer.org_unit_id else None,
        "org_unit_name": unit.name if unit else None,
        "url": issuer.url,
        "email": issuer.email,
        "description": issuer.description,
        "did": None if issuer.did.startswith(PENDING_DID_PREFIX) else issuer.did,
        "status": issuer.status,
        "authority_basis": issuer.authority_basis,
        "authorised_at": issuer.approved_at,
        "may_issue": authz.org_unit_may_issue(db, issuer.org_unit_id),
        "active_key": (
            {"id": str(key.id), "activated_at": key.activated_at, "is_dev": key.is_dev}
            if key
            else None
        ),
        "delegations": [_delegation_out(db, d) for d in delegations],
    }


def _delegation_out(db: Session, d: IssuerDelegation) -> dict[str, Any]:
    target = db.get(OrgUnit if d.scope_type == "org_unit" else Course, d.scope_id)
    name = getattr(target, "name", None) or getattr(target, "title", None)
    return {
        "id": str(d.id),
        "scope_type": d.scope_type,
        "scope_id": str(d.scope_id),
        "scope_name": name,
    }


def list_for(db: Session, actor: authz.Actor) -> list[dict[str, Any]]:
    authz.require_admin(actor)
    issuers = db.scalars(select(Issuer).order_by(Issuer.name)).all()
    return [out(db, i) for i in issuers if can_manage(db, actor, i)]


def create(
    db: Session,
    actor: authz.Actor,
    *,
    name: str,
    slug: str,
    level: str,
    org_unit_id: uuid.UUID | None,
    url: str | None = None,
    email: str | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> Issuer:
    authz.require_admin(actor)
    if level not in ISSUER_LEVELS:
        raise Invalid("LEVEL_INVALID", f"Level must be one of: {', '.join(ISSUER_LEVELS)}.")
    if not actor.is_inst_admin:
        if level not in DEPT_LEVELS:
            raise Forbidden(
                "OUT_OF_SCOPE",
                "Department administrators can create department or programme issuers only.",
            )
        authz.require_manage_org_unit(db, actor, org_unit_id)
    if level != "university" and org_unit_id is None:
        raise Invalid("ORG_UNIT_REQUIRED", "Choose the faculty or department this issuer acts for.")
    if org_unit_id is not None and db.get(OrgUnit, org_unit_id) is None:
        raise NotFound("ORG_UNIT_NOT_FOUND", "No such faculty or department.")
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise Invalid(
            "SLUG_INVALID", "The short name must be 2-63 lowercase letters, digits or hyphens."
        )
    if db.scalar(select(Issuer.id).where(Issuer.slug == slug)) is not None:
        raise Conflict("SLUG_TAKEN", "Another issuer already uses that short name.")
    name = (name or "").strip()
    if not 3 <= len(name) <= 200:
        raise Invalid("NAME_INVALID", "The issuer name must be 3 to 200 characters.")
    if url and not url.startswith("https://"):
        raise Invalid("URL_INVALID", "The issuer's web address must start with https://.")
    issuer_id = uuid.uuid4()
    issuer = Issuer(
        id=issuer_id,
        institution_id=actor.institution_id,
        org_unit_id=org_unit_id,
        slug=slug,
        name=name,
        url=url,
        email=email,
        description=description,
        level=level,
        did=f"{PENDING_DID_PREFIX}{issuer_id}",
        status="draft",
    )
    db.add(issuer)
    db.flush()
    audit.record(
        db,
        action="issuer.create",
        resource_type="issuer",
        resource_id=issuer.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"level": level, "org_unit_id": str(org_unit_id) if org_unit_id else None},
    )
    return issuer


def update(
    db: Session,
    actor: authz.Actor,
    issuer: Issuer,
    changes: dict[str, Any],
    request_id: str | None = None,
) -> Issuer:
    require_manage(db, actor, issuer)
    allowed = {"name", "url", "email", "description"}
    clean = {k: v for k, v in changes.items() if k in allowed}
    if "name" in clean and not 3 <= len((clean["name"] or "").strip()) <= 200:
        raise Invalid("NAME_INVALID", "The issuer name must be 3 to 200 characters.")
    if clean.get("url") and not str(clean["url"]).startswith("https://"):
        raise Invalid("URL_INVALID", "The issuer's web address must start with https://.")
    for k, v in clean.items():
        setattr(issuer, k, v)
    if clean:
        audit.record(
            db,
            action="issuer.update",
            resource_type="issuer",
            resource_id=issuer.id,
            institution_id=actor.institution_id,
            actor_user_id=actor.user_id,
            request_id=request_id,
            data={"fields": sorted(clean)},
        )
    return issuer


def authorise(
    db: Session,
    actor: authz.Actor,
    issuer: Issuer,
    *,
    authority_basis: str,
    signer: SignerClient,
    settings: Settings,
    request_id: str | None = None,
) -> Issuer:
    """Record the explicit delegation of authority and give the issuer a signing identity."""
    authz.require_inst_admin(actor)
    basis = (authority_basis or "").strip()
    if len(basis) < 10:
        raise Invalid(
            "AUTHORITY_REQUIRED",
            "Record the basis of this issuer's authority (for example the committee decision).",
        )
    if not authz.org_unit_may_issue(db, issuer.org_unit_id):
        raise Conflict(
            "ISSUING_NOT_ALLOWED",
            "This issuer's department is not allowed to issue badges. Change that first.",
        )
    if issuer.status == "active":
        raise Conflict("INVALID_STATE", "This issuer is already authorised.")
    now = datetime.now(UTC)
    if key_service.active_key(db, issuer.id) is None:
        _create_identity(db, issuer, signer, settings, actor)
    issuer.status = "active"
    issuer.authority_basis = basis
    issuer.approved_by = actor.user_id
    issuer.approved_at = now
    audit.record(
        db,
        action="issuer.authorise",
        resource_type="issuer",
        resource_id=issuer.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"level": issuer.level, "status": "active"},
    )
    return issuer


def _create_identity(
    db: Session, issuer: Issuer, signer: SignerClient, settings: Settings, actor: authz.Actor
) -> None:
    inst = db.get(Institution, issuer.institution_id)
    assert inst is not None
    if inst.verification_host:
        if issuer.did.startswith(PENDING_DID_PREFIX):
            issuer.did = did_web_for(inst.verification_host, issuer.slug)
            db.flush()
        key = key_service.create_key(db, issuer, signer, dev=False)
    else:
        if settings.is_production:
            raise Conflict(
                "VERIFICATION_HOST_REQUIRED",
                "Set the institution's public verification domain before authorising issuers.",
            )
        key_id = uuid.uuid4()
        generated = signer.create_key(key_id, dev=True)
        issuer.did = generated.did
        db.flush()
        key = IssuerKey(
            id=key_id,
            institution_id=issuer.institution_id,
            issuer_id=issuer.id,
            verification_method_id=generated.verification_method_id,
            public_key_multibase=generated.public_key_multibase,
            state="pending",
            is_dev=True,
        )
        db.add(key)
        db.flush()
    key_service.activate(db, key, signer, actor_user_id=actor.user_id)


def suspend(
    db: Session,
    actor: authz.Actor,
    issuer: Issuer,
    *,
    reason: str,
    request_id: str | None = None,
) -> Issuer:
    """Stop new awards under this issuer. Credentials already issued stay valid (revoke them
    separately if they must stop verifying)."""
    authz.require_inst_admin(actor)
    if len((reason or "").strip()) < 5:
        raise Invalid("REASON_REQUIRED", "Explain why this issuer is being suspended.")
    if issuer.status != "active":
        raise Conflict("INVALID_STATE", f"This issuer is {issuer.status}.")
    issuer.status = "suspended"
    audit.record(
        db,
        action="issuer.suspend",
        resource_type="issuer",
        resource_id=issuer.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"status": "suspended"},
    )
    return issuer


# ---- delegations ----------------------------------------------------------------------------


def delegate(
    db: Session,
    actor: authz.Actor,
    issuer: Issuer,
    *,
    scope_type: str,
    scope_id: uuid.UUID,
    request_id: str | None = None,
) -> IssuerDelegation:
    """Let a course or org unit author badges under ``issuer``."""
    require_manage(db, actor, issuer)
    if scope_type == "org_unit":
        unit = db.get(OrgUnit, scope_id)
        if unit is None:
            raise NotFound("ORG_UNIT_NOT_FOUND", "No such faculty or department.")
        authz.require_manage_org_unit(db, actor, unit.id)
    elif scope_type == "course":
        course = db.get(Course, scope_id)
        if course is None:
            raise NotFound("COURSE_NOT_FOUND", "No such course.")
        if not actor.is_inst_admin:
            authz.require_manage_org_unit(db, actor, course.org_unit_id)
    else:
        raise Invalid("SCOPE_INVALID", "Delegate to a course or an org unit.")
    existing = db.scalar(
        select(IssuerDelegation).where(
            IssuerDelegation.issuer_id == issuer.id,
            IssuerDelegation.scope_type == scope_type,
            IssuerDelegation.scope_id == scope_id,
            IssuerDelegation.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    d = IssuerDelegation(
        institution_id=actor.institution_id,
        issuer_id=issuer.id,
        scope_type=scope_type,
        scope_id=scope_id,
        granted_by=actor.user_id,
    )
    db.add(d)
    db.flush()
    audit.record(
        db,
        action="issuer.delegate",
        resource_type="issuer",
        resource_id=issuer.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"scope_type": scope_type, "scope_id": str(scope_id)},
    )
    return d


def undelegate(
    db: Session,
    actor: authz.Actor,
    delegation_id: uuid.UUID,
    request_id: str | None = None,
) -> None:
    d = db.get(IssuerDelegation, delegation_id)
    if d is None or d.revoked_at is not None:
        raise NotFound("NOT_FOUND", "No such delegation.")
    issuer = get(db, d.issuer_id)
    require_manage(db, actor, issuer)
    d.revoked_at = datetime.now(UTC)
    audit.record(
        db,
        action="issuer.undelegate",
        resource_type="issuer",
        resource_id=issuer.id,
        institution_id=actor.institution_id,
        actor_user_id=actor.user_id,
        request_id=request_id,
        data={"scope_type": d.scope_type, "scope_id": str(d.scope_id)},
    )
