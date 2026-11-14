# SPDX-License-Identifier: AGPL-3.0-or-later
"""Review follow-ups (code review of 13 Nov 2026, findings C8 and S3).

* ``issuer_keys.destroyed_at`` records when the signer erased a key's private material, so the
  nightly job stops destroying the same retired keys again and the admin key list can show it.
* ``institutions.verification_host`` becomes unique: one institution cannot claim another's
  verification host. Upgrading fails if two institutions already share a host; give one of them
  a different host (or none) first.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "issuer_keys",
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_unique_constraint(
        op.f("uq_institutions_verification_host"),
        "institutions",
        ["verification_host"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_institutions_verification_host"), "institutions", schema="app", type_="unique"
    )
    op.drop_column("issuer_keys", "destroyed_at", schema="app")
