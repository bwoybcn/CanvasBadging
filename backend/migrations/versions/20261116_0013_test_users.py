# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mark Canvas's Student View test user.

``users.is_test_user`` is set when Canvas launches its fake "Test Student" (Student View). Such a
user can still look around as a student, but is left out of award pickers, progress lists and
syncs (round 3 of hands-on testing, finding L5).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_test_user", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("users", "is_test_user", schema="app")
