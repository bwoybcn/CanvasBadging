# SPDX-License-Identifier: AGPL-3.0-or-later
"""Institution configuration, credential governance policy and retention (spec §10.1, §10.3,
§12.5). Only institution administrators change these; every change is audited."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.authz import policy as authz
from opencredential.db.models import BadgeAsset, Institution, Issuer, IssuerKey
from opencredential.db.models.tenancy import DEFAULT_POLICY, DEFAULT_RETENTION
from opencredential.errors import Conflict, Invalid

HOST_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(:\d{2,5})?$"
)
COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

CONFIG_FIELDS = (
    "name",
    "description",
    "website_url",
    "logo_asset_id",
    "branding",
    "verification_host",
    "categories",
    "linkedin_org_id",
    "linkedin_org_name",
)

#: Retention keys an administrator can change, with (minimum, maximum).
RETENTION_BOUNDS: dict[str, tuple[int, int]] = {
    "snapshot_days_after_course_end": (30, 3650),
    "evaluation_days": (30, 3650),
    "failed_job_days": (7, 3650),
    "audit_event_years": (1, 30),
}

POLICY_ROLE_LISTS = {
    "approver_roles": authz.APPROVER_ROLES,
    "revokers": authz.REVOKER_ROLES,
}


def current(db: Session, actor: authz.Actor) -> Institution:
    inst = db.get(Institution, actor.institution_id)
    assert inst is not None
    return inst


def config_out(inst: Institution) -> dict[str, Any]:
    return {
        "id": str(inst.id),
        "slug": inst.slug,
        "name": inst.name,
        "description": inst.description,
        "website_url": inst.website_url,
        "logo_asset_id": str(inst.logo_asset_id) if inst.logo_asset_id else None,
        "branding": inst.branding or {},
        "verification_host": inst.verification_host,
        "categories": list(inst.categories or []),
        "linkedin_org_id": inst.linkedin_org_id,
        "linkedin_org_name": inst.linkedin_org_name,
        "is_demo": inst.is_demo,
    }


def update_config(
    db: Session, actor: authz.Actor, changes: dict[str, Any], request_id: str | None = None
) -> Institution:
    authz.require_inst_admin(actor)
    inst = current(db, actor)
    clean: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in CONFIG_FIELDS:
            continue
        if key == "name":
            value = (value or "").strip()
            if not 2 <= len(value) <= 200:
                raise Invalid("NAME_INVALID", "The institution name must be 2 to 200 characters.")
        elif key == "website_url" and value:
            if not str(value).startswith("https://"):
                raise Invalid("URL_INVALID", "The website must be an https:// address.")
        elif key == "verification_host":
            value = (value or "").strip().lower() or None
            if value is not None and not HOST_RE.match(value):
                raise Invalid(
                    "HOST_INVALID",
                    "Enter a host name such as badges.example.ac.uk (no https://, no path).",
                )
            if value != inst.verification_host and _did_web_issuers_with_keys(db):
                raise Conflict(
                    "VERIFICATION_HOST_IN_USE",
                    "Issuers already sign with did:web identifiers on the current host.",
                    "Changing the host would break verification of credentials already issued. "
                    "Plan a migration (new issuers on the new host) instead.",
                )
        elif key == "logo_asset_id" and value is not None:
            if db.get(BadgeAsset, value) is None:
                raise Invalid("ASSET_NOT_FOUND", "Upload the logo first, then choose it.")
        elif key == "branding":
            value = dict(value or {})
            for k in ("primary_colour", "secondary_colour"):
                if value.get(k) and not COLOUR_RE.match(str(value[k])):
                    raise Invalid("COLOUR_INVALID", "Colours must look like #1f4e79.")
            value = {k: v for k, v in value.items() if k in ("primary_colour", "secondary_colour")}
        elif key == "categories":
            cats = [str(c).strip() for c in (value or []) if str(c).strip()]
            if not cats or len(cats) > 30 or any(len(c) > 60 for c in cats):
                raise Invalid(
                    "CATEGORIES_INVALID",
                    "List between 1 and 30 categories, each up to 60 characters.",
                )
            value = list(dict.fromkeys(cats))
        clean[key] = value
    for key, value in clean.items():
        setattr(inst, key, value)
    if "verification_host" in clean:
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            # Another institution already uses this host (unique across institutions). The row
            # itself is invisible here (row-level security), so say only that it is taken.
            raise Conflict(
                "VERIFICATION_HOST_TAKEN",
                "Another institution on this service already uses that verification host.",
                "Each institution needs its own host. Choose a host your institution controls.",
            ) from None
    if clean:
        audit.record(
            db,
            action="institution.config_update",
            resource_type="institution",
            resource_id=inst.id,
            institution_id=inst.id,
            actor_user_id=actor.user_id,
            request_id=request_id,
            data={"fields": sorted(clean)},
        )
    return inst


def _did_web_issuers_with_keys(db: Session) -> bool:
    return (
        db.scalar(
            select(IssuerKey.id)
            .join(Issuer, Issuer.id == IssuerKey.issuer_id)
            .where(Issuer.did.startswith("did:web:"), IssuerKey.state.in_(("active", "retired")))
            .limit(1)
        )
        is not None
    )


# ---- policy ---------------------------------------------------------------------------------


def validate_policy_changes(changes: dict[str, Any]) -> dict[str, Any]:
    out = dict(changes)
    for key, allowed in POLICY_ROLE_LISTS.items():
        if key not in out:
            continue
        roles = list(dict.fromkeys(out[key] or []))
        if not roles or any(r not in allowed for r in roles):
            raise Invalid(
                "POLICY_INVALID", f"{key} must be a non-empty list from: {', '.join(allowed)}."
            )
        if "inst_admin" not in roles:
            roles.append("inst_admin")  # an institution administrator can always act
        out[key] = roles
    if "max_snapshot_age_minutes" in out and not 15 <= int(out["max_snapshot_age_minutes"]) <= 1440:
        raise Invalid("POLICY_INVALID", "Maximum data age must be between 15 and 1440 minutes.")
    return out


# ---- retention ------------------------------------------------------------------------------


def retention(inst: Institution) -> dict[str, Any]:
    merged = {**DEFAULT_RETENTION, **(inst.retention or {})}
    return {k: merged[k] for k in RETENTION_BOUNDS}


def update_retention(
    db: Session, actor: authz.Actor, changes: dict[str, int], request_id: str | None = None
) -> dict[str, Any]:
    authz.require_inst_admin(actor)
    inst = current(db, actor)
    clean = {}
    for key, value in changes.items():
        if key not in RETENTION_BOUNDS:
            continue
        lo, hi = RETENTION_BOUNDS[key]
        if not lo <= int(value) <= hi:
            raise Invalid("RETENTION_INVALID", f"{key} must be between {lo} and {hi}.")
        clean[key] = int(value)
    if clean:
        inst.retention = {**(inst.retention or {}), **clean}
        audit.record(
            db,
            action="institution.retention_update",
            resource_type="institution",
            resource_id=inst.id,
            institution_id=inst.id,
            actor_user_id=actor.user_id,
            request_id=request_id,
            data={"changes": clean},
        )
    return retention(inst)


def policy_out(db: Session, actor: authz.Actor, keys: tuple[str, ...]) -> dict[str, Any]:
    p = authz.institution_policy(db, actor.institution_id)
    return {k: p.get(k, DEFAULT_POLICY.get(k)) for k in keys}
