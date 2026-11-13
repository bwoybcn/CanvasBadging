# SPDX-License-Identifier: AGPL-3.0-or-later
"""W4 issuance: signing attempts, status-list freshness, key retirement, public lookups.

* ``credentials.attempts`` / ``last_error`` support retry and reconciliation (spec §17.2).
* ``status_lists.published_valid_until`` lets the public endpoint refuse a stale list (503,
  which verifiers report as "unable to verify", never as "revoked").
* ``keys.private_keys.retired_at``: the signer refuses to sign with retired keys (ADR-0005).
* Public endpoints (DID documents, status lists, achievement pages, verification) run without a
  session, so RLS hides every tenant row. Three narrow SECURITY DEFINER functions map a public
  identifier to its institution; the request then opens an ordinary tenant-scoped session.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opencredential.settings import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOOKUPS = {
    "institution_for_status_list(p_id uuid)": (
        "SELECT institution_id FROM app.status_lists WHERE id = p_id"
    ),
    "institution_for_issuer_did(p_did text)": (
        "SELECT institution_id FROM app.issuers WHERE did = p_did"
    ),
    "institution_for_version(p_id uuid)": (
        "SELECT institution_id FROM app.achievement_versions WHERE id = p_id AND frozen"
    ),
}


def upgrade() -> None:
    app_role = get_settings().db_app_role
    op.add_column(
        "credentials",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        schema="app",
    )
    op.add_column("credentials", sa.Column("last_error", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "status_lists",
        sa.Column("published_valid_until", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.execute("ALTER TABLE keys.private_keys ADD COLUMN retired_at timestamptz")
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
    op.execute("ALTER TABLE keys.private_keys DROP COLUMN IF EXISTS retired_at")
    op.drop_column("status_lists", "published_valid_until", schema="app")
    op.drop_column("credentials", "last_error", schema="app")
    op.drop_column("credentials", "attempts", schema="app")
