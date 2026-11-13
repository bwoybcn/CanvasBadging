# SPDX-License-Identifier: AGPL-3.0-or-later
"""Student-controlled public sharing of a credential (spec §8.4, §9.4, §16.3; ADR-0014).

Rules this module enforces:

* Nothing is public by default. A credential gets a public page only when its holder creates a
  share grant, and only the holder can create or withdraw one.
* Share identifiers are 128-bit random, base64url, never derived from database ids, so they are
  opaque and not sequential or guessable.
* Withdrawing a share (``revoked_at``) only removes the public page. The credential itself, its
  status-list bit and any copy the student downloaded are untouched.
* :func:`public_view` is the single definition of what a share page shows. The preview endpoint
  calls the same function, so the preview is exactly what becomes public.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential import audit
from opencredential.db.models import (
    AchievementVersion,
    Credential,
    CredentialStatus,
    Institution,
    Issuer,
    ShareGrant,
    User,
)
from opencredential.institutions.identity import base_url
from opencredential.settings import Settings

#: 16 random bytes = 128 bits, encoded as 22 base64url characters.
SHARE_ID_BYTES = 16


class SharingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ShareOptions:
    show_name: bool = False
    show_evidence: bool = False


def new_share_id() -> str:
    return secrets.token_urlsafe(SHARE_ID_BYTES)


def share_url(institution: Institution, settings: Settings, share_id: str) -> str:
    """Public page for a share, on the institution's verification host (configurable)."""
    return f"{base_url(institution, settings)}/verify/{share_id}"


def active_grant(db: Session, credential_id: uuid.UUID) -> ShareGrant | None:
    return db.scalar(
        select(ShareGrant).where(
            ShareGrant.credential_id == credential_id, ShareGrant.revoked_at.is_(None)
        )
    )


def owned_credential(db: Session, credential_id: uuid.UUID, user_id: uuid.UUID) -> Credential:
    """The caller's own issued credential. Anything else is reported as not found (spec E10)."""
    cred = db.get(Credential, credential_id)
    if cred is None or cred.user_id != user_id or cred.status != "issued":
        raise SharingError("NOT_FOUND", "No such credential")
    return cred


def share(
    db: Session,
    cred: Credential,
    options: ShareOptions,
    *,
    actor_user_id: uuid.UUID,
    request_id: str | None = None,
) -> ShareGrant:
    """Turn on (or update) the public page. Re-sharing keeps the same link while it is active."""
    if cred.signed_json is None:
        raise SharingError("NOT_ISSUED", "This credential has not been issued yet")
    grant = active_grant(db, cred.id)
    action = "credential.share_updated"
    if grant is None:
        grant = ShareGrant(
            institution_id=cred.institution_id,
            credential_id=cred.id,
            share_id=new_share_id(),
            created_by=actor_user_id,
        )
        db.add(grant)
        action = "credential.shared"
    grant.show_name = options.show_name
    grant.show_evidence = options.show_evidence
    db.flush()
    audit.record(
        db,
        action=action,
        resource_type="credential",
        resource_id=cred.id,
        institution_id=cred.institution_id,
        actor_user_id=actor_user_id,
        request_id=request_id,
        data={"show_name": options.show_name, "show_evidence": options.show_evidence},
    )
    return grant


def unshare(
    db: Session, cred: Credential, *, actor_user_id: uuid.UUID, request_id: str | None = None
) -> bool:
    """Withdraw the public page. Idempotent. Does not revoke the credential (spec §16.3)."""
    grant = active_grant(db, cred.id)
    if grant is None:
        return False
    grant.revoked_at = datetime.now(UTC)
    audit.record(
        db,
        action="credential.unshared",
        resource_type="credential",
        resource_id=cred.id,
        institution_id=cred.institution_id,
        actor_user_id=actor_user_id,
        request_id=request_id,
    )
    return True


def _evidence(vc: dict[str, Any]) -> list[dict[str, Any]]:
    items = vc.get("evidence") or []
    out = []
    for e in items if isinstance(items, list) else [items]:
        if isinstance(e, dict):
            out.append(
                {
                    "narrative": e.get("narrative") or e.get("description") or e.get("name") or "",
                    "url": e.get("id") if str(e.get("id", "")).startswith("https://") else None,
                    "genre": e.get("genre"),
                }
            )
    return out


