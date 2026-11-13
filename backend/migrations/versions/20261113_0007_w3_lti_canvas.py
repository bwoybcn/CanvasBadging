# SPDX-License-Identifier: AGPL-3.0-or-later
"""W3: LTI 1.3 launch state, NRPS URL and pre-tenant registration lookup (ADR-0008, ADR-0009)

* ``lti_launch_state`` gains the browser-binding columns used when third-party cookies are
  blocked (platform storage via ``lti_storage_target``) and a one-time launch ticket.
* ``courses.lti_nrps_url`` remembers the Names and Roles service URL from the latest launch.
* ``app.lti_registration(iss, client_id)``: the LTI login and launch arrive before we know the
  tenant, and ``canvas_integrations`` is protected by row-level security. This SECURITY DEFINER
  function reveals only the tenant and integration ids for one exact (issuer, client id) pair,
  which is all the runtime role needs to open a tenant-scoped session.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from opencredential.settings import get_settings

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATE_COLUMNS = (
    ("client_id", sa.Text()),
    ("browser_secret_hash", sa.Text()),
    ("storage_target", sa.Text()),
    ("launch_ticket_hash", sa.Text()),
    ("launch_claims", postgresql.JSONB(astext_type=sa.Text())),
    ("completed_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, type_ in _STATE_COLUMNS:
        op.add_column("lti_launch_state", sa.Column(name, type_, nullable=True), schema="app")
    op.create_unique_constraint(
        op.f("uq_lti_launch_state_launch_ticket_hash"),
        "lti_launch_state",
        ["launch_ticket_hash"],
        schema="app",
    )
    op.add_column("courses", sa.Column("lti_nrps_url", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "courses", sa.Column("lti_resource_link_id", sa.Text(), nullable=True), schema="app"
    )

    app_role = get_settings().db_app_role
    if not app_role.replace("_", "").isalnum():
        raise ValueError(f"unsafe role name {app_role!r}")
    op.execute(
        """
        CREATE FUNCTION app.lti_registration(p_iss text, p_client_id text)
        RETURNS TABLE (institution_id uuid, integration_id uuid, status text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
        $$ SELECT ci.institution_id, ci.id, ci.status
             FROM app.canvas_integrations ci
             JOIN app.institutions i ON i.id = ci.institution_id
            WHERE ci.lti_issuer = p_iss AND ci.lti_client_id = p_client_id
              AND i.status = 'active' $$;
        REVOKE ALL ON FUNCTION app.lti_registration(text, text) FROM PUBLIC;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION app.lti_registration(text, text) TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.lti_registration(text, text)")
    op.drop_column("courses", "lti_resource_link_id", schema="app")
    op.drop_column("courses", "lti_nrps_url", schema="app")
    op.drop_constraint(
        op.f("uq_lti_launch_state_launch_ticket_hash"), "lti_launch_state", schema="app"
    )
    for name, _ in reversed(_STATE_COLUMNS):
        op.drop_column("lti_launch_state", name, schema="app")
