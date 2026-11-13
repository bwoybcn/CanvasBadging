# SPDX-License-Identifier: AGPL-3.0-or-later
"""Row-level security and composite FKs keep tenants apart (ADR-0016, spec §3.4)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db


def _as_tenant(conn, iid: uuid.UUID | None) -> None:  # type: ignore[no-untyped-def]
    conn.execute("SELECT set_config('app.institution_id', %s, true)", [str(iid) if iid else ""])


def test_tenant_sees_only_its_own_rows(app_conn, two_tenants) -> None:  # type: ignore[no-untyped-def]
    _as_tenant(app_conn, two_tenants["a"])
    ids = {r[0] for r in app_conn.execute("SELECT id FROM users").fetchall()}
    assert two_tenants["user_a"] in ids
    assert two_tenants["user_b"] not in ids


def test_no_tenant_means_no_rows(app_conn, two_tenants) -> None:  # type: ignore[no-untyped-def]
    _as_tenant(app_conn, None)
    assert app_conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_cannot_write_into_another_tenant(app_conn, two_tenants) -> None:  # type: ignore[no-untyped-def]
    _as_tenant(app_conn, two_tenants["a"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(
            "INSERT INTO users (id, institution_id, status) VALUES (%s, %s, 'active')",
            [uuid.uuid4(), two_tenants["b"]],
        )


def test_cannot_update_another_tenants_rows(app_conn, two_tenants) -> None:  # type: ignore[no-untyped-def]
    _as_tenant(app_conn, two_tenants["a"])
    cur = app_conn.execute(
        "UPDATE users SET display_name = 'x' WHERE id = %s", [two_tenants["user_b"]]
    )
    assert cur.rowcount == 0


def test_composite_fk_blocks_cross_tenant_reference(owner_conn, two_tenants) -> None:  # type: ignore[no-untyped-def]
    """Even the owner role (which bypasses RLS) cannot link a row to another tenant's row."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        owner_conn.execute(
            "INSERT INTO app.memberships (id, institution_id, user_id, scope_type, scope_id,"
            " role, source) VALUES (%s, %s, %s, 'institution', %s, 'inst_admin', 'grant')",
            [uuid.uuid4(), two_tenants["a"], two_tenants["user_b"], two_tenants["a"]],
        )


def test_institutions_readable_but_only_own_updatable(app_conn, two_tenants) -> None:  # type: ignore[no-untyped-def]
    _as_tenant(app_conn, two_tenants["a"])
    assert (
        app_conn.execute(
            "SELECT count(*) FROM institutions WHERE id IN (%s, %s)",
            [two_tenants["a"], two_tenants["b"]],
        ).fetchone()[0]
        == 2
    )
    cur = app_conn.execute(
        "UPDATE institutions SET name = 'hijacked' WHERE id = %s", [two_tenants["b"]]
    )
    assert cur.rowcount == 0


def test_app_role_cannot_read_private_keys(app_conn) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT * FROM keys.private_keys")
