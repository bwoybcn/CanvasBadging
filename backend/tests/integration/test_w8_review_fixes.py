# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for the 13 Nov 2026 review (docs/reports/code-review-2026-11-13.md).

C1: a credential waiting for its signature is never signed once its award has been cancelled.
C3: compromising a key that was already rotated out still re-signs the issuer's status lists.
C4: the signer only retires or destroys a key once the database change has committed.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text, update

from opencredential.authz import policy as authz
from opencredential.db import models as m
from opencredential.db.session import tenant_session
from opencredential.governance import privacy
from opencredential.institutions import keys as key_service
from opencredential.issuance import decisions
from opencredential.issuance.service import IssuanceError, issue, pending
from opencredential.jobs import tasks
from opencredential.settings import get_settings
from opencredential.signer_client import SignerClient
from opencredential.status import service as status_service
from opencredential.status.compromise import respond_to_compromise
from opencredential.verification.service import Outcome, Verifier
from opencredential.verification.sources import DefaultSources, own_origins
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


def _decide(t: Tenant, student: int = 0) -> uuid.UUID:
    with tenant_session(t.institution_id) as db:
        d, _ = decisions.decide(
            db,
            institution_id=t.institution_id,
            user_id=t.student_ids[student],
            version_id=t.version_id,
            kind="manual",
            justification="Completed all modules (test)",
            decided_by=t.admin_id,
        )
        return d.id


def _issue(t: Tenant, signer: SignerClient, decision_id: uuid.UUID, **kw: Any):  # type: ignore[no-untyped-def]
    return issue(t.institution_id, decision_id, signer=signer, settings=get_settings(), **kw)


def _leave_pending(t: Tenant, signer: SignerClient, decision_id: uuid.UUID) -> None:
    def crash(at: str) -> None:
        if at == "after_prepare":
            raise ConnectionError("signer outage (simulated)")

    with pytest.raises(ConnectionError):
        _issue(t, signer, decision_id, fault=crash)


def _credential(t: Tenant, decision_id: uuid.UUID) -> m.Credential:
    with tenant_session(t.institution_id) as db:
        cred = db.scalar(select(m.Credential).where(m.Credential.award_decision_id == decision_id))
        assert cred is not None
        db.expunge(cred)
        return cred


def _reject(t: Tenant, decision_id: uuid.UUID) -> None:
    with tenant_session(t.institution_id) as db:
        db.execute(
            update(m.AwardDecision)
            .where(m.AwardDecision.id == decision_id)
            .values(status="rejected", rejection_reason="test")
        )


def test_c1_pending_credential_of_rejected_award_is_not_signed(
    tenant: Tenant, signer: SignerClient
) -> None:
    decision = _decide(tenant)
    _leave_pending(tenant, signer, decision)
    _reject(tenant, decision)

    result = _issue(tenant, signer, decision)
    assert result.outcome == "cancelled" and result.status_list_id is None
    cred = _credential(tenant, decision)
    assert cred.status == "failed" and cred.signed_json is None
    with tenant_session(tenant.institution_id) as db:
        assert db.get(m.AwardDecision, decision).status == "rejected"  # type: ignore[union-attr]
        assert pending(db) == []
    # Retrying is refused rather than signing.
    with pytest.raises(IssuanceError):
        _issue(tenant, signer, decision)


def test_c1_award_cancelled_while_signing_is_not_issued(
    tenant: Tenant, signer: SignerClient
) -> None:
    decision = _decide(tenant)

    def cancel_mid_flight(at: str) -> None:
        if at == "after_sign":
            _reject(tenant, decision)

    result = _issue(tenant, signer, decision, fault=cancel_mid_flight)
    assert result.outcome == "cancelled"
    cred = _credential(tenant, decision)
    assert cred.status == "failed" and cred.signed_json is None


def test_c1_erasure_cancels_a_credential_waiting_for_its_signature(
    tenant: Tenant, signer: SignerClient
) -> None:
    decision = _decide(tenant)
    _leave_pending(tenant, signer, decision)
    with tenant_session(tenant.institution_id) as db:
        actor = authz.load_actor(db, tenant.admin_id, tenant.institution_id)
        counts = privacy.erase(db, actor, tenant.student_ids[0], confirm="ERASE")
    assert counts["awards_cancelled"] == 1
    assert counts["unsigned_credentials_cancelled"] == 1
    assert _credential(tenant, decision).status == "failed"
    # Reconciliation (or a late job) cannot bring it back.
    with pytest.raises(IssuanceError):
        _issue(tenant, signer, decision)
    assert _credential(tenant, decision).status == "failed"


# ---- C3 / C4: key compromise and rotation --------------------------------------------------


@pytest.fixture
def web_tenant(signer: SignerClient) -> Tenant:
    return build_tenant(
        get_settings(),
        did_method="web",
        verification_host=f"badges-{uuid.uuid4().hex[:6]}.example.ac.uk",
    )


