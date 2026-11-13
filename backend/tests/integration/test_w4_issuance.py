# SPDX-License-Identifier: AGPL-3.0-or-later
"""W4 end to end: real signing, idempotent issuance, revocation, verification outcomes, keys.

Runs against PostgreSQL and the real signer (no mocked issuance, spec R-0.1). Every credential
issued here is also checked with the independent Python verifier (C-INDEP-01).
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from opencredential.api.app import create_app
from opencredential.authz import sessions
from opencredential.db import models as m
from opencredential.db.session import tenant_session
from opencredential.institutions import keys as key_service
from opencredential.issuance import decisions
from opencredential.issuance.schema import validate_achievement_credential
from opencredential.issuance.service import IssuanceError, issue
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient, SignerUnavailable
from opencredential.status import service as status_service
from opencredential.status.compromise import respond_to_compromise
from opencredential.verification.service import Outcome, Verifier
from opencredential.verification.sources import DefaultSources, Unavailable, own_origins
from tests.independent import verifier as independent
from tests.integration.w4_factory import Tenant, build_tenant

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def signer(database: None, signer_available: bool):  # type: ignore[no-untyped-def]
    client = SignerClient(get_settings())
    yield client
    client.close()


@pytest.fixture
def tenant(signer: SignerClient) -> Tenant:
    return build_tenant(get_settings())


def _decide(t: Tenant, student: int = 0, version: uuid.UUID | None = None) -> uuid.UUID:
    with tenant_session(t.institution_id) as db:
        d, _ = decisions.decide(
            db,
            institution_id=t.institution_id,
            user_id=t.student_ids[student],
            version_id=version or t.version_id,
            kind="manual",
            justification="Completed all modules (test)",
            decided_by=t.admin_id,
        )
        return d.id


def _issue(t: Tenant, signer: SignerClient, decision_id: uuid.UUID, **kw: Any):  # type: ignore[no-untyped-def]
    return issue(t.institution_id, decision_id, signer=signer, settings=get_settings(), **kw)


def _signed(t: Tenant, credential_id: uuid.UUID) -> dict[str, Any]:
    with tenant_session(t.institution_id) as db:
        cred = db.get(m.Credential, credential_id)
        assert cred is not None and cred.signed_json is not None
        return copy.deepcopy(cred.signed_json)


def _publish(t: Tenant, signer: SignerClient, list_id: uuid.UUID) -> None:
    with tenant_session(t.institution_id) as db:
        status_service.publish(db, list_id, signer, get_settings())


def _verifier(signer: SignerClient) -> Verifier:
    return Verifier(signer, DefaultSources(own_origins(get_settings().public_base_url)))


def _count(t: Tenant, model: Any, **where: Any) -> int:
    with tenant_session(t.institution_id) as db:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return int(db.scalar(q) or 0)


# ---- issuance ---------------------------------------------------------------------------


def test_issued_credential_is_genuine_ob3(tenant: Tenant, signer: SignerClient) -> None:
    result = _issue(tenant, signer, _decide(tenant))
    assert result.outcome == "issued"
    vc = _signed(tenant, result.credential_id)

    assert validate_achievement_credential(vc) == []  # official 1EdTech JSON Schema
    assert vc["proof"]["cryptosuite"] == "eddsa-rdfc-2022"
    assert vc["issuer"]["id"] == tenant.did
    assert "@" not in str(vc["credentialSubject"]["identifier"][0]["identityHash"])
    assert "student." not in str(vc).lower()  # no raw email anywhere
    independent.verify(vc)  # a second, unrelated implementation agrees

    _publish(tenant, signer, result.status_list_id)
    outcome = _verifier(signer).verify(vc)
    assert outcome.result == Outcome.verified, outcome.checks
    assert {c.name for c in outcome.checks} >= {
        "structure",
        "issuer",
        "verification_method",
        "signature",
        "achievement_integrity",
        "validity",
        "status",
    }
    assert outcome.issuer_trust["known_issuer"] is True


def test_status_list_credential_is_signed_and_independently_verifiable(
    tenant: Tenant, signer: SignerClient
) -> None:
    result = _issue(tenant, signer, _decide(tenant))
    _publish(tenant, signer, result.status_list_id)
    with tenant_session(tenant.institution_id) as db:
        sl = db.get(m.StatusList, result.status_list_id)
        assert sl is not None and sl.published_credential is not None
        list_vc = copy.deepcopy(sl.published_credential)
    assert list_vc["type"] == ["VerifiableCredential", "BitstringStatusListCredential"]
    assert list_vc["credentialSubject"]["statusPurpose"] == "revocation"
    independent.verify(list_vc)


def test_duplicate_event_creates_no_duplicate(tenant: Tenant, signer: SignerClient) -> None:
    """Scenario 3 (E3): processing the same completion event again creates nothing new."""
    first = _decide(tenant)
    again = _decide(tenant)
    assert first == again
    a = _issue(tenant, signer, first)
    b = _issue(tenant, signer, again)
    assert (a.outcome, b.outcome) == ("issued", "already_issued")
    assert a.credential_id == b.credential_id
    assert _count(tenant, m.Credential, user_id=tenant.student_ids[0]) == 1


def test_second_decision_for_same_learner_is_a_duplicate(
    tenant: Tenant, signer: SignerClient
) -> None:
    first = _decide(tenant)
    a = _issue(tenant, signer, first)
    with tenant_session(tenant.institution_id) as db:
        auto, created = decisions.decide(
            db,
            institution_id=tenant.institution_id,
            user_id=tenant.student_ids[0],
            version_id=tenant.version_id,
            kind="automatic",
            justification="rule met",
        )
    # W5's uq_award_decisions_live allows one live decision per learner and version, so the
    # second decision of another kind resolves to the first one instead of creating a duplicate.
    assert not created and auto.id == first
    b = _issue(tenant, signer, auto.id)
    assert b.outcome == "already_issued" and b.credential_id == a.credential_id
    assert _count(tenant, m.Credential, user_id=tenant.student_ids[0]) == 1


@pytest.mark.parametrize("step", ["after_prepare", "after_sign", "before_commit"])
def test_interrupted_issuance_recovers_without_duplicates(
    tenant: Tenant, signer: SignerClient, step: str
) -> None:
    """Scenario 12 (E12): a crash at any step, then a retry, gives exactly one good credential."""
    decision = _decide(tenant)

    def crash(at: str) -> None:
        if at == step:
            raise ConnectionError(f"simulated failure at {at}")

    with pytest.raises(ConnectionError):
        _issue(tenant, signer, decision, fault=crash)
    with tenant_session(tenant.institution_id) as db:
        rows = db.scalars(
            select(m.Credential).where(m.Credential.award_decision_id == decision)
        ).all()
        assert len(rows) == 1 and rows[0].status == "pending_signature"
        assert db.get(m.AwardDecision, decision).status == "ready"  # type: ignore[union-attr]

    result = _issue(tenant, signer, decision)
    assert result.outcome == "issued"
    assert _count(tenant, m.Credential, award_decision_id=decision) == 1
    assert _count(tenant, m.StatusListBit, credential_id=result.credential_id) == 1
    with tenant_session(tenant.institution_id) as db:
        cred = db.get(m.Credential, result.credential_id)
        assert cred is not None and cred.attempts == 2
        assert db.get(m.AwardDecision, decision).status == "issued"  # type: ignore[union-attr]
    independent.verify(_signed(tenant, result.credential_id))


def test_signer_outage_is_transient(tenant: Tenant, signer: SignerClient) -> None:
    decision = _decide(tenant)
    dead = SignerClient(get_settings().model_copy(update={"signer_url": "http://127.0.0.1:9"}))
    with pytest.raises(SignerUnavailable):
        _issue(tenant, dead, decision)
    with tenant_session(tenant.institution_id) as db:
        cred = db.scalar(select(m.Credential).where(m.Credential.award_decision_id == decision))
        assert cred is not None and cred.last_error == "SignerUnavailable"
    assert _issue(tenant, signer, decision).outcome == "issued"


def test_issued_credentials_are_immutable(tenant: Tenant, signer: SignerClient, owner_conn) -> None:  # type: ignore[no-untyped-def]
    r = _issue(tenant, signer, _decide(tenant))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        owner_conn.execute(
            "UPDATE app.credentials SET signed_json = '{}' WHERE id = %s", [r.credential_id]
        )
    owner_conn.rollback()
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        owner_conn.execute("DELETE FROM app.credentials WHERE id = %s", [r.credential_id])
    owner_conn.rollback()


def test_unapproved_issuer_cannot_issue(tenant: Tenant, signer: SignerClient, owner_conn) -> None:  # type: ignore[no-untyped-def]
    owner_conn.execute(
        "UPDATE app.issuers SET approved_by = NULL WHERE id = %s", [tenant.issuer_id]
    )
    owner_conn.commit()
    with pytest.raises(IssuanceError, match="approved"):
        _issue(tenant, signer, _decide(tenant))


def test_app_role_cannot_read_private_keys(app_conn) -> None:  # type: ignore[no-untyped-def]
    """S-KEYS-01: key material lives in schema ``keys``, readable only by the signer role."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT ciphertext FROM keys.private_keys")


