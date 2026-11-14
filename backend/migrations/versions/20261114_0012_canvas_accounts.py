# SPDX-License-Identifier: AGPL-3.0-or-later
"""Link chosen Canvas sub-accounts to areas.

* ``canvas_accounts``: the Canvas account tree as last read by an administrator, and which
  area (org unit) each ticked sub-account is linked to.
* ``courses.canvas_account_id``: the sub-account a course sits in, from the launch
  (``$Canvas.account.id``) or the Canvas API, so new courses join the linked area.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canvas_accounts",
        sa.Column("canvas_integration_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_account_id", sa.Text(), nullable=True),
        sa.Column("org_unit_id", sa.Uuid(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
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
            ["institution_id", "org_unit_id"],
            ["app.org_units.institution_id", "app.org_units.id"],
            name="fk_org_unit_id_org_units",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["app.institutions.id"],
            name=op.f("fk_canvas_accounts_institution_id_institutions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas_accounts")),
        sa.UniqueConstraint(
            "canvas_integration_id",
            "account_id",
            name=op.f("uq_canvas_accounts_canvas_integration_id_account_id"),
        ),
        sa.UniqueConstraint("institution_id", "id", name="uq_canvas_accounts_tenant_id"),
        schema="app",
    )
    op.create_index(
        op.f("ix_app_canvas_accounts_institution_id"),
        "canvas_accounts",
        ["institution_id"],
        unique=False,
        schema="app",
    )
    op.add_column("courses", sa.Column("canvas_account_id", sa.Text(), nullable=True), schema="app")
    op.execute("ALTER TABLE app.canvas_accounts ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON app.canvas_accounts
          USING (institution_id = app.current_institution_id())
          WITH CHECK (institution_id = app.current_institution_id())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON app.canvas_accounts")
    op.drop_column("courses", "canvas_account_id", schema="app")
    op.drop_index(
        op.f("ix_app_canvas_accounts_institution_id"),
        table_name="canvas_accounts",
        schema="app",
    )
    op.drop_table("canvas_accounts", schema="app")