def _publish(t: Tenant, signer: SignerClient, list_id: uuid.UUID) -> None:
    with tenant_session(t.institution_id) as db:
        status_service.publish(db, list_id, signer, get_settings())


def _signed(t: Tenant, credential_id: uuid.UUID) -> dict[str, Any]:
    with tenant_session(t.institution_id) as db:
        cred = db.get(m.Credential, credential_id)
        assert cred is not None and cred.signed_json is not None
        return copy.deepcopy(cred.signed_json)


def _signer_refusal(signer: SignerClient, key_id: uuid.UUID) -> str:
    """What the signer says when asked to sign with ``key_id`` (an empty document is refused
    either way; a retired or destroyed key is refused *before* the document is looked at)."""
    try:
        signer.sign(issuer_key_id=key_id, verification_method_id="did:web:x#k", document={})
    except Exception as exc:
        return str(exc)
    return "signed"


class _Abort(Exception):
    pass


def test_c3_compromise_of_a_retired_key_republishes_lists_with_the_current_key(
    web_tenant: Tenant, signer: SignerClient
) -> None:
    t = web_tenant
    old = _issue(t, signer, _decide(t, 0))
    _publish(t, signer, old.status_list_id)
    with tenant_session(t.institution_id) as db:
        issuer = db.get(m.Issuer, t.issuer_id)
        assert issuer is not None
        current = key_service.rotate(db, issuer, signer, actor_user_id=t.admin_id).id
    new = _issue(t, signer, _decide(t, 1))
    _publish(t, signer, new.status_list_id)

    with tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None and key.state == "retired"
        out = respond_to_compromise(
            db,
            key,
            signer,
            get_settings(),
            reason="old laptop found (drill)",
            actor_user_id=t.admin_id,
        )
    assert out.replacement_key_id is None and out.credentials_revoked == 1
    assert out.status_lists_republished >= 1

    verifier = Verifier(signer, DefaultSources(own_origins(get_settings().public_base_url)))
    # the list no longer carries the revoked key's signature, so B's credential still verifies
    assert verifier.verify(_signed(t, new.credential_id)).result == Outcome.verified
    assert verifier.verify(_signed(t, old.credential_id)).result == Outcome.invalid
    with tenant_session(t.institution_id) as db:
        lists = db.scalars(select(m.StatusList).where(m.StatusList.issuer_id == t.issuer_id))
        for sl in lists:
            if sl.published_credential:
                vm = sl.published_credential["proof"]["verificationMethod"]
                assert vm.endswith(str(current))


def test_c4_rolled_back_compromise_leaves_the_signer_untouched(
    web_tenant: Tenant, signer: SignerClient
) -> None:
    t = web_tenant
    with pytest.raises(_Abort), tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None
        respond_to_compromise(
            db,
            key,
            signer,
            get_settings(),
            reason="false alarm (drill)",
            actor_user_id=t.admin_id,
        )
        raise _Abort  # e.g. publishing a status list failed after the key was handled

    with tenant_session(t.institution_id) as db:
        assert db.get(m.IssuerKey, t.key_id).state == "active"  # type: ignore[union-attr]
        queued = db.execute(
            text(
                "SELECT count(*) FROM jobs.procrastinate_jobs"
                " WHERE task_name = 'oc:signer_key_lifecycle' AND args->>'key_id' = :k"
            ),
            {"k": str(t.key_id)},
        ).scalar()
    assert queued == 0
    assert "KEY_NOT_ACTIVE" not in _signer_refusal(signer, t.key_id)
    # and the issuer can still issue with its key
    assert _issue(t, signer, _decide(t, 0)).outcome == "issued"


def test_c4_rolled_back_rotation_keeps_the_old_key_signing(
    web_tenant: Tenant, signer: SignerClient
) -> None:
    t = web_tenant
    with pytest.raises(_Abort), tenant_session(t.institution_id) as db:
        issuer = db.get(m.Issuer, t.issuer_id)
        assert issuer is not None
        key_service.rotate(db, issuer, signer, actor_user_id=t.admin_id)
        raise _Abort
    assert "KEY_NOT_ACTIVE" not in _signer_refusal(signer, t.key_id)
    assert _issue(t, signer, _decide(t, 0)).outcome == "issued"


def test_c4_committed_compromise_reaches_the_signer_at_once(
    web_tenant: Tenant, signer: SignerClient
) -> None:
    t = web_tenant
    with tenant_session(t.institution_id) as db:
        key = db.get(m.IssuerKey, t.key_id)
        assert key is not None
        respond_to_compromise(
            db, key, signer, get_settings(), reason="drill", actor_user_id=t.admin_id
        )
        # nothing irreversible has happened before the commit
        assert "KEY_NOT_ACTIVE" not in _signer_refusal(signer, t.key_id)
    assert "KEY_NOT_ACTIVE" in _signer_refusal(signer, t.key_id)
    # the queued job is the durable retry, and repeating it is harmless
    assert tasks.signer_key_lifecycle(str(t.key_id), "destroy") == "destroy"
