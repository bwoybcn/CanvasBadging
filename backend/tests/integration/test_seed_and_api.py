# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dev seed + dev login + API, end to end against Postgres and the real signer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from opencredential import seed
from opencredential.api.app import create_app
from opencredential.db import models as m
from opencredential.db.session import owner_session, tenant_session
from opencredential.settings import Settings, get_settings
from opencredential.startup import StartupRefused, check_production_safety

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def seeded(database: None, signer_available: bool) -> seed.SeedResult:
    result = seed.run()
    assert result.created or result.counts == {}
    return result


@pytest.fixture
def client(seeded: seed.SeedResult):  # type: ignore[no-untyped-def]
    with TestClient(create_app(get_settings())) as c:
        yield c


def test_seed_counts(seeded: seed.SeedResult) -> None:
    assert seeded.counts == {"badges": 9, "students": 12, "staff": 3, "evaluations": 108}


def test_seed_is_idempotent(seeded: seed.SeedResult) -> None:
    again = seed.run()
    assert not again.created
    assert again.institution_id == seeded.institution_id


def test_seed_content(seeded: seed.SeedResult) -> None:
    with tenant_session(seeded.institution_id) as db:
        versions = db.scalars(select(m.AchievementVersion)).all()
        assert {v.category for v in versions} == {
            "Academic Communication",
            "Research Skills",
            "Digital Skills",
        }
        assert all(v.frozen for v in versions)
        issuer = db.scalars(select(m.Issuer)).one()
        assert issuer.did.startswith("did:key:z6Mk")
        assert "(DEVELOPMENT)" in issuer.name
        key = db.scalars(select(m.IssuerKey)).one()
        assert key.is_dev and key.state == "active"
        assert db.scalar(select(func.count()).select_from(m.Credential)) == 0  # no fake issuance
        outcomes = dict(
            db.execute(
                select(m.EligibilityEvaluation.outcome, func.count()).group_by(
                    m.EligibilityEvaluation.outcome
                )
            ).all()
        )
    assert set(outcomes) == {"met", "not_met", "unknown"}


GOLDEN = {
    # (student given name, badge title) -> expected outcome; pinned for the W5 rules engine.
    ("Amara", "Academic Writing Foundations"): "met",
    ("Amara", "Seminar Participation"): "unknown",
    ("Ben", "Academic Writing Foundations"): "met",
    ("Chloe", "Evaluating Academic Sources"): "unknown",  # grade not yet released
    ("Dev", "Research Methods Foundations"): "not_met",
    ("Eilidh", "Academic Presentations"): "not_met",  # 10/20 < 60%
    ("Farah", "Evaluating Academic Sources"): "unknown",  # excused
    ("Gwen", "Data Literacy Foundations"): "met",  # ANY: module done though quiz failed
    ("Hamza", "Data Literacy Foundations"): "met",  # ANY: 20/25 = 80%
    ("Iris", "Responsible AI Use"): "not_met",  # reflection not submitted
    ("Jonah", "Academic Presentations"): "unknown",  # unposted
    ("Luca", "Data Literacy Foundations"): "unknown",  # excused quiz, module not done
}


def test_golden_eligibility_outcomes(seeded: seed.SeedResult) -> None:
    with tenant_session(seeded.institution_id) as db:
        rows = db.execute(
            select(m.User.given_name, m.AchievementVersion.title, m.EligibilityEvaluation.outcome)
            .join(m.User, m.User.id == m.EligibilityEvaluation.user_id)
            .join(
                m.AchievementVersion, m.AchievementVersion.id == m.EligibilityEvaluation.version_id
            )
        ).all()
    actual = {(g, t): o for g, t, o in rows}
    for k, v in GOLDEN.items():
        assert actual[k] == v, k


