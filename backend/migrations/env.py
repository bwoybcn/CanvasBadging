# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic environment. Migrations always run as the owner role (OC_DATABASE_OWNER_URL)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text

import opencredential.db.models  # noqa: F401  (registers all tables)
from opencredential.db.autogen import include_name, include_object
from opencredential.db.base import Base
from opencredential.settings import get_settings

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_owner_url
    # Plain search_path here: with app first, reflection would report app tables as
    # "default schema" and autogenerate would see phantom differences.
    engine = create_engine(url)
    with engine.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            include_name=include_name,
            version_table_schema="app",
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline SQL generation is not supported; run against a database.")
run_migrations_online()
