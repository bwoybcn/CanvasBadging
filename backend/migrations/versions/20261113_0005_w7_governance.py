# SPDX-License-Identifier: AGPL-3.0-or-later
"""W7: institutional governance (spec §10, §12.5)

* ``issuers.level`` and ``issuers.authority_basis``: university, faculty or department issuers
  with the explicit delegation of authority recorded when an administrator authorised them.
* ``org_units.may_issue`` / ``status``: which departments may issue credentials.
* ``badge_templates.description`` / ``created_by`` / ``status``: institutional templates.
* ``app.purge_audit_events``: the only way audit events are ever deleted, for the configured
  retention period. The append-only trigger now allows a DELETE only inside that function and
  only for events older than one year, so a misconfiguration cannot empty the log.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13 13:43:04.567757
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opencredential.settings import get_settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=False,
        length=max(len(v) for v in values) + 8,
        schema="app",
    )


def upgrade() -> None:
    app_role = get_settings().db_app_role
    op.add_column(
        "badge_templates", sa.Column("description", sa.Text(), nullable=True), schema="app"
    )
    op.add_column(
        "badge_templates", sa.Column("created_by", sa.Uuid(), nullable=True), schema="app"
    )
    op.add_column(
        "badge_templates",
        sa.Column(
            "status",
            _enum("active", "archived", name="status"),
            nullable=False,
            server_default="active",
        ),
        schema="app",
    )
    op.add_column(
        "issuers",
        sa.Column(
            "level",
            _enum("university", "faculty", "department", "programme", name="level"),
            nullable=False,
            server_default="university",
        ),
        schema="app",
    )
    op.add_column("issuers", sa.Column("authority_basis", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "org_units",
        sa.Column("may_issue", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="app",
    )
    op.add_column(
        "org_units",
        sa.Column(
            "status",
            _enum("active", "archived", name="status"),
            nullable=False,
            server_default="active",
        ),
        schema="app",
    )
    op.execute(
        """
        ALTER TABLE app.badge_templates ADD CONSTRAINT ck_badge_templates_status
          CHECK (status IN ('active', 'archived'));
        ALTER TABLE app.org_units ADD CONSTRAINT ck_org_units_status
          CHECK (status IN ('active', 'archived'));
        ALTER TABLE app.issuers ADD CONSTRAINT ck_issuers_level
          CHECK (level IN ('university', 'faculty', 'department', 'programme'));
        """
    )

    # ---- audit retention -----------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.forbid_audit_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND current_setting('opencredential.audit_purge', true) = 'on'
             AND OLD.at < now() - interval '1 year' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'audit events are append-only'
            USING ERRCODE = 'insufficient_privilege';
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app.purge_audit_events(p_institution uuid, p_years integer)
        RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS $$
        DECLARE removed integer;
        BEGIN
          IF p_years IS NULL OR p_years < 1 THEN
            RAISE EXCEPTION 'audit retention must be at least one year';
          END IF;
          PERFORM set_config('opencredential.audit_purge', 'on', true);
          DELETE FROM app.audit_events
           WHERE institution_id = p_institution
             AND at < now() - make_interval(years => p_years);
          GET DIAGNOSTICS removed = ROW_COUNT;
          PERFORM set_config('opencredential.audit_purge', 'off', true);
          RETURN removed;
        END $$;
        REVOKE ALL ON FUNCTION app.purge_audit_events(uuid, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.purge_audit_events(uuid, integer) TO {app_role};
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.purge_audit_events(uuid, integer)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.forbid_audit_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit events are append-only'
            USING ERRCODE = 'insufficient_privilege';
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE app.issuers DROP CONSTRAINT IF EXISTS ck_issuers_level;
        ALTER TABLE app.org_units DROP CONSTRAINT IF EXISTS ck_org_units_status;
        ALTER TABLE app.badge_templates DROP CONSTRAINT IF EXISTS ck_badge_templates_status;
        """
    )
    op.drop_column("org_units", "status", schema="app")
    op.drop_column("org_units", "may_issue", schema="app")
    op.drop_column("issuers", "authority_basis", schema="app")
    op.drop_column("issuers", "level", schema="app")
    op.drop_column("badge_templates", "status", schema="app")
    op.drop_column("badge_templates", "created_by", schema="app")
    op.drop_column("badge_templates", "description", schema="app")