# ---- revocation, expiry and the five outcomes ------------------------------------------


def test_downloaded_copy_is_recognised_as_revoked(tenant: Tenant, signer: SignerClient) -> None:
    """Scenario 8 (E8)."""
    r = _issue(tenant, signer, _decide(tenant))
    downloaded = _signed(tenant, r.credential_id)  # the learner's copy, taken before revocation
    _publish(tenant, signer, r.status_list_id)
    assert _verifier(signer).verify(downloaded).result == Outcome.verified

    with tenant_session(tenant.institution_id) as db:
        rev = status_service.revoke(
            db,
            r.credential_id,
            reason_code="issued_in_error",
            reason_text="test",
            actor_user_id=tenant.admin_id,
        )
        status_service.publish(db, r.status_list_id, signer, get_settings())
        assert rev.changed
        ev = db.scalars(
            select(m.CredentialStatusEvent).where(
                m.CredentialStatusEvent.credential_id == r.credential_id
            )
        ).one()
        assert ev.reason == "issued_in_error" and ev.actor_id == tenant.admin_id
    result = _verifier(signer).verify(downloaded)
    assert result.result == Outcome.revoked
    # the record is kept, not deleted
    assert _count(tenant, m.Credential, id=r.credential_id) == 1


def test_revocation_requires_a_reason(tenant: Tenant, signer: SignerClient) -> None:
    r = _issue(tenant, signer, _decide(tenant))
    with tenant_session(tenant.institution_id) as db, pytest.raises(status_service.StatusError):
        status_service.revoke(
            db, r.credential_id, reason_code="because", actor_user_id=tenant.admin_id
        )


