# SPDX-License-Identifier: AGPL-3.0-or-later
"""W6 sharing: one live share per credential, public lookups for share pages and badge images.

* ``uq_share_grants_active``: at most one active public link per credential.
* ``app.institution_for_share(text)`` maps an *active* share id to its institution, so the
  public ``/verify/{share_id}`` page can open a tenant-scoped session. Withdrawn shares map to
  nothing, exactly like ids that never existed.
* ``app.institution_for_public_asset(text)`` maps a badge image hash to an institution only when
  the image belongs to a published (frozen) achievement version, so draft uploads stay private.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opencredential.settings import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOOKUPS = {
    "institution_for_share(p_share text)": (
        "SELECT institution_id FROM app.share_grants WHERE share_id = p_share AND revoked_at IS NULL"
    ),
    "institution_for_public_asset(p_sha text)": (
        "SELECT a.institution_id FROM app.badge_assets a"
        " JOIN app.achievement_versions v ON v.asset_id = a.id AND v.frozen"
        " WHERE a.sha256 = p_sha ORDER BY a.created_at LIMIT 1"
    ),
}


def upgrade() -> None:
    app_role = get_settings().db_app_role
    op.create_index(
        "uq_share_grants_active",
        "share_grants",
        ["credential_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    for signature, body in LOOKUPS.items():
        name = signature.split("(")[0]
        op.execute(
            f"""
            CREATE FUNCTION app.{signature} RETURNS uuid
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
            $$ {body} $$;
            REVOKE ALL ON FUNCTION app.{name} FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION app.{name} TO {app_role};
            """
        )


def downgrade() -> None:
    for signature in LOOKUPS:
        op.execute(f"DROP FUNCTION IF EXISTS app.{signature}")
    op.drop_index("uq_share_grants_active", table_name="share_grants", schema="app")
