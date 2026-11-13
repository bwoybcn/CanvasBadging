# SPDX-License-Identifier: AGPL-3.0-or-later
"""OB 3.0 credential assembly (U-ISS-FIELDS, U-ISS-SUBJ, U-ISS-EVIDENCE)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from opencredential.issuance import ob3


def _inputs(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        credential_id="urn:uuid:0190f3a2-7b1c-7d2e-8f00-123456789abc",
        issuer=ob3.IssuerProfile(
            id="did:key:z6MkExample", name="Skills Centre", url="https://u.example/"
        ),
        achievement=ob3.AchievementInfo(
            id="https://u.example/achievements/1",
            name="Academic Writing",
            description="Completed academic writing.",
            criteria_narrative="Complete three modules.",
            image_url="https://u.example/assets/default-badge.svg",
            image_caption="Badge",
            alignments=({"targetName": "Writing", "targetUrl": "https://skills.example/w"},),
        ),
        valid_from=datetime(2026, 11, 13, 12, 0, 0, 123456, tzinfo=UTC),
        recipient_hash=ob3.email_identity_hash("Learner@Uni.example ", "00ff"),
        recipient_salt="00ff",
        status=ob3.StatusEntry(list_url="https://u.example/status/c/l", index=42),
    )
    base.update(kw)
    return ob3.CredentialInputs(**base)


def test_mandatory_fields() -> None:
    c = ob3.build_credential(_inputs())
    assert c["@context"][:2] == [ob3.VC_V2_CONTEXT, ob3.OB_CONTEXT]
    assert c["type"] == ["VerifiableCredential", "OpenBadgeCredential"]
    assert c["id"].startswith("urn:uuid:")
    assert c["issuer"]["id"] == "did:key:z6MkExample" and c["issuer"]["type"] == ["Profile"]
    assert c["validFrom"] == "2026-11-13T12:00:00Z"
    assert "validUntil" not in c
    a = c["credentialSubject"]["achievement"]
    assert {"id", "type", "name", "description", "criteria", "image"} <= set(a)
    assert a["image"] == {
        "id": "https://u.example/assets/default-badge.svg",
        "type": "Image",
        "caption": "Badge",
    }
    assert a["alignment"][0]["type"] == ["Alignment"]
    assert c["credentialStatus"] == {
        "id": "https://u.example/status/c/l#42",
        "type": "BitstringStatusListEntry",
        "statusPurpose": "revocation",
        "statusListIndex": "42",
        "statusListCredential": "https://u.example/status/c/l",
    }
    assert c["credentialSchema"][0]["type"] == "1EdTechJsonSchemaValidator2019"
    assert "evidence" not in c


def test_recipient_is_salted_hash_without_email_or_name() -> None:
    c = ob3.build_credential(_inputs())
    subject = c["credentialSubject"]
    assert "id" not in subject
    (ident,) = subject["identifier"]
    expected = "sha256$" + hashlib.sha256(b"learner@uni.example00ff").hexdigest()
    assert ident == {
        "type": "IdentityObject",
        "identityHash": expected,
        "identityType": "emailAddress",
        "hashed": True,
        "salt": "00ff",
    }
    text = json.dumps(c).lower()
    assert "learner@uni.example" not in text
    assert ob3.matches_email(ident, "LEARNER@uni.example")
    assert not ob3.matches_email(ident, "someone@else.example")


def test_name_only_when_policy_allows() -> None:
    c = ob3.build_credential(_inputs(recipient_name="Amara Okafor"))
    names = [i for i in c["credentialSubject"]["identifier"] if i["identityType"] == "name"]
    assert names == [
        {
            "type": "IdentityObject",
            "identityHash": "Amara Okafor",
            "identityType": "name",
            "hashed": False,
        }
    ]


def test_salts_are_fresh_per_credential() -> None:
    assert ob3.new_salt() != ob3.new_salt()
    assert len(ob3.new_salt()) == 32


def test_only_disclosed_evidence_and_expiry() -> None:
    c = ob3.build_credential(
        _inputs(
            evidence=(ob3.EvidenceItem(narrative="Passed the quiz", genre="assessment result"),),
            valid_until=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    assert c["evidence"] == [
        {"type": ["Evidence"], "narrative": "Passed the quiz", "genre": "assessment result"}
    ]
    assert c["validUntil"] == "2027-01-01T00:00:00Z"
