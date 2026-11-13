# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migrations apply cleanly, match the models, and round-trip (Phase 1 exit condition)."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import opencredential.db.models  # noqa: F401
from opencredential.db import migrate
from opencredential.db.autogen import include_name, include_object
from opencredential.db.base import TENANT_TABLES, Base
from opencredential.settings import get_settings

pytestmark = pytest.mark.db


def _diff() -> list:  # type: ignore[type-arg]
    engine = create_engine(get_settings().database_owner_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "include_object": include_object,
                "include_name": include_name,
                "compare_type": True,
                "version_table_schema": "app",
            },
        )
        return compare_metadata(ctx, Base.metadata)


def test_schema_matches_models(database: None) -> None:
    assert _diff() == []


def test_every_tenant_table_has_rls(database: None, owner_conn) -> None:  # type: ignore[no-untyped-def]
    rows = owner_conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'app' AND c.relkind = 'r' AND c.relrowsecurity"
    ).fetchall()
    protected = {r[0] for r in rows}
    assert set(TENANT_TABLES) <= protected
    assert {"institutions", "audit_events"} <= protected
    assert len(TENANT_TABLES) >= 30


def test_downgrade_to_base_and_upgrade_again(database: None, owner_conn) -> None:  # type: ignore[no-untyped-def]
    owner_conn.close()
    migrate.downgrade("base")
    migrate.upgrade("head")
    assert _diff() == []
