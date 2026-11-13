# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Badges 3.0 ``OpenBadgeCredential`` assembly (spec §7.1, §7.2, §7.5).

Pure functions: no database, no network. Property names come from the OB 3.0 data model
(context 3.0.3) and VC Data Model 2.0 only; nothing here is invented. The output is the
*unsigned* credential the signer receives.

Recipient identity (ADR-0007): ``credentialSubject`` carries no ``id``. It carries one salted
SHA-256 ``IdentityObject`` for the learner's email. The learner's name is included only when the
institution's policy turns it on, as a plaintext ``IdentityObject`` of ``identityType: name``.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

VC_V2_CONTEXT = "https://www.w3.org/ns/credentials/v2"
OB_CONTEXT = "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json"
#: Defines ``1EdTechJsonSchemaValidator2019`` (the ``credentialSchema`` type); without it the
#: type is an undefined term and JSON-LD safe mode rightly refuses to sign.
OB_EXTENSIONS_CONTEXT = "https://purl.imsglobal.org/spec/ob/v3p0/extensions.json"
OB_CONTEXTS = frozenset(
    {
        OB_CONTEXT,
        "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.2.json",
        "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.1.json",
        "https://purl.imsglobal.org/spec/ob/v3p0/context.json",
    }
)
ACHIEVEMENT_CREDENTIAL_SCHEMA = (
    "https://purl.imsglobal.org/spec/ob/v3p0/schema/json/ob_v3p0_achievementcredential_schema.json"
)
SCHEMA_VALIDATOR_TYPE = "1EdTechJsonSchemaValidator2019"


def new_salt() -> str:
    """A fresh 128-bit salt per credential, so hashes cannot be linked across credentials."""
    return secrets.token_hex(16)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def identity_hash(identity: str, salt: str) -> str:
    """OB 3.0 ``IdentityHash``: ``sha256$`` + hex SHA-256 of the identity followed by the salt."""
    return "sha256$" + hashlib.sha256((identity + salt).encode("utf-8")).hexdigest()


def email_identity_hash(email: str, salt: str) -> str:
    return identity_hash(normalise_email(email), salt)


def matches_email(identity_object: dict[str, Any], email: str) -> bool:
    """Holder binding helper (ADR-0007): does ``email`` match a hashed email IdentityObject?"""
    if identity_object.get("identityType") != "emailAddress":
        return False
    salt = identity_object.get("salt") or ""
    expected = identity_object.get("identityHash", "")
    if identity_object.get("hashed"):
        return secrets.compare_digest(email_identity_hash(email, salt), expected)
    return normalise_email(email) == normalise_email(str(expected))


def iso(dt: datetime) -> str:
    """XML Schema dateTimeStamp in UTC with a ``Z`` and whole seconds."""
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class IssuerProfile:
    id: str  # the issuer DID
    name: str
    url: str | None = None
    email: str | None = None
    description: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class AchievementInfo:
    id: str
    name: str
    description: str
    criteria_narrative: str
    criteria_id: str | None = None
    achievement_type: str = "Badge"
    image_url: str | None = None
    image_caption: str | None = None
    tags: tuple[str, ...] = ()
    #: Skills alignment: dicts with ``targetName`` and ``targetUrl`` and optional extras.
    alignments: tuple[dict[str, str], ...] = ()
    language: str | None = "en"


@dataclass(frozen=True)
class EvidenceItem:
    narrative: str
    name: str | None = None
    url: str | None = None
    genre: str | None = None


@dataclass(frozen=True)
class StatusEntry:
    list_url: str
    index: int


@dataclass(frozen=True)
class CredentialInputs:
    credential_id: str  # urn:uuid:…
    issuer: IssuerProfile
    achievement: AchievementInfo
    valid_from: datetime
    recipient_hash: str
    recipient_salt: str
    status: StatusEntry
    valid_until: datetime | None = None
    recipient_name: str | None = None
    evidence: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    awarded: datetime | None = None


ALIGNMENT_KEYS = (
    "targetName",
    "targetUrl",
    "targetDescription",
    "targetFramework",
    "targetCode",
    "targetType",
)


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def build_achievement(a: AchievementInfo) -> dict[str, Any]:
    criteria = _drop_none({"id": a.criteria_id, "narrative": a.criteria_narrative})
    achievement: dict[str, Any] = {
        "id": a.id,
        "type": ["Achievement"],
        "achievementType": a.achievement_type,
        "name": a.name,
        "description": a.description,
        "criteria": criteria,
    }
    if a.image_url:
        achievement["image"] = _drop_none(
            {"id": a.image_url, "type": "Image", "caption": a.image_caption}
        )
    if a.tags:
        achievement["tag"] = list(a.tags)
    alignments = [
        {"type": ["Alignment"], **{k: al[k] for k in ALIGNMENT_KEYS if al.get(k)}}
        for al in a.alignments
        if al.get("targetName") and al.get("targetUrl")
    ]
    if alignments:
        achievement["alignment"] = alignments
    if a.language:
        achievement["inLanguage"] = a.language
    return achievement


def build_credential(inp: CredentialInputs) -> dict[str, Any]:
    """Assemble the unsigned OpenBadgeCredential (VC Data Model 2.0)."""
    issuer = _drop_none(
        {
            "id": inp.issuer.id,
            "type": ["Profile"],
            "name": inp.issuer.name,
            "url": inp.issuer.url,
            "email": inp.issuer.email,
            "description": inp.issuer.description,
        }
    )
    if inp.issuer.image_url:
        issuer["image"] = {"id": inp.issuer.image_url, "type": "Image"}

    identifiers: list[dict[str, Any]] = [
        {
            "type": "IdentityObject",
            "identityHash": inp.recipient_hash,
            "identityType": "emailAddress",
            "hashed": True,
            "salt": inp.recipient_salt,
        }
    ]
    if inp.recipient_name:
        identifiers.append(
            {
                "type": "IdentityObject",
                "identityHash": inp.recipient_name,
                "identityType": "name",
                "hashed": False,
            }
        )

    credential: dict[str, Any] = {
        "@context": [VC_V2_CONTEXT, OB_CONTEXT, OB_EXTENSIONS_CONTEXT],
        "id": inp.credential_id,
        "type": ["VerifiableCredential", "OpenBadgeCredential"],
        "name": inp.achievement.name,
        "issuer": issuer,
        "validFrom": iso(inp.valid_from),
        "credentialSubject": {
            "type": ["AchievementSubject"],
            "identifier": identifiers,
            "achievement": build_achievement(inp.achievement),
        },
        "credentialStatus": {
            "id": f"{inp.status.list_url}#{inp.status.index}",
            "type": "BitstringStatusListEntry",
            "statusPurpose": "revocation",
            "statusListIndex": str(inp.status.index),
            "statusListCredential": inp.status.list_url,
        },
        "credentialSchema": [{"id": ACHIEVEMENT_CREDENTIAL_SCHEMA, "type": SCHEMA_VALIDATOR_TYPE}],
    }
    if inp.valid_until is not None:
        credential["validUntil"] = iso(inp.valid_until)
    if inp.awarded is not None:
        credential["awardedDate"] = iso(inp.awarded)
    if inp.evidence:
        credential["evidence"] = [
            _drop_none(
                {
                    "id": e.url,
                    "type": ["Evidence"],
                    "name": e.name,
                    "narrative": e.narrative,
                    "genre": e.genre,
                }
            )
            for e in inp.evidence
        ]
    return credential
