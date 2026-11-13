# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec §12.3: published versions, issued credentials and audit events cannot be changed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from tests.integration.conftest import make_institution, make_user

pytestmark = pytest.mark.db


@pytest.fixture
def graph(owner_conn):  # type: ignore[no-untyped-def]
    c = owner_conn
    iid = make_institution(c, f"imm-{uuid.uuid4().hex[:8]}")
    uid = make_user(c, iid, "Owner")
    issuer, key, definition, version = (uuid.uuid4() for _ in range(4))
    c.execute(
        "INSERT INTO app.issuers (id, institution_id, slug, name, did, status)"
        " VALUES (%s, %s, 'i', 'Issuer', %s, 'active')",
        [issuer, iid, f"did:key:z{uuid.uuid4().hex}"],
    )
    c.execute(
        "INSERT INTO app.issuer_keys (id, institution_id, issuer_id, verification_method_id,"
        " public_key_multibase, algorithm, state, is_dev) VALUES (%s,%s,%s,%s,'z','Ed25519',"
        " 'retired', false)",
        [key, iid, issuer, f"did:key:z#{key}"],
    )
    c.execute(
        "INSERT INTO app.achievement_definitions (id, institution_id, issuer_id, owner_user_id,"
        " state, award_policy) VALUES (%s,%s,%s,%s,'published','automatic')",
        [definition, iid, issuer, uid],
    )
    c.execute(
        "INSERT INTO app.achievement_versions (id, institution_id, definition_id, version_no,"
        " title, short_description, description, learning_outcomes, criteria_narrative,"
        " category, achievement_type, demonstration_kind, skills, credit_claim_approved, frozen)"
        " VALUES (%s,%s,%s,1,'T','S','D','[]','C','Cat','Badge','completing','[]',false,true)",
        [version, iid, definition],
    )
    decision, cred = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    c.execute(
        "INSERT INTO app.award_decisions (id, institution_id, version_id, user_id, issuer_id,"
        " kind, justification, decided_at, status, issuance_seq, idempotency_key)"
        " VALUES (%s,%s,%s,%s,%s,'manual','test',%s,'issued',1,%s)",
        [decision, iid, version, uid, issuer, now, uuid.uuid4().hex],
    )
    c.execute(
        "INSERT INTO app.credentials (id, institution_id, award_decision_id, issuer_id,"
        " issuer_key_id, version_id, user_id, credential_uri, status, signed_json, valid_from,"
        " issued_at, recipient_salt, recipient_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'issued',"
        " '{\"proof\": {}}', %s, %s, 's', 'h')",
        [cred, iid, decision, issuer, key, version, uid, f"urn:uuid:{cred}", now, now],
    )
    c.commit()
    return {"institution": iid, "version": version, "credential": cred, "user": uid}


def test_frozen_version_cannot_change(owner_conn, graph) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="immutable"):
        owner_conn.execute(
            "UPDATE app.achievement_versions SET title = 'Edited' WHERE id = %s", [graph["version"]]
        )


def test_frozen_version_cannot_be_deleted(owner_conn, graph) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        owner_conn.execute("DELETE FROM app.achievement_versions WHERE id = %s", [graph["version"]])


def test_issued_credential_content_is_immutable(owner_conn, graph) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="reissue"):
        owner_conn.execute(
            "UPDATE app.credentials SET signed_json = '{}' WHERE id = %s", [graph["credential"]]
        )


def test_issued_credential_may_record_supersession(owner_conn, graph) -> None:  # type: ignore[no-untyped-def]
    owner_conn.execute(
        "UPDATE app.credentials SET superseded_by_id = %s WHERE id = %s",
        [uuid.uuid4(), graph["credential"]],
    )


def test_issued_credential_cannot_be_deleted(owner_conn, graph) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="revoke"):
        owner_conn.execute("DELETE FROM app.credentials WHERE id = %s", [graph["credential"]])


def test_audit_events_append_only(owner_conn, app_conn, graph) -> None:  # type: ignore[no-untyped-def]
    eid = uuid.uuid4()
    app_conn.execute(
        "SELECT set_config('app.institution_id', %s, true)", [str(graph["institution"])]
    )
    app_conn.execute(
        "INSERT INTO audit_events (id, institution_id, actor_kind, action, resource_type, at,"
        " data) VALUES (%s, %s, 'system', 'test.event', 'test', now(), '{}')",
        [eid, graph["institution"]],
    )
    app_conn.commit()
    # Runtime role has no UPDATE/DELETE privilege at all...
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("UPDATE audit_events SET action = 'x' WHERE id = %s", [eid])
    app_conn.rollback()
    # ...and even the owner is stopped by the trigger.
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
        owner_conn.execute("DELETE FROM app.audit_events WHERE id = %s", [eid])
