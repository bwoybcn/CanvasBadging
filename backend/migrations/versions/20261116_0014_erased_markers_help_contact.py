# SPDX-License-Identifier: AGPL-3.0-or-later
"""Erasure that sticks, and a help contact (whole-product review, findings 9 and 10).

* ``erased_identities``: when a person's data is erased, a keyed one-way fingerprint of each of
  their Canvas identifiers is kept, so the next launch or class-list refresh does not create
  them again while they are still enrolled in Canvas. No identifier is stored.
* ``institutions.help_contact_name`` / ``help_email`` / ``help_url``: who people ask for help,
  shown on the Help page every screen links to.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erased_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_integration_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value_digest", sa.Text(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "canvas_integration_id"],
            ["app.canvas_integrations.institution_id", "app.canvas_integrations.id"],
            name="fk_canvas_integration_id_canvas_integrations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "user_id"],
            ["app.users.institution_id", "app.users.id"],
            name="fk_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["app.institutions.id"],
            name=op.f("fk_erased_identities_institution_id_institutions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erased_identities")),
        sa.UniqueConstraint(
            "canvas_integration_id",
            "kind",
            "value_digest",
            name=op.f("uq_erased_identities_canvas_integration_id_kind_value_digest"),
        ),
        sa.UniqueConstraint("institution_id", "id", name="uq_erased_identities_tenant_id"),
        schema="app",
    )
    op.create_index(
        op.f("ix_app_erased_identities_institution_id"),
        "erased_identities",
        ["institution_id"],
        unique=False,
        schema="app",
    )
    op.execute("ALTER TABLE app.erased_identities ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON app.erased_identities
          USING (institution_id = app.current_institution_id())
          WITH CHECK (institution_id = app.current_institution_id())
        """
    )
    for column in ("help_contact_name", "help_email", "help_url"):
        op.add_column("institutions", sa.Column(column, sa.Text(), nullable=True), schema="app")


def downgrade() -> None:
    for column in ("help_url", "help_email", "help_contact_name"):
        op.drop_column("institutions", column, schema="app")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON app.erased_identities")
    op.drop_index(
        op.f("ix_app_erased_identities_institution_id"),
        table_name="erased_identities",
        schema="app",
    )
    op.drop_table("erased_identities", schema="app")
