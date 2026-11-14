# SPDX-License-Identifier: AGPL-3.0-or-later
"""Colleague review set per area and per badge (extracurricular badges, PR 1 of 4).

* ``org_units.review_policy`` holds a faculty's, department's or service's overrides of the
  institution's review settings (definition review mode, self-approval, second approval of
  manual awards). Empty means "inherit".
* ``definition_reviews.without_review`` marks approvals that happened automatically, so admins
  can list live badges nobody else checked. Existing automatic approvals are backfilled.
* ``memberships.role`` gains ``reviewer``: a named colleague who may review badges in an area.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ROLES = ("student", "lecturer", "course_admin", "issuer_manager", "dept_admin", "inst_admin")
NEW_ROLES = (
    "student",
    "lecturer",
    "course_admin",
    "issuer_manager",
    "reviewer",
    "dept_admin",
    "inst_admin",
)


def _role_check(roles: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{r}'" for r in roles)
    op.execute(
        f"""
        ALTER TABLE app.memberships DROP CONSTRAINT IF EXISTS ck_memberships_role;
        ALTER TABLE app.memberships ADD CONSTRAINT ck_memberships_role
          CHECK (role IN ({listed}));
        """
    )


def upgrade() -> None:
    op.add_column(
        "org_units",
        sa.Column(
            "review_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="app",
    )
    op.add_column(
        "definition_reviews",
        sa.Column("without_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )
    # Automatic approvals so far all carry {"policy": "definitions_require_approval=false"}.
    op.execute("UPDATE app.definition_reviews SET without_review = true WHERE checklist ? 'policy'")
    _role_check(NEW_ROLES)


def downgrade() -> None:
    op.execute("DELETE FROM app.memberships WHERE role = 'reviewer'")
    _role_check(OLD_ROLES)
    op.drop_column("definition_reviews", "without_review", schema="app")
    op.drop_column("org_units", "review_policy", schema="app")
