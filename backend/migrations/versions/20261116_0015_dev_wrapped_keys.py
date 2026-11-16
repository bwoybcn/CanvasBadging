# SPDX-License-Identifier: AGPL-3.0-or-later
"""Production guard: is an active signing key wrapped with the development KEK?

``app.dev_keys_active()`` (migration 0002) only looks at ``issuer_keys.is_dev``, which the api
sets when it asks for a development key. A signer that ran without its own ``SIGNER_KEK`` wraps
every key with the committed development key-wrapping key and records ``kek_ref =
'dev:committed'``, whatever the key was marked as. ``app.dev_wrapped_keys_active()`` lets the
api and worker see that without reading the ``keys`` schema themselves (whole-product review,
finding 4).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-16
"""

from collections.abc import Sequence

from alembic import op

from opencredential.settings import get_settings

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    app_role = get_settings().db_app_role
    op.execute(
        f"""
        CREATE FUNCTION app.dev_wrapped_keys_active() RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
        $$ SELECT EXISTS (
             SELECT 1 FROM app.issuer_keys k
               JOIN keys.private_keys p ON p.issuer_key_id = k.id
              WHERE k.state = 'active' AND p.destroyed_at IS NULL
                AND (p.is_dev OR p.kek_ref LIKE 'dev:%')) $$;
        REVOKE ALL ON FUNCTION app.dev_wrapped_keys_active() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.dev_wrapped_keys_active() TO {app_role};
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.dev_wrapped_keys_active()")
