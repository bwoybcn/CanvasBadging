# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures.

Integration tests (marker ``db``) need a PostgreSQL 16+ server reachable with a superuser
URL in ``OC_TEST_ADMIN_URL`` (default ``postgresql://postgres:postgres@localhost:5432/postgres``).
They create the three roles if missing and a fresh database ``opencredential_test``.

The seed tests also need the signer (``OC_SIGNER_URL``) pointed at that database. They skip when
it is unreachable, unless ``OC_TEST_REQUIRE_SIGNER=1`` (CI), in which case they fail.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

TEST_DB = "opencredential_test"
ADMIN_URL = os.environ.get(
    "OC_TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
ROLES = {"oc_owner": "oc_owner_dev", "oc_app": "oc_app_dev", "oc_signer": "oc_signer_dev"}


def _server_url(user: str, password: str, db: str) -> str:
    info = psycopg.conninfo.conninfo_to_dict(ADMIN_URL)
    host, port = info.get("host", "localhost"), info.get("port", "5432")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _clear_caches() -> None:
    from opencredential.db import session
    from opencredential.settings import get_settings

    get_settings.cache_clear()
    for fn in (session.app_engine, session.owner_engine):
        if fn.cache_info().currsize:
            fn().dispose()
        fn.cache_clear()


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Create a fresh, migrated test database and point the settings at it."""
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable at OC_TEST_ADMIN_URL: {exc}")
    with admin:
        for role, password in ROLES.items():
            exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
            if not exists:
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOBYPASSRLS").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            else:
                admin.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
        admin.execute("ALTER ROLE oc_owner CREATEROLE")
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", [TEST_DB]
        )
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB)))
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER oc_owner").format(sql.Identifier(TEST_DB)))

    os.environ["OC_ENV"] = "test"
    os.environ["OC_DATABASE_URL"] = _server_url("oc_app", ROLES["oc_app"], TEST_DB)
    os.environ["OC_DATABASE_OWNER_URL"] = _server_url("oc_owner", ROLES["oc_owner"], TEST_DB)
    _clear_caches()

    from opencredential.db.migrate import upgrade

    upgrade("head")
    yield
    _clear_caches()


@pytest.fixture
def owner_conn(database: None) -> Iterator[psycopg.Connection]:
    url = os.environ["OC_DATABASE_OWNER_URL"].replace("+psycopg", "")
    with psycopg.connect(url) as conn:
        yield conn


@pytest.fixture
def app_conn(database: None) -> Iterator[psycopg.Connection]:
    url = os.environ["OC_DATABASE_URL"].replace("+psycopg", "")
    with psycopg.connect(url, options="-c search_path=app,jobs,public") as conn:
        yield conn
