# SPDX-License-Identifier: AGPL-3.0-or-later
"""Declarative base, column helpers and tenant-safety conventions.

Conventions (docs/architecture/data-model.md):

* Every table lives in schema ``app`` and has a UUIDv7 ``id`` plus ``created_at``/``updated_at``.
* Every tenant table has ``institution_id`` and ``UNIQUE (institution_id, id)`` so that other
  tenant tables can reference it with a *composite* foreign key ``(institution_id, x_id)``.
  A row therefore can never point at a row that belongs to another institution.
* Enumerations are ``varchar`` + ``CHECK`` (no native Postgres enums).
* Row-level security policies are created by the migrations for every table listed in
  :data:`TENANT_TABLES`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    MetaData,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from opencredential.ids import uuid7

APP_SCHEMA = "app"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=APP_SCHEMA, naming_convention=NAMING_CONVENTION)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


#: Names of tables that carry ``institution_id`` and get an RLS policy. Filled by TenantMixin.
TENANT_TABLES: list[str] = []


class TenantMixin:
    """Adds ``institution_id`` (FK to institutions) and registers the table for RLS."""

    @declared_attr
    def institution_id(cls) -> Mapped[uuid.UUID]:
        from sqlalchemy import ForeignKey

        return mapped_column(
            Uuid, ForeignKey(f"{APP_SCHEMA}.institutions.id"), nullable=False, index=True
        )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name = cls.__dict__.get("__tablename__")
        if name and name not in TENANT_TABLES:
            TENANT_TABLES.append(name)


def choice(*values: str, name: str) -> Enum:
    """A text column restricted by CHECK to ``values`` (portable, migration-friendly enum)."""
    return Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(v) for v in values) + 8,
        validate_strings=True,
    )


def tenant_fk(
    column: str, target: str, *, ondelete: str | None = None, use_alter: bool = False
) -> ForeignKeyConstraint:
    """Composite FK ``(institution_id, column) -> target(institution_id, id)``."""
    return ForeignKeyConstraint(
        ["institution_id", column],
        [f"{APP_SCHEMA}.{target}.institution_id", f"{APP_SCHEMA}.{target}.id"],
        ondelete=ondelete,
        use_alter=use_alter,
        name=f"fk_{column}_{target}"[:63],
    )


def tenant_args(table: str, *extra: Any) -> tuple[Any, ...]:
    """Standard ``__table_args__`` for a tenant table: (institution_id, id) unique + extras."""
    return (
        UniqueConstraint("institution_id", "id", name=f"uq_{table}_tenant_id"[:63]),
        *extra,
    )


__all__ = [
    "APP_SCHEMA",
    "TENANT_TABLES",
    "Base",
    "CheckConstraint",
    "TenantMixin",
    "choice",
    "tenant_args",
    "tenant_fk",
]
