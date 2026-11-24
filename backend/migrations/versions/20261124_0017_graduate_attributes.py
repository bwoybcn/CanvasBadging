# SPDX-License-Identifier: AGPL-3.0-or-later
"""Graduate attributes: an institution-managed list that badges are tagged with.

* ``institutions.graduate_attributes``: the list an institution administrator keeps, each
  ``{key, name, description, framework, url}``. Empty until an administrator adds attributes
  or installs a template pack.
* ``achievement_versions.graduate_attributes``: the attributes an author tagged the badge
  with, copied from the list at the time, so a published version (and every badge issued from
  it, where they appear as Open Badges alignments) stays the same if the list is edited later.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("institutions", "achievement_versions"):
        op.add_column(
            table,
            sa.Column(
                "graduate_attributes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            schema="app",
        )


def downgrade() -> None:
    for table in ("achievement_versions", "institutions"):
        op.drop_column(table, "graduate_attributes", schema="app")