def test_expired(tenant: Tenant, signer: SignerClient) -> None:
    r = _issue(tenant, signer, _decide(tenant, version=tenant.expiring_version_id))
    _publish(tenant, signer, r.status_list_id)
    vc = _signed(tenant, r.credential_id)
    assert vc["validUntil"]
    later = datetime.now(UTC) + timedelta(days=31)
    # (publish a list valid at that time so only expiry is in play)
    with tenant_session(tenant.institution_id) as db:
        status_service.publish(
            db, r.status_list_id, signer, get_settings(), now=later - timedelta(days=1)
        )
    assert _verifier(signer).verify(vc, now=later).result == Outcome.expired


def test_tampered_is_invalid(tenant: Tenant, signer: SignerClient) -> None:
    r = _issue(tenant, signer, _decide(tenant))
    _publish(tenant, signer, r.status_list_id)
    vc = _signed(tenant, r.credential_id)
    vc["credentialSubject"]["achievement"]["name"] = "PhD in Everything"
    res = _verifier(signer).verify(vc)
    assert res.result == Outcome.invalid
    assert {c.name: c.status for c in res.checks}["signature"] == "fail"
    with pytest.raises(independent.NotVerified):
        independent.verify(vc)

    broken = _signed(tenant, r.credential_id)
    del broken["credentialSubject"]["achievement"]["criteria"]
    assert _verifier(signer).verify(broken).result == Outcome.invalid


def test_status_infrastructure_failure_is_unable_to_verify(
    tenant: Tenant, signer: SignerClient
) -> None:
    r = _issue(tenant, signer, _decide(tenant))
    vc = _signed(tenant, r.credential_id)
    # list never published -> the status endpoint has nothing valid to serve
    res = _verifier(signer).verify(vc)
    assert res.result == Outcome.unable_to_verify
    assert {c.name: c.status for c in res.checks}["status"] == "unavailable"

    class DownSources(DefaultSources):
        def status_list(self, url: str) -> dict[str, Any]:
            raise Unavailable("connection refused")

    res = Verifier(signer, DownSources(set())).verify(vc)
    assert res.result == Outcome.unable_to_verify  # never "invalid" or "revoked"

    dead = SignerClient(get_settings().model_copy(update={"signer_url": "http://127.0.0.1:9"}))
    res = Verifier(dead, DefaultSources(set())).verify(vc)
    assert res.result == Outcome.unable_to_verify


