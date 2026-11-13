# SPDX-License-Identifier: AGPL-3.0-or-later
"""Non-issued preview of a badge (spec §5.5).

Everything here is marked as a preview: the sample credential has a placeholder id, no proof
and a top-level ``_preview`` notice, and the example verification page says it is not a real
verification. Nothing in a preview can be presented or verified as a credential.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opencredential.authoring import rules_store
from opencredential.authoring.service import DEMONSTRATION_KINDS
from opencredential.db.models import (
    AchievementDefinition,
    AchievementVersion,
    BadgeAsset,
    Issuer,
    LmsAssignment,
    LmsModule,
)
from opencredential.rules.schema import describe
from opencredential.settings import get_settings
from opencredential.storage import get_store

PREVIEW_NOTICE = "PREVIEW: NOT ISSUED AND NOT VERIFIABLE"
PLACEHOLDER_ID = "urn:uuid:00000000-0000-0000-0000-000000000000"


def asset_data_url(asset: BadgeAsset | None) -> str | None:
    if asset is None:
        return None
    try:
        data = get_store().get(asset.storage_key)
    except (OSError, ValueError):
        return None
    return f"data:{asset.media_type};base64,{base64.b64encode(data).decode()}"


def source_names(db: Session, course_id: uuid.UUID | None) -> dict[str, str]:
    if course_id is None:
        return {}
    names = {
        m.canvas_module_id: m.name
        for m in db.scalars(select(LmsModule).where(LmsModule.course_id == course_id))
    }
    names |= {
        a.canvas_assignment_id: a.name
        for a in db.scalars(select(LmsAssignment).where(LmsAssignment.course_id == course_id))
    }
    return names


def build(
    db: Session, definition: AchievementDefinition, version: AchievementVersion
) -> dict[str, Any]:
    settings = get_settings()
    issuer = db.get(Issuer, definition.issuer_id)
    asset = db.get(BadgeAsset, version.asset_id) if version.asset_id else None
    rules = rules_store.load(db, version.id)
    names = source_names(db, definition.course_id)
    requirements = [describe(r, names) for r in rules.rules] if rules else []
    host = f"https://{settings.verification_host}"
    example_date = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    evidence = [
        "The public credential does not include your marks, submissions or other private "
        "Canvas data.",
    ]
    if version.evidence_description:
        evidence.insert(0, version.evidence_description)

    sample = {
        "_preview": PREVIEW_NOTICE,
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json",
        ],
        "id": PLACEHOLDER_ID,
        "type": ["VerifiableCredential", "OpenBadgeCredential"],
        "issuer": {
            "id": issuer.did if issuer else None,
            "type": ["Profile"],
            "name": issuer.name if issuer else None,
            "url": issuer.url if issuer else None,
        },
        "validFrom": example_date,
        "name": version.title,
        "credentialSubject": {
            "type": ["AchievementSubject"],
            "achievement": {
                "id": f"{host}/achievements/{version.id}",
                "type": ["Achievement"],
                "achievementType": version.achievement_type,
                "name": version.title,
                "description": version.description or version.short_description,
                "criteria": {"narrative": version.criteria_narrative},
                **(
                    {"image": {"id": "(badge image)", "type": "Image", "caption": asset.alt_text}}
                    if asset
                    else {}
                ),
            },
        },
    }
    if version.validity_days:
        sample["validUntil"] = f"(issue date + {version.validity_days} days)"
    return {
        "preview": True,
        "notice": PREVIEW_NOTICE,
        "version_id": str(version.id),
        "version_no": version.version_no,
        "state": definition.state,
        "artwork": {
            "data_url": asset_data_url(asset),
            "alt_text": asset.alt_text if asset else None,
        },
        "achievement": {
            "title": version.title,
            "short_description": version.short_description,
            "description": version.description or version.short_description,
            "category": version.category,
            "achievement_type": version.achievement_type,
            "demonstration": DEMONSTRATION_KINDS.get(version.demonstration_kind),
            "learning_outcomes": version.learning_outcomes,
            "criteria": version.criteria_narrative,
            "requirements": requirements,
            "skills": version.skills,
            "validity_days": version.validity_days,
        },
        "issuer": {
            "name": issuer.name if issuer else None,
            "url": issuer.url if issuer else None,
            "did": issuer.did if issuer else None,
        },
        "evidence_disclosures": evidence,
        "example_student_badge": {
            "recipient": "Example Student",
            "issued_on": "(date of award)",
            "title": version.title,
            "issuer": issuer.name if issuer else None,
        },
        "example_verification_page": {
            "result": "preview_only",
            "headline": "This is a preview. It is not a credential and cannot be verified.",
            "explains": [
                "When a real badge is shared, this page checks the issuer's digital signature, "
                "whether the badge was revoked and whether it has expired.",
                "It shows only what the student chose to share.",
            ],
        },
        "sample_credential": sample,
    }