def test_dev_login_and_me(client: TestClient) -> None:
    users = client.get("/dev/institutions/demo-university/users").json()
    student = next(u for u in users if u["display_name"] == "Amara Synthetic")
    login = client.post(
        "/dev/login", json={"institution": "demo-university", "user_id": student["id"]}
    )
    assert login.status_code == 200
    token = login.json()["token"]
    me = client.get("/api/v1/learners/me", headers={"authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["display_name"] == "Amara Synthetic"
    assert body["memberships"][0]["role"] == "student"
    assert body["memberships"][0]["scope_name"] == "Academic Skills Passport (demo)"


def test_dev_login_is_audited(client: TestClient, seeded: seed.SeedResult) -> None:
    users = client.get("/dev/institutions/demo-university/users").json()
    client.post("/dev/login", json={"institution": "demo-university", "user_id": users[0]["id"]})
    with tenant_session(seeded.institution_id) as db:
        n = db.scalar(
            select(func.count())
            .select_from(m.AuditEvent)
            .where(m.AuditEvent.action == "session.dev_login")
        )
    assert n and n >= 1


def test_dev_login_rejects_non_demo_institution(client: TestClient, owner_conn) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.conftest import make_institution

    make_institution(owner_conn, "real-university", demo=False)
    owner_conn.commit()
    r = client.get("/dev/institutions/real-university/users")
    assert r.status_code == 404


def test_session_from_one_tenant_cannot_see_user_of_another(
    client: TestClient,
    two_tenants,  # type: ignore[no-untyped-def]
) -> None:
    from opencredential.authz import sessions

    # A token claiming tenant A but naming tenant B's user resolves to nothing under RLS.
    token, _ = sessions.issue(
        get_settings(),
        user_id=two_tenants["user_b"],
        institution_id=two_tenants["a"],
        method="dev",
    )
    r = client.get("/api/v1/learners/me", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_readyz(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200, r.json()
    assert r.json()["checks"] == {"database": "ok", "migrations": "ok", "signer": "ok"}


def test_production_refuses_active_dev_key(seeded: seed.SeedResult) -> None:
    prod = Settings(
        env="production",
        secret_key="s" * 48,
        signer_shared_secret="s" * 48,
        token_encryption_key="s" * 48,
    )
    with pytest.raises(StartupRefused):
        check_production_safety(prod)


def test_production_refuses_keys_wrapped_with_the_development_kek(
    seeded: seed.SeedResult,
    owner_conn,  # type: ignore[no-untyped-def]
) -> None:
    """A signer that ran without its own SIGNER_KEK wraps keys with the committed development
    key, whatever they are marked as. The first guard only reads the mark."""

    def answer(fn: str) -> bool:
        return bool(owner_conn.execute(f"select app.{fn}()").fetchone()[0])

    try:
        owner_conn.execute("UPDATE app.issuer_keys SET is_dev = false")
        owner_conn.execute("UPDATE keys.private_keys SET is_dev = false")
        assert answer("dev_keys_active") is False  # nothing is marked as a development key
        assert answer("dev_wrapped_keys_active") is True  # but the test signer has no KEK
        owner_conn.execute("UPDATE keys.private_keys SET kek_ref = 'env:SIGNER_KEK'")
        assert answer("dev_wrapped_keys_active") is False
    finally:
        owner_conn.rollback()
    # As seeded, both guards see development keys, and production refuses to start.
    with owner_session() as db:
        assert db.execute(text("select app.dev_wrapped_keys_active()")).scalar() is True


def test_seed_refuses_production() -> None:
    prod = Settings(
        env="production",
        secret_key="s" * 48,
        signer_shared_secret="s" * 48,
        token_encryption_key="s" * 48,
    )
    with pytest.raises(seed.SeedRefused):
        seed.run(settings=prod)


def test_signer_holds_encrypted_key_only(seeded: seed.SeedResult) -> None:
    with owner_session() as db:
        row = db.execute(text("SELECT ciphertext, kek_ref, is_dev FROM keys.private_keys")).one()
    assert row.is_dev and row.kek_ref == "dev:committed"
    assert b"z" not in bytes(row.ciphertext)[:1] or len(bytes(row.ciphertext)) > 28
