# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds a small, self-contained tenant for issuance tests (independent of the demo seed)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from opencredential.db import models as m
from opencredential.db.session import owner_session
from opencredential.institutions.identity import did_web_for
from opencredential.settings import Settings
from opencredential.signer_client import SignerClient


@dataclass
class Tenant:
    institution_id: uuid.UUID
    issuer_id: uuid.UUID
    key_id: uuid.UUID
    admin_id: uuid.UUID
    student_ids: list[uuid.UUID]
    version_id: uuid.UUID
    expiring_version_id: uuid.UUID
    did: str


def build_tenant(
    settings: Settings,
    *,
    did_method: str = "key",
    verification_host: str | None = None,
    students: int = 3,
) -> Tenant:
    signer = SignerClient(settings)
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    try:
        key_id = uuid.uuid4()
        key = signer.create_key(key_id, dev=True)
    finally:
        signer.close()
    with owner_session() as db:
        inst = m.Institution(
            slug=f"w4-{suffix}",
            name=f"W4 Test University {suffix}",
            website_url="https://w4.example/",
            verification_host=verification_host,
            is_demo=True,
        )
        db.add(inst)
        db.flush()
        iid = inst.id
        admin = m.User(institution_id=iid, display_name="Ada Admin", email="admin@w4.example")
        db.add(admin)
        users = [
            m.User(
                institution_id=iid,
                display_name=f"Student {i}",
                email=f"Student.{i}@W4.example ",
                email_verified_by="dev_seed",
            )
            for i in range(students)
        ]
        db.add_all(users)
        db.flush()
        db.add(
            m.Membership(
                institution_id=iid,
                user_id=admin.id,
                scope_type="institution",
                scope_id=iid,
                role="inst_admin",
                source="dev_seed",
            )
        )
        slug = f"centre-{suffix}"
        if did_method == "web":
            assert verification_host
            did = did_web_for(verification_host, slug)
            vm = f"{did}#key-{key_id}"
        else:
            did, vm = key.did, key.verification_method_id
        issuer = m.Issuer(
            institution_id=iid,
            slug=slug,
            name="Skills Centre (DEVELOPMENT)",
            url="https://w4.example/skills",
            did=did,
            status="active",
            approved_by=admin.id,
            approved_at=now,
        )
        db.add(issuer)
        db.flush()
        db.add(
            m.IssuerKey(
                id=key_id,
                institution_id=iid,
                issuer_id=issuer.id,
                verification_method_id=vm,
                public_key_multibase=key.public_key_multibase,
                state="active",
                activated_at=now,
                is_dev=True,
            )
        )
        versions = []
        for title, validity in (("Academic Writing Foundations", None), ("Lab Safety", 30)):
            d = m.AchievementDefinition(
                institution_id=iid,
                issuer_id=issuer.id,
                owner_user_id=admin.id,
                state="published",
                award_policy="automatic",
            )
            db.add(d)
            db.flush()
            v = m.AchievementVersion(
                institution_id=iid,
                definition_id=d.id,
                version_no=1,
                title=title,
                short_description=f"{title} short",
                description=f"Learners who hold {title} completed the required modules.",
                learning_outcomes=["Do the thing"],
                criteria_narrative="Complete all modules in the course.",
                category="Academic Communication",
                achievement_type="Badge",
                demonstration_kind="completing",
                validity_days=validity,
                skills=[
                    {"targetName": "Writing", "targetUrl": "https://example.org/skills/writing"}
                ],
                published_at=now,
                published_by=admin.id,
            )
            db.add(v)
            db.flush()
            v.frozen = True
            versions.append(v.id)
        db.flush()
        return Tenant(
            institution_id=iid,
            issuer_id=issuer.id,
            key_id=key_id,
            admin_id=admin.id,
            student_ids=[u.id for u in users],
            version_id=versions[0],
            expiring_version_id=versions[1],
            did=did,
        )
