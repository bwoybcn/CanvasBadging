# SPDX-License-Identifier: AGPL-3.0-or-later
"""Row-level security, immutability triggers, grants, keys schema and job queue.

Hand-written: none of this is expressible in SQLAlchemy metadata.

* Roles: the runtime role (``OC_DB_APP_ROLE``, default ``oc_app``) gets DML only and is
  subject to RLS; the signer role (``OC_DB_SIGNER_ROLE``, default ``oc_signer``) only sees
  schema ``keys``. Missing roles are created ``NOLOGIN`` so the migration is self-contained;
  operators set passwords / LOGIN separately (docker/postgres/init does this in dev).
* RLS: every tenant table gets ``tenant_isolation`` keyed on ``app.institution_id``.
* Immutability (spec §12.3): published achievement versions, issued credentials and audit
  events are protected by triggers, so even a buggy code path cannot change them.
* Jobs: procrastinate's schema is installed into schema ``jobs`` (ADR-0011).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op
from procrastinate import schema as procrastinate_schema

from opencredential.db.base import TENANT_TABLES
from opencredential.settings import get_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables written before a tenant is known (LTI login/launch); no RLS, short-lived rows.
PRE_TENANT_TABLES = ("lti_launch_state", "lti_nonces_used")


def _roles() -> tuple[str, str]:
    s = get_settings()
    for role in (s.db_app_role, s.db_signer_role):
        if not role.replace("_", "").isalnum():
            raise ValueError(f"unsafe role name {role!r}")
    return s.db_app_role, s.db_signer_role


def upgrade() -> None:
    app_role, signer_role = _roles()

    for role in (app_role, signer_role):
        op.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN;
              END IF;
            END $$;
            """
        )

    # ---- tenant helper ------------------------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION app.current_institution_id() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.institution_id', true), '')::uuid $$;
        """
    )

    # ---- row-level security -------------------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON app.{table}
              USING (institution_id = app.current_institution_id())
              WITH CHECK (institution_id = app.current_institution_id())
            """
        )

    # Institutions: readable by everyone (needed to resolve a tenant), writable only for
    # the current tenant. New institutions are created by the owner role (install CLI).
    op.execute("ALTER TABLE app.institutions ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY institutions_read ON app.institutions FOR SELECT USING (true)")
    op.execute(
        """
        CREATE POLICY institutions_update_own ON app.institutions FOR UPDATE
          USING (id = app.current_institution_id())
          WITH CHECK (id = app.current_institution_id())
        """
    )

    # Audit: tenant rows visible to that tenant; system rows (NULL tenant) insert-only.
    op.execute("ALTER TABLE app.audit_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_read ON app.audit_events FOR SELECT
          USING (institution_id = app.current_institution_id())
        """
    )
    op.execute(
        """
        CREATE POLICY audit_insert ON app.audit_events FOR INSERT
          WITH CHECK (institution_id IS NULL OR institution_id = app.current_institution_id())
        """
    )

    # ---- immutability triggers (spec §12.3) ---------------------------------------------
    op.execute(
        """
        CREATE FUNCTION app.forbid_frozen_version_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.frozen THEN
            RAISE EXCEPTION 'achievement version % is published and immutable', OLD.id
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;
        CREATE TRIGGER trg_achievement_versions_frozen
          BEFORE UPDATE OR DELETE ON app.achievement_versions
          FOR EACH ROW EXECUTE FUNCTION app.forbid_frozen_version_change();
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.forbid_issued_credential_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status = 'issued' THEN
            IF TG_OP = 'DELETE' THEN
              RAISE EXCEPTION 'issued credential % cannot be deleted; revoke it instead', OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            -- Only the supersession pointer may change after issue (reissue workflow).
            IF (NEW.signed_json, NEW.content_hash, NEW.credential_uri, NEW.status, NEW.user_id,
                NEW.version_id, NEW.issuer_id, NEW.issuer_key_id, NEW.valid_from,
                NEW.valid_until, NEW.issued_at, NEW.recipient_hash, NEW.recipient_salt,
                NEW.status_list_id, NEW.status_list_index, NEW.award_decision_id,
                NEW.institution_id)
               IS DISTINCT FROM
               (OLD.signed_json, OLD.content_hash, OLD.credential_uri, OLD.status, OLD.user_id,
                OLD.version_id, OLD.issuer_id, OLD.issuer_key_id, OLD.valid_from,
                OLD.valid_until, OLD.issued_at, OLD.recipient_hash, OLD.recipient_salt,
                OLD.status_list_id, OLD.status_list_index, OLD.award_decision_id,
                OLD.institution_id) THEN
              RAISE EXCEPTION 'issued credential % is immutable; use reissue', OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
            END IF;
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$;
        CREATE TRIGGER trg_credentials_issued_immutable
          BEFORE UPDATE OR DELETE ON app.credentials
          FOR EACH ROW EXECUTE FUNCTION app.forbid_issued_credential_change();
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.forbid_audit_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit events are append-only'
            USING ERRCODE = 'insufficient_privilege';
        END $$;
        CREATE TRIGGER trg_audit_events_append_only
          BEFORE UPDATE OR DELETE ON app.audit_events
          FOR EACH ROW EXECUTE FUNCTION app.forbid_audit_change();
        """
    )

    # ---- production guard: are any development keys active? -----------------------------
    op.execute(
        """
        CREATE FUNCTION app.dev_keys_active() RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
        $$ SELECT EXISTS (SELECT 1 FROM app.issuer_keys WHERE is_dev AND state = 'active') $$;
        REVOKE ALL ON FUNCTION app.dev_keys_active() FROM PUBLIC;
        """
    )

    # ---- keys schema (signer only, ADR-0005) --------------------------------------------
    op.execute(
        """
        CREATE SCHEMA keys;
        REVOKE ALL ON SCHEMA keys FROM PUBLIC;
        CREATE TABLE keys.private_keys (
          issuer_key_id uuid PRIMARY KEY,
          ciphertext    bytea NOT NULL,
          dek_wrapped   bytea NOT NULL,
          kek_ref       text  NOT NULL,
          algorithm     text  NOT NULL DEFAULT 'Ed25519',
          is_dev        boolean NOT NULL DEFAULT false,
          created_at    timestamptz NOT NULL DEFAULT now(),
          destroyed_at  timestamptz
        );
        """
    )

    # ---- job queue (procrastinate, ADR-0011) --------------------------------------------
    op.execute("CREATE SCHEMA jobs")
    op.execute("SET LOCAL search_path TO jobs")
    op.execute(procrastinate_schema.SchemaManager.get_schema())
    op.execute("SET LOCAL search_path TO app, jobs, public")
    op.execute(
        """
        CREATE VIEW app.background_jobs WITH (security_invoker = true) AS
        SELECT j.id, j.queue_name, j.task_name, j.status::text AS status, j.attempts,
               j.scheduled_at, j.args->>'subject_type' AS subject_type,
               j.args->>'subject_id' AS subject_id,
               nullif(j.args->>'institution_id', '')::uuid AS institution_id, j.args
          FROM jobs.procrastinate_jobs j
         WHERE nullif(j.args->>'institution_id', '')::uuid = app.current_institution_id()
        """
    )

    # ---- grants -------------------------------------------------------------------------
    op.execute(
        f"""
        GRANT USAGE ON SCHEMA app TO {app_role};
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO {app_role};
        REVOKE INSERT, UPDATE, DELETE ON app.alembic_version FROM {app_role};
        REVOKE UPDATE, DELETE ON app.audit_events FROM {app_role};
        REVOKE INSERT, DELETE ON app.institutions FROM {app_role};
        GRANT SELECT ON app.background_jobs TO {app_role};
        GRANT EXECUTE ON FUNCTION app.dev_keys_active() TO {app_role};
        ALTER DEFAULT PRIVILEGES IN SCHEMA app
          GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role};

        GRANT USAGE ON SCHEMA jobs TO {app_role};
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA jobs TO {app_role};
        GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA jobs TO {app_role};
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA jobs TO {app_role};

        GRANT USAGE ON SCHEMA keys TO {signer_role};
        GRANT SELECT, INSERT, UPDATE ON keys.private_keys TO {signer_role};
        """
    )


def downgrade() -> None:
    app_role, _ = _roles()
    op.execute(
        f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA app
          REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {app_role};
        REVOKE ALL ON ALL TABLES IN SCHEMA app FROM {app_role};
        REVOKE ALL ON SCHEMA app FROM {app_role};
        """
    )
    op.execute("DROP VIEW IF EXISTS app.background_jobs")
    op.execute("DROP SCHEMA IF EXISTS jobs CASCADE")
    op.execute("DROP SCHEMA IF EXISTS keys CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.dev_keys_active()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON app.audit_events")
    op.execute("DROP FUNCTION IF EXISTS app.forbid_audit_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_credentials_issued_immutable ON app.credentials")
    op.execute("DROP FUNCTION IF EXISTS app.forbid_issued_credential_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_achievement_versions_frozen ON app.achievement_versions")
    op.execute("DROP FUNCTION IF EXISTS app.forbid_frozen_version_change()")
    for table in [*TENANT_TABLES, "institutions", "audit_events"]:
        op.execute(f"ALTER TABLE app.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            DROP POLICY IF EXISTS tenant_isolation ON app.{table};
            DROP POLICY IF EXISTS institutions_read ON app.{table};
            DROP POLICY IF EXISTS institutions_update_own ON app.{table};
            DROP POLICY IF EXISTS audit_read ON app.{table};
            DROP POLICY IF EXISTS audit_insert ON app.{table};
            """
        )
    op.execute("DROP FUNCTION IF EXISTS app.current_institution_id()")