# ---- keys: did:web, rotation, compromise ------------------------------------------------


@pytest.fixture
def web_tenant(signer: SignerClient) -> Tenant:
    return build_tenant(
        get_settings(),
        did_method="web",
        verification_host=f"badges-{uuid.uuid4().hex[:6]}.example.ac.uk",
    )


def test_did_web_rotation_keeps_old_credentials_verifiable(
    web_tenant: Tenant, signer: SignerClient
) -> None:
    t = web_tenant
    old = _issue(t, signer, _decide(t, 0))
    _publish(t, signer, old.status_list_id)
    with tenant_session(t.institution_id) as db:
        issuer = db.get(m.Issuer, t.issuer_id)
        assert issuer is not None
        new_key = key_service.rotate(db, issuer, signer, actor_user_id=t.admin_id)
        assert db.get(m.IssuerKey, t.key_id).state == "retired"  # type: ignore[union-attr]
        new_key_id = new_key.id
    new = _issue(t, signer, _decide(t, 1))
    _publish(t, signer, new.status_list_id)

    old_vc, new_vc = _signed(t, old.credential_id), _signed(t, new.credential_id)
    assert old_vc["proof"]["verificationMethod"] != new_vc["proof"]["verificationMethod"]
    assert new_vc["proof"]["verificationMethod"].endswith(str(new_key_id))
    v = _verifier(signer)
    assert v.verify(old_vc).result == Outcome.verified
    assert v.verify(new_vc).result == Outcome.verified

    # the published DID document carries both keys; the independent verifier uses it too
    with TestClient(create_app(get_settings())) as client:
        host = t.did.split(":")[2]
        slug = t.did.split(":")[-1]
        doc = client.get(f"/issuers/{slug}/did.json", headers={"host": host}).json()
    assert len(doc["verificationMethod"]) == 2
    independent.verify(old_vc, {t.did: doc})
    independent.verify(new_vc, {t.did: doc})

    # the retired key can no longer sign
    with pytest.raises(Exception, match="KEY_NOT_ACTIVE"):
        signer.sign(
            issuer_key_id=t.key_id,
            verification_method_id=old_vc["proof"]["verificationMethod"],
            document={},
        )


def test_key_compromise_procedure(web_tenant: Tenant, signer: SignerClient) -> None:
    """I-KEYS-COMPROMISE: drill of docs/security/key-compromise.md steps 2-6."""
    t = web_tenant
    victims = [_issue(t, signer, _decide(t, i)) for i in range(2)]
    for r in victims:
        _publish(t, signer, r.status_list_id)
    copies = [_signed(t, r.credential_id) for r in victims]

    with tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None
        out = respond_to_compromise(
            db,
            key,
            signer,
            get_settings(),
            reason="laptop stolen (drill)",
            actor_user_id=t.admin_id,
        )
    assert out.credentials_revoked == 2 and out.status_lists_republished >= 1
    assert out.replacement_key_id is not None

    with tenant_session(t.institution_id) as db:
        assert db.get(m.IssuerKey, t.key_id).state == "revoked"  # type: ignore[union-attr]
        issuer = db.get(m.Issuer, t.issuer_id)
        keys = list(db.scalars(select(m.IssuerKey).where(m.IssuerKey.issuer_id == t.issuer_id)))
        from opencredential.institutions.identity import did_document

        doc = did_document(issuer, keys)  # type: ignore[arg-type]
    assert all(vm["id"].endswith(str(out.replacement_key_id)) for vm in doc["verificationMethod"])
    # anything signed by the compromised key (including forgeries) now fails
    for vc in copies:
        assert _verifier(signer).verify(vc).result == Outcome.invalid
    # new issuance works with the replacement key
    fresh = _issue(t, signer, _decide(t, 2))
    _publish(t, signer, fresh.status_list_id)
    assert _verifier(signer).verify(_signed(t, fresh.credential_id)).result == Outcome.verified

    # step 7: affected learners get replacement credentials (explicit, idempotent reissue)
    with tenant_session(t.institution_id) as db:
        originals = [
            db.get(m.AwardDecision, db.get(m.Credential, r.credential_id).award_decision_id)  # type: ignore[union-attr]
            for r in victims
        ]
        again = [
            decisions.reissue(db, d, justification="key compromise", decided_by=t.admin_id)  # type: ignore[arg-type]
            for d in originals
        ]
        twice = decisions.reissue(
            db,
            originals[0],  # type: ignore[arg-type]
            justification="key compromise",
            decided_by=t.admin_id,
        )
        assert twice.id == again[0].id and again[0].issuance_seq == 2
        live = db.get(m.Credential, fresh.credential_id)
        assert live is not None
        with pytest.raises(decisions.DecisionError, match="revoke it first"):
            decisions.reissue(
                db,
                db.get(m.AwardDecision, live.award_decision_id),  # type: ignore[arg-type]
                justification="not allowed while live",
                decided_by=t.admin_id,
            )
        new_ids = [d.id for d in again]
    for did in new_ids:
        replacement = _issue(t, signer, did)
        _publish(t, signer, replacement.status_list_id)
        vc = _signed(t, replacement.credential_id)
        assert _verifier(signer).verify(vc).result == Outcome.verified
        assert vc["proof"]["verificationMethod"].endswith(str(out.replacement_key_id))


