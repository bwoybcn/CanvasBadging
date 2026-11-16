# SPDX-License-Identifier: AGPL-3.0-or-later
"""W6: student collection, download, sharing, LinkedIn and external verification.

Phase 6 exit (spec §20): a student earns, downloads and shares a credential, and someone without
Canvas access verifies it. Also spec §19.3 scenarios 6, 7, 9 and 11, and the privacy rules of
§8.4 / §9.4 / §16.3 (off by default, opaque ids, noindex, withdrawing a link is not revocation,
the preview is exactly what becomes public, no learner data in link previews).

Real PostgreSQL and the real signer throughout (no mocked issuance, spec R-0.1). Every exported
credential is also checked by the independent Python verifier (C-INDEP-01).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from opencredential.api.app import create_app
from opencredential.authz import sessions
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.integrations import registry
from opencredential.issuance import decisions
from opencredential.issuance.schema import validate_achievement_credential
from opencredential.issuance.service import issue
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient
from opencredential.status import service as status_service
from tests.independent import verifier as independent
from tests.integration.issuance_factory import Tenant, build_tenant
from tests.integration.world import COURSE_REF, World, build_world

pytestmark = pytest.mark.db

MODULE_RULES = {"mode": "ALL", "rules": [{"type": "module_completed", "module_id": "m1"}]}
SHARE_ID = re.compile(r"/verify/([A-Za-z0-9_-]{22})$")


@pytest.fixture(scope="module")
def signer(database: None, signer_available: bool) -> Iterator[SignerClient]:
    client = SignerClient(get_settings())
    yield client
    client.close()


@pytest.fixture
def client(signer: SignerClient, tmp_path: Path) -> Iterator[TestClient]:
    settings = get_settings()
    settings.storage_dir = str(tmp_path / "assets")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def tenant(signer: SignerClient) -> Tenant:
    return build_tenant(get_settings())


def _headers(iid: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    token, _ = sessions.issue(get_settings(), user_id=user_id, institution_id=iid, method="dev")
    return {"authorization": f"Bearer {token}"}


def _issue_for(
    t: Tenant,
    signer: SignerClient,
    student: int = 0,
    *,
    version_id: uuid.UUID | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> uuid.UUID:
    with tenant_session(t.institution_id) as db:
        d, _ = decisions.decide(
            db,
            institution_id=t.institution_id,
            user_id=t.student_ids[student],
            version_id=version_id or t.version_id,
            kind="manual",
            justification="Completed all modules (test)",
            decided_by=t.admin_id,
        )
        if evidence:
            d.evidence = evidence
        decision_id = d.id
    result = issue(t.institution_id, decision_id, signer=signer, settings=get_settings())
    assert result.outcome == "issued"
    with tenant_session(t.institution_id) as db:
        status_service.publish(db, result.status_list_id, signer, get_settings())
    return result.credential_id


def _share_id(url: str) -> str:
    match = SHARE_ID.search(url)
    assert match, url
    return match.group(1)


def _og(html: str) -> dict[str, str]:
    return dict(re.findall(r'<meta property="(og:[^"]+)" content="([^"]*)">', html))


# ---- Phase 6 exit: earn, download, share, verify without Canvas ---------------------------


def _give_world_a_real_key(w: World, signer: SignerClient) -> None:
    """W5's world uses a placeholder DID; give its issuer a real signing key and learners an
    email so the W4 issuance service can sign for it."""
    key_id = uuid.uuid4()
    key = signer.create_key(key_id, dev=True)
    now = datetime.now(UTC)
    with owner_session() as db:
        issuer = db.get(m.Issuer, w.issuer_id)
        assert issuer is not None
        issuer.did = key.did
        issuer.approved_by = w.users["admin"]
        issuer.approved_at = now
        db.add(
            m.IssuerKey(
                id=key_id,
                institution_id=w.iid,
                issuer_id=issuer.id,
                verification_method_id=key.verification_method_id,
                public_key_multibase=key.public_key_multibase,
                state="active",
                activated_at=now,
                is_dev=True,
            )
        )
        for who in ("s1", "s2", "s3"):
            u = db.get(m.User, w.users[who])
            assert u is not None
            u.email = f"{who}.{w.iid.hex[:6]}@w6.example"
            u.display_name = f"Morwenna {who.upper()} Trelawney"


def test_phase6_exit_earn_download_share_and_outsider_verifies(
    client: TestClient, signer: SignerClient
) -> None:
    w = build_world(client)
    _give_world_a_real_key(w, signer)
    with registry.override(w.lms):
        w.publish(MODULE_RULES)
        # Earn: Canvas reports the module complete; sync + rules evaluation award the badge.
        w.lms.complete_module(COURSE_REF, "lms-s1", "m1")
        assert w.sync_and_evaluate()["decisions"] == 1
    (decision,) = w.decisions()
    assert [j["args"]["decision_id"] for j in w.jobs("oc:issue_credential")] == [str(decision.id)]
    # What the worker does for that queued job (the task body is W4's issuance service).
    result = issue(w.iid, decision.id, signer=signer, settings=get_settings())
    assert result.outcome == "issued"
    with w.db() as db:
        cred = db.scalar(select(m.Credential).where(m.Credential.user_id == w.users["s1"]))
        assert cred is not None and cred.status_list_id is not None
        status_service.publish(db, cred.status_list_id, signer, get_settings())
        cred_id = cred.id

    # Dashboard: earned credential in the collection, not shared by default.
    (item,) = w.get("s1", "/api/v1/learners/me/credentials").json()
    assert item["id"] == str(cred_id) and item["status"] == "active"
    assert item["course"]["title"] == "Study Skills 101"
    assert item["image"]["data_url"] and item["image"]["alt_text"]
    assert item["share"] == {
        "shared": False,
        "url": None,
        "show_name": False,
        "show_evidence": False,
        "shared_since": None,
    }
    assert w.get("s2", "/api/v1/learners/me/credentials").json() == []

    # Detail page data (spec §8.3).
    detail = w.get("s1", f"/api/v1/credentials/{cred_id}").json()
    assert detail["verification"]["result"] == "verified"
    assert detail["criteria"] == "Complete the writing module."
    assert detail["issuer"]["name"] == "Skills Centre (TEST)"
    assert detail["credential_id"].startswith("urn:uuid:")
    assert detail["linkedin"]["needs_share"] is True

    # Download.
    dl = w.get("s1", f"/api/v1/credentials/{cred_id}/export")
    assert dl.status_code == 200 and "attachment" in dl.headers["content-disposition"]
    downloaded = dl.json()
    assert validate_achievement_credential(downloaded) == []
    independent.verify(downloaded)

    # Share: preview first, then turn it on.
    preview = w.post("s1", f"/api/v1/credentials/{cred_id}/share/preview", {}).json()
    assert preview["public"]["recipient_name"] is None
    shared = w.put("s1", f"/api/v1/credentials/{cred_id}/share", {}).json()
    url = shared["share"]["url"]
    share_id = _share_id(url)
    assert shared["preview"]["public"] == preview["public"]

    # Outsider: no session, no Canvas.
    outsider = TestClient(client.app)
    page = outsider.get(f"/verify/{share_id}")
    assert page.status_code == 200
    assert "Verified" in page.text and "Academic Writing Foundations" in page.text
    assert "Trelawney" not in page.text
    assert '<meta name="robots" content="noindex' in page.text
    assert "noindex" in page.headers["x-robots-tag"]
    file = outsider.get(f"/verify/{share_id}/credential.json")
    assert file.status_code == 200 and file.json() == downloaded
    assert outsider.post("/api/v1/verify", json=downloaded).json()["result"] == "verified"
    machine = outsider.get(f"/verify/{share_id}/verification.json").json()
    assert machine["result"] == "verified"
    # The badge image the credential points at is publicly served.
    image_url = downloaded["credentialSubject"]["achievement"]["image"]["id"]
    img = outsider.get(urlsplit(image_url).path)
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")

    # Withdrawing the link hides the page but does not revoke the credential.
    after = w.client.delete(f"/api/v1/credentials/{cred_id}/share", headers=w.h("s1")).json()
    assert after["share"]["shared"] is False
    assert outsider.get(f"/verify/{share_id}").status_code == 404
    assert outsider.post("/api/v1/verify", json=downloaded).json()["result"] == "verified"
    assert w.get("s1", "/api/v1/learners/me/credentials").json()[0]["status"] == "active"


def test_skills_typed_by_the_author_reach_the_issued_badge(
    client: TestClient, signer: SignerClient
) -> None:
    """Skills are authored as name, framework, code and link. They used to be dropped unless
    they had a link, which the screens could not give, so no badge carried its skills."""
    w = build_world(client)
    _give_world_a_real_key(w, signer)
    with registry.override(w.lms):
        w.publish(
            MODULE_RULES,
            skills=[
                {"name": "Academic writing", "framework": "UoL Skills"},
                {
                    "name": "Referencing",
                    "framework": "ESCO",
                    "code": "S1.2",
                    "url": "https://skills.example/referencing",
                },
            ],
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

    downloaded = w.get("s1", f"/api/v1/credentials/{cred_id}/export").json()
    assert validate_achievement_credential(downloaded) == []
    independent.verify(downloaded)
    achievement = downloaded["credentialSubject"]["achievement"]
    assert achievement["alignment"] == [
        {
            "type": ["Alignment"],
            "targetName": "Academic writing",
            # No link was given, so it points at the badge's own published definition.
            "targetUrl": f"{achievement['id']}#skill-1",
            "targetFramework": "UoL Skills",
        },
        {
            "type": ["Alignment"],
            "targetName": "Referencing",
            "targetUrl": "https://skills.example/referencing",
            "targetFramework": "ESCO",
            "targetCode": "S1.2",
        },
    ]
    # That published definition lists the same skills.
    outsider = TestClient(client.app)
    published = outsider.get(urlsplit(achievement["id"]).path).json()
    assert published["alignment"] == achievement["alignment"]

    # The student's page and the public page name them, linking only where a link was given.
    detail = w.get("s1", f"/api/v1/credentials/{cred_id}").json()
    assert detail["skills"] == [
        {"name": "Academic writing", "url": None, "framework": "UoL Skills"},
        {"name": "Referencing", "url": "https://skills.example/referencing", "framework": "ESCO"},
    ]
    url = w.put("s1", f"/api/v1/credentials/{cred_id}/share", {}).json()["share"]["url"]
    page = outsider.get(f"/verify/{_share_id(url)}").text
    assert "<li>Academic writing (UoL Skills)</li>" in page
    link = '<a href="https://skills.example/referencing" rel="nofollow noopener">Referencing</a>'
    assert f"<li>{link} (ESCO)</li>" in page


# ---- Scenario 6: student export ----------------------------------------------------------


def test_scenario_6_student_export_is_valid_ob3_with_verifiable_proof(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred_id = _issue_for(tenant, signer)
    student = _headers(tenant.institution_id, tenant.student_ids[0])
    r = client.get(f"/api/v1/credentials/{cred_id}/export", headers=student)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/ld+json")
    assert r.headers["content-disposition"].startswith('attachment; filename="academic-writing')
    assert r.headers["cache-control"] == "no-store"
    vc = r.json()
    assert {"VerifiableCredential", "OpenBadgeCredential"} <= set(vc["type"])
    assert validate_achievement_credential(vc) == []
    assert vc["proof"]["type"] == "DataIntegrityProof"
    assert vc["proof"]["cryptosuite"] == "eddsa-rdfc-2022"
    independent.verify(vc)
    # Learner name and email are not in the file by default (ADR-0007).
    assert "Student 0" not in r.text and "student.0@" not in r.text.lower()


# ---- Scenario 7: external verification ---------------------------------------------------


def test_scenario_7_external_verifier_reports_valid_then_revoked(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred_id = _issue_for(tenant, signer)
    student = _headers(tenant.institution_id, tenant.student_ids[0])
    admin = _headers(tenant.institution_id, tenant.admin_id)
    vc = client.get(f"/api/v1/credentials/{cred_id}/export", headers=student).json()
    share = client.put(f"/api/v1/credentials/{cred_id}/share", json={}, headers=student).json()
    share_id = _share_id(share["share"]["url"])
    public = TestClient(client.app)

    independent.verify(vc)  # signature and issuer key, by an unrelated implementation
    res = public.post("/api/v1/verify", json=vc).json()
    assert res["result"] == "verified"
    assert {c["name"] for c in res["checks"]} >= {"signature", "issuer", "status"}
    assert res["issuer"]["id"] == tenant.did

    body = {"reason_code": "issued_in_error", "reason_text": "Awarded to the wrong learner"}
    assert (
        client.post(f"/api/v1/credentials/{cred_id}/revoke", json=body, headers=admin).status_code
        == 200
    )
    assert public.post("/api/v1/verify", json=vc).json()["result"] == "revoked"
    page = public.get(f"/verify/{share_id}")
    assert page.status_code == 200 and "Revoked" in page.text
    assert public.get(f"/verify/{share_id}/verification.json").json()["result"] == "revoked"
    # The holder is told when and why (the category, not the staff explanation).
    mine = client.get(f"/api/v1/credentials/{cred_id}", headers=student).json()
    assert mine["withdrawal"]["state"] == "revoked"
    assert mine["withdrawal"]["reason_code"] == "issued_in_error"
    assert mine["withdrawal"]["on"]
    assert "wrong learner" not in str(mine["withdrawal"])

    tampered = {**vc, "validFrom": "2001-01-01T00:00:00Z"}
    assert public.post("/api/v1/verify", json=tampered).json()["result"] == "invalid"


# ---- Scenario 9: Canvas account closure --------------------------------------------------


def test_scenario_9_export_survives_account_closure(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred_id = _issue_for(tenant, signer)
    student_id = tenant.student_ids[0]
    student = _headers(tenant.institution_id, student_id)
    vc = client.get(f"/api/v1/credentials/{cred_id}/export", headers=student).json()

    # The learner leaves: account closed, memberships and Canvas identity gone.
    with owner_session() as db:
        db.execute(
            update(m.Membership)
            .where(m.Membership.user_id == student_id)
            .values(revoked_at=datetime.now(UTC))
        )
        db.execute(update(m.User).where(m.User.id == student_id).values(status="deleted"))
    assert client.get("/api/v1/learners/me", headers=student).status_code == 401

    # Their downloaded file is still independently verifiable without any session.
    independent.verify(vc)
    res = TestClient(client.app).post("/api/v1/verify", json=vc).json()
    assert res["result"] == "verified", res["checks"]


# ---- Scenario 11: LinkedIn ---------------------------------------------------------------


def test_scenario_11_linkedin_gets_certification_fields_and_a_working_url(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    cred_id = _issue_for(tenant, signer, version_id=tenant.expiring_version_id)
    student = _headers(tenant.institution_id, tenant.student_ids[0])
    before = client.get(f"/api/v1/credentials/{cred_id}", headers=student).json()["linkedin"]
    assert before["needs_share"] is True and before["add_to_profile_url"] is None

    out = client.put(f"/api/v1/credentials/{cred_id}/share", json={}, headers=student).json()
    li = out["linkedin"]
    fields = {f["key"]: f["value"] for f in li["fields"]}
    vc = client.get(f"/api/v1/credentials/{cred_id}/export", headers=student).json()
    assert fields["name"] == "Lab Safety"
    assert fields["organization"].startswith("W4 Test University")
    assert fields["issue_date"] == vc["validFrom"][:10]
    assert fields["expiration_date"] == vc["validUntil"][:10]
    assert fields["credential_id"] == vc["id"]
    assert fields["credential_url"] == out["share"]["url"]
    assert "does not import" in li["note"]

    link = urlsplit(li["add_to_profile_url"])
    assert (link.scheme, link.netloc, link.path) == ("https", "www.linkedin.com", "/profile/add")
    q = {k: v[0] for k, v in parse_qs(link.query).items()}
    issued = datetime.fromisoformat(vc["validFrom"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(vc["validUntil"].replace("Z", "+00:00"))
    assert q == {
        "startTask": "CERTIFICATION_NAME",
        "name": "Lab Safety",
        "organizationName": fields["organization"],
        "issueYear": str(issued.year),
        "issueMonth": str(issued.month),
        "expirationYear": str(expires.year),
        "expirationMonth": str(expires.month),
        "certUrl": out["share"]["url"],
        "certId": vc["id"],
    }
    # The URL LinkedIn shows is a working verification page for anyone.
    page = TestClient(client.app).get(urlsplit(q["certUrl"]).path)
    assert page.status_code == 200 and "Verified" in page.text

    # An institution can supply its LinkedIn company page id instead of a free-text name.
    with owner_session() as db:
        inst = db.get(m.Institution, tenant.institution_id)
        assert inst is not None
        inst.policy = {**(inst.policy or {}), "linkedin_organization_id": "1234567"}
    again = client.get(f"/api/v1/credentials/{cred_id}/share", headers=student).json()
    q2 = parse_qs(urlsplit(again["linkedin"]["add_to_profile_url"]).query)
    assert q2["organizationId"] == ["1234567"] and "organizationName" not in q2


# ---- privacy and control ----------------------------------------------------------------


def test_sharing_is_off_by_default_opaque_and_owner_only(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    a = _issue_for(tenant, signer, 0)
    b = _issue_for(tenant, signer, 1)
    s0 = _headers(tenant.institution_id, tenant.student_ids[0])
    s1 = _headers(tenant.institution_id, tenant.student_ids[1])
    admin = _headers(tenant.institution_id, tenant.admin_id)
    public = TestClient(client.app)

    with tenant_session(tenant.institution_id) as db:
        assert db.scalar(select(m.ShareGrant).where(m.ShareGrant.credential_id == a)) is None

    # Someone else's credential: not found, never "forbidden" (no disclosure).
    for path in ("", "/share"):
        assert client.get(f"/api/v1/credentials/{a}{path}", headers=s1).status_code == 404
        assert client.get(f"/api/v1/credentials/{a}{path}", headers=admin).status_code == 404
    assert client.put(f"/api/v1/credentials/{a}/share", json={}, headers=s1).status_code == 404
    assert (
        client.post(f"/api/v1/credentials/{a}/share/preview", json={}, headers=s1).status_code
        == 404
    )
    assert client.get(f"/api/v1/credentials/{uuid.uuid4()}", headers=s0).status_code == 404

    url_a = client.put(f"/api/v1/credentials/{a}/share", json={}, headers=s0).json()["share"]["url"]
    url_b = client.put(f"/api/v1/credentials/{b}/share", json={}, headers=s1).json()["share"]["url"]
    id_a, id_b = _share_id(url_a), _share_id(url_b)
    assert id_a != id_b and str(a) not in id_a and str(a.hex) not in id_a
    # 128-bit random: no shared prefix structure like sequential or time-ordered ids.
    assert len(set(id_a) | set(id_b)) > 12
    # Re-sharing keeps the same link; withdrawing then sharing again issues a new one.
    again = client.put(f"/api/v1/credentials/{a}/share", json={"show_name": True}, headers=s0)
    assert again.json()["share"]["url"] == url_a and again.json()["share"]["show_name"] is True
    client.delete(f"/api/v1/credentials/{a}/share", headers=s0)
    fresh = client.put(f"/api/v1/credentials/{a}/share", json={}, headers=s0).json()
    assert _share_id(fresh["share"]["url"]) != id_a

    # A withdrawn id and a never-issued id look exactly the same.
    gone, never = public.get(f"/verify/{id_a}"), public.get("/verify/" + "A" * 22)
    assert gone.status_code == never.status_code == 404 and gone.text == never.text
    assert public.get(f"/verify/{id_a}/credential.json").status_code == 404
    assert public.get("/verify/not-a-share-id").status_code == 404

    # Cross-tenant: a student from another institution cannot reach these credentials.
    other = build_tenant(get_settings(), students=1)
    outsider = _headers(other.institution_id, other.student_ids[0])
    assert client.get(f"/api/v1/credentials/{b}", headers=outsider).status_code == 404
    assert client.delete(f"/api/v1/credentials/{b}/share", headers=outsider).status_code == 404
    assert public.get(f"/verify/{id_b}").status_code == 200  # b's own share is unaffected


def test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data(
    client: TestClient, tenant: Tenant, signer: SignerClient
) -> None:
    with tenant_session(tenant.institution_id) as db:
        db.execute(
            update(m.User)
            .where(m.User.id == tenant.student_ids[0])
            .values(display_name="Eilidh Featherstonehaugh")
        )
    cred_id = _issue_for(
        tenant,
        signer,
        evidence=[
            {"kind": "artefact", "narrative": "Reflective essay on lab practice", "public": True}
        ],
    )
    student = _headers(tenant.institution_id, tenant.student_ids[0])
    public = TestClient(client.app)

    hidden = client.post(
        f"/api/v1/credentials/{cred_id}/share/preview", json={}, headers=student
    ).json()
    assert hidden["public"]["recipient_name"] is None and hidden["public"]["evidence"] == []
    rows = {r["label"]: r["value"] for r in hidden["visible"]}
    assert rows["Your name"] == "Not shown" and rows["Evidence"] == "Not shown"
    assert any("email" in s for s in hidden["never_shared"])

    opts = {"show_name": True, "show_evidence": True}
    shown = client.post(
        f"/api/v1/credentials/{cred_id}/share/preview", json=opts, headers=student
    ).json()
    assert shown["public"]["recipient_name"] == "Eilidh Featherstonehaugh"
    assert [e["narrative"] for e in shown["public"]["evidence"]] == [
        "Reflective essay on lab practice"
    ]
    # Previewing changes nothing: still not shared.
    assert (
        client.get(f"/api/v1/credentials/{cred_id}/share", headers=student).json()["share"][
            "shared"
        ]
        is False
    )

    out = client.put(f"/api/v1/credentials/{cred_id}/share", json=opts, headers=student).json()
    assert out["preview"]["public"] == shown["public"]
    page = public.get(f"/verify/{_share_id(out['share']['url'])}")
    assert "Eilidh Featherstonehaugh" in page.text
    # The name is said once ("Awarded to …"), not repeated in the facts table.
    assert page.text.count("Eilidh Featherstonehaugh") == 1
    assert "Reflective essay on lab practice" in page.text
    og = _og(page.text)
    assert og["og:title"].startswith("Academic Writing Foundations")
    assert all("Featherstonehaugh" not in v and "Eilidh" not in v for v in og.values())
    assert "Featherstonehaugh" not in re.sub(r"<body>.*</body>", "", page.text, flags=re.S)
    assert page.headers["content-security-policy"].startswith("default-src 'none'")
    assert page.headers["referrer-policy"] == "no-referrer"

    # Turning the name off again takes it off the page.
    client.put(f"/api/v1/credentials/{cred_id}/share", json={}, headers=student)
    page = public.get(f"/verify/{_share_id(out['share']['url'])}")
    assert "Featherstonehaugh" not in page.text and "Reflective essay" not in page.text


def test_public_check_page_and_robots(client: TestClient) -> None:
    public = TestClient(client.app)
    page = public.get("/verify")
    assert page.status_code == 200 and 'type="file"' in page.text
    assert "does not independently prove" in page.text
    js = public.get("/verify-assets/check.js")
    assert js.status_code == 200 and "/api/v1/verify" in js.text
    # The result is explained in plain words, the same ones as a shared badge page, and the
    # technical checks are folded away; a file that is not JSON gets advice, not an API error.
    words = page.text.split('id="result-words">', 1)[1].split("</script>", 1)[0]
    parsed = json.loads(words)
    assert parsed["text"]["invalid"].startswith("This badge failed its checks")
    assert set(parsed["style"]) >= {"verified", "invalid", "revoked", "expired"}
    assert "Show the individual checks" in js.text and "NOT_JSON" in js.text
    assert "request body" not in js.text
    robots = public.get("/robots.txt")
    assert robots.text == "User-agent: *\nDisallow: /\n"
    assert "noindex" in page.headers["x-robots-tag"]
    assert "noindex" in public.get("/api/v1/learners/me").headers["x-robots-tag"]
    assert public.get("/assets/public/" + "0" * 64 + ".svg").status_code == 404
    assert public.get("/assets/public/../../etc/passwd").status_code == 404
