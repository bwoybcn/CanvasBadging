# SPDX-License-Identifier: AGPL-3.0-or-later
"""Org units can be a "service" (a library, careers service, students' union), not only a
faculty, department or programme. Found while setting up a Library recognition course.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _kinds(kinds: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{k}'" for k in kinds)
    op.execute(
        f"""
        ALTER TABLE app.org_units DROP CONSTRAINT IF EXISTS ck_org_units_kind;
        ALTER TABLE app.org_units ADD CONSTRAINT ck_org_units_kind CHECK (kind IN ({listed}));
        """
    )


def upgrade() -> None:
    _kinds(("faculty", "department", "programme", "service", "other"))


def downgrade() -> None:
    op.execute("UPDATE app.org_units SET kind = 'other' WHERE kind = 'service'")
    _kinds(("faculty", "department", "programme", "other"))
