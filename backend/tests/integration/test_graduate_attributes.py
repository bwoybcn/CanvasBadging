# SPDX-License-Identifier: AGPL-3.0-or-later
"""Graduate attributes and template packs (migration 0017).

An institution administrator keeps a list of graduate attributes and can install a template
pack (the University of Liverpool one) that adds attributes and templates in one go. Authors
tag badges with attributes from the list; issued badges carry them as Open Badges 3.0
alignments, and the student's and public pages name them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.governance import packs
from opencredential.integrations import registry
from opencredential.issuance.schema import validate_achievement_credential
from opencredential.issuance.service import issue
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient
from opencredential.status import service as status_service
from tests.independent import verifier as independent
from tests.integration.test_sharing_and_export import (
    MODULE_RULES,
    _give_world_a_real_key,
    _share_id,
)
from tests.integration.world import COURSE_REF, build_world

LIST = "/api/v1/admin/graduate-attributes"
INSTALL = "/api/v1/admin/template-packs/liverpool/install"


def _named(version: dict[str, Any]) -> list[tuple[str, str]]:
    return [(a["key"], a["name"]) for a in version["graduate_attributes"]]


@pytest.fixture(scope="module")
def signer(database: None, signer_available: bool) -> Iterator[SignerClient]:
    client = SignerClient(get_settings())
    yield client
    client.close()


@pytest.fixture
def client(database: None, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


def test_admins_keep_the_list_and_new_attributes_get_keys(client: TestClient) -> None:
    w = build_world(client)
    assert w.get("admin", LIST).json() == []
    assert w.put("lecturer", LIST, {"attributes": [{"name": "Confidence"}]}).status_code == 403

    r = w.put(
        "admin",
        LIST,
        {
            "attributes": [
                {"name": "  Digital   Fluency ", "framework": "Our Framework"},
                {"name": "Confidence", "url": "https://example.ac.uk/confidence"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"key": "digital-fluency", "name": "Digital Fluency", "framework": "Our Framework"},
        {"key": "confidence", "name": "Confidence", "url": "https://example.ac.uk/confidence"},
    ]
    # Renaming keeps the key, so badges that use it are unaffected.
    r = w.put("admin", LIST, {"attributes": [{"key": "confidence", "name": "Self-confidence"}]})
    assert r.json() == [{"key": "confidence", "name": "Self-confidence"}]

    for bad in (
        [{"name": "Confidence"}, {"name": "confidence"}],
        [{"name": "Confidence", "url": "http://example.ac.uk"}],
    ):
        assert w.put("admin", LIST, {"attributes": bad}).status_code == 422


def test_the_liverpool_pack_installs_once_and_its_templates_tag_new_badges(
    client: TestClient,
) -> None:
    w = build_world(client)
    listed = w.get("admin", "/api/v1/admin/template-packs").json()
    assert [p["key"] for p in listed] == ["liverpool"]
    assert listed[0]["attributes"] == ["Confidence", "Digital Fluency", "Global Citizenship"]
    assert w.post("lecturer", INSTALL, {}).status_code == 403

    r = w.post("admin", INSTALL, {})
    assert r.status_code == 201, r.text
    added = r.json()
    assert [a["key"] for a in added["attributes"]] == [
        "confidence",
        "digital-fluency",
        "global-citizenship",
    ]
    assert [t["name"] for t in added["templates"]] == [
        "Confidence in practice",
        "Digital Fluency in practice",
        "Global Citizenship in practice",
        "Sustainability literacy",
        "AI literacy",
        "Year in Industry",
    ]
    # Installing again adds nothing and leaves what is there alone.
    assert w.post("admin", INSTALL, {}).json() == {"attributes": [], "templates": []}
    assert w.post("admin", "/api/v1/admin/template-packs/nope/install", {}).status_code == 404

    # Authors see the list next to the categories.
    catalogue = w.get("lecturer", "/api/v1/categories").json()
    assert [a["name"] for a in catalogue["graduate_attributes"]] == [
        "Confidence",
        "Digital Fluency",
        "Global Citizenship",
    ]

    # A badge started from a template arrives tagged; the template's [placeholders] must go
    # before it can be submitted.
    offered = w.get("lecturer", "/api/v1/templates", params={"course_id": w.course_id}).json()
    yii = next(t for t in offered if t["name"] == "Year in Industry")
    r = w.post(
        "lecturer",
        "/api/v1/achievements",
        {
            "issuer_id": str(w.issuer_id),
            "course_id": str(w.course_id),
            "template_id": yii["id"],
            "fields": {"asset_id": w.artwork()},
        },
    )
    assert r.status_code == 201, r.text
    version = r.json()["working_version"]
    assert [a["key"] for a in version["graduate_attributes"]] == [
        "confidence",
        "global-citizenship",
    ]
    assert version["award_policy"] == "manual"
    codes = {i["code"] for i in r.json()["readiness"]}
    assert "TEMPLATE_PLACEHOLDER" in codes

    # An attribute removed from the list since is left off a new badge, not an error.
    current = w.get("admin", LIST).json()
    w.put("admin", LIST, {"attributes": [a for a in current if a["key"] != "confidence"]})
    r = w.post(
        "lecturer",
        "/api/v1/achievements",
        {"issuer_id": str(w.issuer_id), "course_id": str(w.course_id), "template_id": yii["id"]},
    )
    assert r.status_code == 201, r.text
    assert [a["key"] for a in r.json()["working_version"]["graduate_attributes"]] == [
        "global-citizenship"
    ]


def test_a_draft_keeps_its_copy_when_the_list_changes(client: TestClient) -> None:
    w = build_world(client)
    w.put("admin", LIST, {"attributes": [{"name": "Confidence"}, {"name": "Teamwork"}]})
    d = w.draft(MODULE_RULES, graduate_attributes=["confidence"])
    assert _named(d["working_version"]) == [("confidence", "Confidence")]

    r = w.post(
        "lecturer",
        "/api/v1/achievements",
        {
            "issuer_id": str(w.issuer_id),
            "course_id": str(w.course_id),
            "fields": {"graduate_attributes": ["not-on-the-list"]},
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "GRADUATE_ATTRIBUTE_UNKNOWN"

    # The administrator renames one and removes the other; the draft keeps what it had and
    # can still be saved with it.
    w.put("admin", LIST, {"attributes": [{"key": "teamwork", "name": "Working together"}]})
    detail = w.get("lecturer", f"/api/v1/achievements/{d['id']}").json()
    r = w.client.patch(
        f"/api/v1/achievements/{d['id']}",
        headers={**w.h("lecturer"), "if-match": detail["revision"]},
        json={"graduate_attributes": ["confidence", "teamwork"]},
    )
    assert r.status_code == 200, r.text
    assert _named(r.json()["working_version"]) == [
        ("confidence", "Confidence"),
        ("teamwork", "Working together"),
    ]


def test_issued_badges_carry_graduate_attributes_as_alignments(
    client: TestClient, signer: SignerClient
) -> None:
    w = build_world(client)
    _give_world_a_real_key(w, signer)
    assert w.post("admin", INSTALL, {}).status_code == 201
    with registry.override(w.lms):
        w.publish(
            MODULE_RULES,
            skills=[{"name": "Academic writing"}],
            graduate_attributes=["digital-fluency"],
        )
        w.lms.complete_module(COURSE_REF, "lms-s1", "m1")
        assert w.sync_and_evaluate()["decisions"] == 1
    (decision,) = w.decisions()
    assert issue(w.iid, decision.id, signer=signer, settings=get_settings()).outcome == "issued"
    with w.db() as db:
        cred = db.scalar(select(m.Credential).where(m.Credential.user_id == w.users["s1"]))
        assert cred is not None and cred.status_list_id is not None
        status_service.publish(db, cred.status_list_id, signer, get_settings())
        cred_id = cred.id

    # Editing the list afterwards changes nothing already issued.
    w.put("admin", LIST, {"attributes": []})

    downloaded = w.get("s1", f"/api/v1/credentials/{cred_id}/export").json()
    assert validate_achievement_credential(downloaded) == []
    independent.verify(downloaded)
    achievement = downloaded["credentialSubject"]["achievement"]
    pack = packs.get("liverpool")
    fluency = next(a for a in pack.attributes if a.key == "digital-fluency")
    assert achievement["alignment"][1] == {
        "type": ["Alignment"],
        "targetName": "Digital Fluency",
        "targetUrl": fluency.url,
        "targetCode": "digital-fluency",
        "targetType": "ext:GraduateAttribute",
        "targetDescription": fluency.description,
        "targetFramework": "Liverpool Curriculum Framework",
    }
    outsider = TestClient(client.app)
    published = outsider.get(urlsplit(achievement["id"]).path).json()
    assert published["alignment"] == achievement["alignment"]

    # The student's page lists skills and graduate attributes separately.
    detail = w.get("s1", f"/api/v1/credentials/{cred_id}").json()
    assert [s["name"] for s in detail["skills"]] == ["Academic writing"]
    assert detail["graduate_attributes"] == [
        {
            "name": "Digital Fluency",
            "description": fluency.description,
            "framework": "Liverpool Curriculum Framework",
        }
    ]
    url = w.put("s1", f"/api/v1/credentials/{cred_id}/share", {}).json()["share"]["url"]
    page = outsider.get(f"/verify/{_share_id(url)}").text
    assert "<h2>Graduate attributes it develops</h2>" in page
    assert "<li><strong>Digital Fluency</strong>: Students use digital tools" in page