# ---- HTTP surface -----------------------------------------------------------------------


def _token(t: Tenant, user_id: uuid.UUID) -> dict[str, str]:
    token, _ = sessions.issue(
        get_settings(), user_id=user_id, institution_id=t.institution_id, method="dev"
    )
    return {"authorization": f"Bearer {token}"}


def test_http_export_verify_and_revoke(tenant: Tenant, signer: SignerClient) -> None:
    r = _issue(tenant, signer, _decide(tenant))
    _publish(tenant, signer, r.status_list_id)
    student = _token(tenant, tenant.student_ids[0])
    admin = _token(tenant, tenant.admin_id)
    with TestClient(create_app(get_settings())) as client:
        mine = client.get("/api/v1/learners/me/credentials", headers=student).json()
        assert [c["status"] for c in mine] == ["active"]

        dl = client.get(f"/api/v1/credentials/{r.credential_id}/export", headers=student)
        assert dl.status_code == 200 and dl.headers["content-type"].startswith(
            "application/ld+json"
        )
        downloaded = dl.json()
        other = _token(tenant, tenant.student_ids[1])
        assert (
            client.get(f"/api/v1/credentials/{r.credential_id}/export", headers=other).status_code
            == 403
        )

        res = client.post("/api/v1/verify", json=downloaded).json()
        assert res["result"] == "verified" and res["label"] == "Verified"
        assert res["achievement"]["name"] == "Academic Writing Foundations"

        url = downloaded["credentialStatus"]["statusListCredential"]
        path = url.split("://", 1)[1].split("/", 1)[1]
        sl = client.get("/" + path)
        assert sl.status_code == 200 and "max-age=300" in sl.headers["cache-control"]

        body = {"reason_code": "issued_in_error", "reason_text": "Awarded to the wrong learner"}
        assert (
            client.post(
                f"/api/v1/credentials/{r.credential_id}/revoke", json=body, headers=student
            ).status_code
            == 403
        )
        rv = client.post(f"/api/v1/credentials/{r.credential_id}/revoke", json=body, headers=admin)
        assert rv.status_code == 200 and rv.json()["status_list_published"] is True

        assert client.post("/api/v1/verify", json=downloaded).json()["result"] == "revoked"
        assert client.post("/api/v1/verify", content=b"not json").status_code == 422
        mine = client.get("/api/v1/learners/me/credentials", headers=student).json()
        assert mine[0]["status"] == "revoked"

        ach_id = downloaded["credentialSubject"]["achievement"]["id"]
        ach = client.get("/" + ach_id.split("://", 1)[1].split("/", 1)[1])
        assert ach.status_code == 200 and ach.json()["name"] == "Academic Writing Foundations"


def test_issue_task_accepts_w5_contract(tenant: Tenant, signer: SignerClient) -> None:
    """W5 defers oc:issue_credential(decision_id, institution_id, subject_type, subject_id, ...)."""
    from opencredential.jobs.tasks import issue_credential

    d = _decide(tenant)
    kwargs = {
        "decision_id": str(d),
        "institution_id": str(tenant.institution_id),
        "subject_type": "award_decision",
        "subject_id": str(d),
        "_trace": "x",
    }
    assert issue_credential(**kwargs) == "issued"
    assert issue_credential(**kwargs) == "already_issued"
    with tenant_session(tenant.institution_id) as db:
        assert db.get(m.AwardDecision, d).status == "issued"  # type: ignore[union-attr]
