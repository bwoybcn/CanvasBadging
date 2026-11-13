# SPDX-License-Identifier: AGPL-3.0-or-later
"""Programmatic Alembic helpers (owner role)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from opencredential.paths import ALEMBIC_INI
from opencredential.settings import get_settings


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_owner_url)
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(_config(), revision)


def downgrade(revision: str) -> None:
    command.downgrade(_config(), revision)


def reset_database() -> None:
    """Drop everything and migrate again. Development and tests only."""
    if get_settings().is_production:
        raise RuntimeError("reset_database is disabled in production")
    downgrade("base")
    upgrade("head")
