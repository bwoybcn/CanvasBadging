# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engines and tenant-scoped sessions.

Request handlers use the *app* role, which is subject to PostgreSQL row-level security. The
tenant is set per transaction with ``set_config('app.institution_id', …, true)``; without it,
tenant tables return no rows and reject writes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from opencredential.settings import get_settings

SEARCH_PATH = "app,jobs,public"


def make_engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={SEARCH_PATH}"},
    )


@lru_cache
def app_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def owner_engine() -> Engine:
    return make_engine(get_settings().database_owner_url)


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


def set_tenant(session: Session, institution_id: uuid.UUID | None) -> None:
    """Bind the current transaction to one institution (``SET LOCAL`` semantics)."""
    session.execute(
        text("select set_config('app.institution_id', :iid, true)"),
        {"iid": str(institution_id) if institution_id else ""},
    )


@contextmanager
def tenant_session(
    institution_id: uuid.UUID | None, *, engine: Engine | None = None
) -> Iterator[Session]:
    """A session whose single transaction is scoped to ``institution_id``.

    Commits on success, rolls back on error. Pass ``None`` only for tenant-independent work
    (for example resolving an institution by slug); tenant tables will then be invisible.
    """
    session = _factory(engine or app_engine())()
    try:
        with session.begin():
            set_tenant(session, institution_id)
            yield session
    finally:
        session.close()


@contextmanager
def owner_session() -> Iterator[Session]:
    """Owner-role session (bypasses RLS). Only for migrations, seeding and maintenance CLIs."""
    session = _factory(owner_engine())()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