def credential_state(cred: Credential, status: CredentialStatus | None) -> str:
    if status is not None and status.state == "revoked":
        return "revoked"
    if status is not None and status.state == "suspended":
        return "suspended"
    if cred.valid_until is not None and cred.valid_until < datetime.now(UTC):
        return "expired"
    return "active"


def public_view(
    db: Session, cred: Credential, options: ShareOptions, settings: Settings
) -> dict[str, Any]:
    """Everything a share page shows, and nothing else.

    Built from the signed credential (what a verifier would see) plus the learner's display name
    only when the learner opted in. Never includes email, Canvas ids, grades, submissions, the
    recipient hash or course names.
    """
    vc = cred.signed_json or {}
    subject = vc.get("credentialSubject") or {}
    achievement = subject.get("achievement") or {}
    issuer_doc = vc.get("issuer") or {}
    issuer = db.get(Issuer, cred.issuer_id)
    version = db.get(AchievementVersion, cred.version_id)
    institution = db.get(Institution, cred.institution_id)
    assert issuer is not None and institution is not None
    criteria = achievement.get("criteria") or {}
    image = achievement.get("image") or {}
    name = None
    if options.show_name:
        user = db.get(User, cred.user_id)
        name = user.display_name if user else None
    return {
        "credential_name": achievement.get("name") or (version.title if version else ""),
        "achievement_type": achievement.get("achievementType"),
        "description": achievement.get("description") or "",
        "short_description": version.short_description if version else None,
        "criteria": criteria.get("narrative") or "",
        "skills": [
            {"name": a.get("targetName"), "url": a.get("targetUrl")}
            for a in achievement.get("alignment") or []
            if isinstance(a, dict)
        ],
        "issuer": {
            "name": issuer_doc.get("name") or issuer.name,
            "id": issuer_doc.get("id") or issuer.did,
            "url": issuer_doc.get("url") or issuer.url,
            "institution": institution.name,
        },
        "image": {
            "url": image.get("id") if isinstance(image, dict) else None,
            "alt": (image.get("caption") if isinstance(image, dict) else None)
            or f"Badge image for {achievement.get('name', 'this credential')}",
        },
        "issued_on": vc.get("validFrom"),
        "valid_until": vc.get("validUntil"),
        "credential_id": vc.get("id"),
        "recipient_name": name,
        "evidence": _evidence(vc) if options.show_evidence else [],
        "evidence_hidden": bool(_evidence(vc)) and not options.show_evidence,
        "name_in_credential": _name_in_credential(subject),
    }


def _name_in_credential(subject: dict[str, Any]) -> bool:
    """True when the institution's policy put the learner's name inside the signed file."""
    ids = subject.get("identifier") or []
    return any(isinstance(i, dict) and i.get("identityType") == "name" for i in ids)


def preview_fields(view: dict[str, Any]) -> list[dict[str, str]]:
    """Plain list of what becomes visible, for the student's consent screen."""
    rows = [
        ("Badge name", view["credential_name"]),
        ("Issued by", f"{view['issuer']['name']} ({view['issuer']['institution']})"),
        ("Description", view["description"]),
        ("Criteria", view["criteria"]),
        ("Issued on", view["issued_on"] or ""),
        ("Credential ID", view["credential_id"] or ""),
        ("Your name", _name_row(view)),
        (
            "Evidence",
            "; ".join(e["narrative"] for e in view["evidence"])
            if view["evidence"]
            else ("Not shown" if view["evidence_hidden"] else "None"),
        ),
    ]
    if view["valid_until"]:
        rows.insert(5, ("Expires on", view["valid_until"]))
    return [{"label": k, "value": v} for k, v in rows]


def _name_row(view: dict[str, Any]) -> str:
    if view["recipient_name"]:
        return view["recipient_name"]
    if view["name_in_credential"]:
        return "Not shown on the page, but your institution includes it in the credential file"
    return "Not shown"


NEVER_SHARED = (
    "Your email address and Canvas login",
    "Your marks, grades and Canvas submissions",
    "Your other badges and the course roster",
)
