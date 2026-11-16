# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read less from Canvas, and stop reading a course after it ends.

Whole-product review, finding 2 (data minimisation and retention):

* ``lms_assignments.submissions_synced``: submissions are now read and kept only for assignments
  a live badge rule uses. Existing rows are marked as read; the next sync of each course sets
  the flag properly and deletes the submissions nobody's badge depends on, and the daily
  retention job does the same for courses that are no longer read.
* Unreleased marks are no longer stored. The ones already held are cleared here.
* ``courses.ended_at`` and ``courses.archived_at``: when the course ended in Canvas and when it
  stopped being read (``opencredential.sync.lifecycle``). Retention counts from ``ended_at``.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lms_assignments",
        sa.Column("submissions_synced", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="app",
    )
    op.add_column(
        "courses", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True), schema="app"
    )
    op.add_column(
        "courses",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    # A mark the student cannot see yet is not kept. Runs as the owner, across institutions.
    op.execute(
        "UPDATE app.lms_submissions SET score = NULL WHERE posted_at IS NULL AND score IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("courses", "archived_at", schema="app")
    op.drop_column("courses", "ended_at", schema="app")
    op.drop_column("lms_assignments", "submissions_synced", schema="app")
