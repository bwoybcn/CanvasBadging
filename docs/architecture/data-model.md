# Data model (PostgreSQL 16+)

Design for spec §12. Alembic owns the real DDL (W2); this is the contract it must meet. Conventions:

- PK `id uuid` (UUIDv7, generated in app for index locality) on every table. `created_at`, `updated_at timestamptz` everywhere (omitted below).
- Every tenant table has `institution_id uuid not null` (FK) and an RLS policy `institution_id = current_setting('app.institution_id')::uuid`. Composite FKs `(institution_id, x_id)` on tenant-to-tenant references so a row can never point across tenants.
- Enums are Postgres `text` + `CHECK` (easier migrations than native enums).
- Three schemas: `app` (everything below unless noted), `keys` (signer-only role), `jobs` (procrastinate).
- Immutability enforced by triggers, not just code: `achievement_versions` after publish, `credentials.signed_json` after `issued`, `audit_events` always.

## Entities

### Tenancy and integration

```text
institutions            id, slug unique, name, description, website_url, logo_asset_id?, branding jsonb,
                        verification_host (nullable until set; placeholder in dev), linkedin_org_id?, linkedin_org_name?,
                        policy jsonb  -- see "Institution policy" below
                        retention jsonb, categories text[] (local additions), status (active|suspended)

canvas_integrations     id, institution_id, name, base_url, lti_issuer, lti_client_id, lti_jwks_url, lti_auth_url,
                        lti_token_url, api_client_id, api_client_secret_enc bytea, privacy_level,
                        live_events_enabled bool, live_events_jwks_url?, status
                        unique (lti_issuer, lti_client_id)
lti_deployments         id, institution_id, canvas_integration_id, deployment_id, scope (account|course), canvas_account_id?
                        unique (canvas_integration_id, deployment_id)
canvas_tokens           id, institution_id, canvas_integration_id, purpose (integration_account|user), canvas_user_id?,
                        access_token_enc, refresh_token_enc, expires_at, scopes text[]   -- envelope-encrypted, never returned by API
lti_launch_state        state (pk text), nonce, canvas_integration_id, created_at, consumed_at   -- TTL purge 10 min
lti_nonces_used         nonce pk, iss, expires_at
```

### Identity and membership

```text
users                   id, institution_id, display_name?, given_name?, family_name?, email?, email_verified_by (lti|nrps|rest),
                        status (active|deleted), deleted_at?        -- email/name nullable for erasure; never a key
external_identities     id, institution_id, user_id, canvas_integration_id, kind (lti_sub|canvas_user_id|sis_user_id|lti11_user_id),
                        value, unique (canvas_integration_id, kind, value)
org_units               id, institution_id, parent_id?, name, kind (faculty|department|programme|other)
memberships             id, institution_id, user_id, scope_type (institution|org_unit|issuer|course), scope_id,
                        role (student|lecturer|course_admin|issuer_manager|dept_admin|inst_admin),
                        source (lti|nrps|grant), granted_by?, expires_at?, revoked_at?
                        unique (user_id, scope_type, scope_id, role) where revoked_at is null
courses                 id, institution_id, canvas_integration_id, canvas_course_id, lti_context_id, title, course_code,
                        org_unit_id?, activated_at?, activated_by?, status
                        unique (canvas_integration_id, canvas_course_id)
```

### Issuers and keys

```text
issuers                 id, institution_id, org_unit_id?, slug, name, url, email?, description, image_asset_id?,
                        did (unique), approved_by?, approved_at?, status (draft|active|suspended)
issuer_keys             id, institution_id, issuer_id, verification_method_id (did#key-n), public_key_multibase,
                        algorithm ('Ed25519'), state (pending|active|retired|revoked), activated_at?, retired_at?,
                        revoked_at?, revocation_reason?, is_dev bool
                        partial unique (issuer_id) where state = 'active'
keys.private_keys       issuer_key_id pk, ciphertext, dek_wrapped, kek_ref, created_at    -- signer role only
issuer_delegations      id, institution_id, issuer_id, scope_type (org_unit|course), scope_id, granted_by, revoked_at?
```

### Authoring

```text
badge_assets            id, institution_id, kind (upload|template), media_type (image/svg+xml|image/png), storage_key,
                        sha256, width, height, bytes, alt_text, licence?, sanitised bool, png_rendition_key?
badge_templates         id, institution_id, org_unit_id?, name, defaults jsonb (title, description, outcomes, criteria scaffold,
                        evidence expectations, skills, validity_days, asset_id)
achievement_definitions id, institution_id, issuer_id, course_id?, template_id?, owner_user_id, state
                        (draft|in_review|approved|published|archived), current_version_id?, award_policy
                        (automatic|lecturer_confirmed|manual)
achievement_versions    id, institution_id, definition_id, version_no, title, short_description, description,
                        learning_outcomes jsonb, criteria_narrative, category, achievement_type (OB3 enum),
                        demonstration_kind (attending|participating|completing|demonstrating|assessed),
                        evidence_description?, validity_days?, skills jsonb (alignment[]), asset_id, credit_claim_approved bool,
                        content_hash, published_at?, published_by?, frozen bool
                        unique (definition_id, version_no); trigger: no UPDATE when frozen
definition_reviews      id, institution_id, definition_id, version_id, reviewer_id, decision (approve|reject|comment),
                        checklist jsonb (clarity, level, evidence, alignment, accessibility, terminology), comment
award_rule_sets         id, institution_id, version_id unique, mode (ALL|ANY), schema_version ('rules/v1')
award_rules             id, institution_id, rule_set_id, parent_rule_id? (one level), position, type, params jsonb,
                        source_status (ok|source_missing|source_changed)
```

### LMS snapshots (written by sync, read by rules)

```text
lms_modules             id, institution_id, course_id, canvas_module_id, name, requirement_type, has_requirements bool,
                        workflow_state, fetched_at
lms_module_progress     id, institution_id, course_id, user_id, canvas_module_id, state, completed_at?, fetched_at,
                        unique (course_id, user_id, canvas_module_id)
lms_assignments         id, institution_id, course_id, canvas_assignment_id, name, points_possible, published, deleted, fetched_at
lms_submissions         id, institution_id, course_id, user_id, canvas_assignment_id, workflow_state, submitted_at?,
                        score?, excused, posted_at?, grade_matches_current_submission, missing, late, fetched_at
sync_runs               id, institution_id, course_id, kind (initial|scheduled|on_demand|hint), started_at, finished_at?,
                        status (ok|partial|failed), error jsonb
```

### Evaluation, awards, credentials

```text
eligibility_evaluations id, institution_id, version_id, user_id, outcome (met|not_met|unknown), detail jsonb (per-rule
                        outcome, source, explanation codes), inputs_hash, triggered_by (sync|manual|reeval), evaluated_at
award_decisions         id, institution_id, version_id, user_id, issuer_id, kind (automatic|confirmed|manual),
                        evaluation_id? , justification?, decided_by?, decided_at, status
                        (awaiting_confirmation|ready|issued|rejected|failed), issuance_seq int default 1,
                        idempotency_key unique
                        check (evaluation_id is not null or justification is not null)
credentials             id, institution_id, award_decision_id unique, issuer_id, issuer_key_id, version_id, user_id,
                        credential_uri ('urn:uuid:…') unique, status (pending_signature|issued|failed),
                        signed_json jsonb?, content_hash?, valid_from, valid_until?, issued_at?,
                        recipient_salt, recipient_hash, status_list_id, status_list_index
                        partial unique (version_id, user_id) where status <> 'failed' and not superseded
                        unique (status_list_id, status_list_index)
credential_evidence     id, institution_id, credential_id, kind (completion_record|assessment_result|evaluation_statement|
                        artefact|lecturer_confirmation), narrative, url?, include_in_credential bool, public bool
credential_status       credential_id pk, institution_id, state (active|revoked|suspended), reason_code?, reason_text?,
                        changed_by?, changed_at
credential_status_events id, institution_id, credential_id, from_state, to_state, reason, actor_id, request_id?, at
revocation_requests     id, institution_id, credential_id, requested_by, reason, status (open|approved|rejected), decided_by?
status_lists            id, institution_id, issuer_id, purpose ('revocation'), url_path, size (131072), next_publish_due,
                        published_credential jsonb?, published_at?, published_key_id?
status_list_bits        status_list_id, index, credential_id?  (pk status_list_id+index) -- allocation table
share_grants            id, institution_id, credential_id, share_id (base64url, 128-bit) unique, show_name bool,
                        show_evidence bool, created_by, revoked_at?
```

### Audit and jobs

```text
audit_events            id, institution_id?, actor_user_id?, actor_kind (user|system|lti), action, resource_type,
                        resource_id, request_id, at, data jsonb (no free-text PII)  -- INSERT only
background_jobs         view over procrastinate tables + app columns (kind, subject_type, subject_id, attempts, last_error,
                        dead_lettered_at) for admin visibility and reconciliation
```

## Institution policy (`institutions.policy`)

```json
{
  "definitions_require_approval": true,
  "self_approval_allowed": false,
  "approver_roles": ["dept_admin", "inst_admin"],
  "manual_awards_require_second_approval": false,
  "revokers": ["inst_admin", "dept_admin"],
  "score_rules_default_policy": "lecturer_confirmed",
  "score_rules_force_confirmation": false,
  "course_activation_required": true,
  "max_snapshot_age_minutes": 120,
  "include_recipient_name_in_credential": false
}
```

`score_rules_default_policy` reflects Gary's answer: each badge may pick `automatic` or `lecturer_confirmed`; the institution sets the default and may force confirmation.

## Data lifecycle

- **Account deletion / erasure:** null `users` PII columns, delete external identities and snapshots, keep `credentials` rows (signed JSON contains only the salted hash, no name/email by default) so verification still works; withdraw all share grants. Documented in `docs/security/erasure.md` (W7).
- **Unshare** deletes nothing: sets `share_grants.revoked_at`.
- **Revoke** changes status only.
- Retention jobs purge: launch state (10 min), snapshots for inactive courses (policy, default 1 year after course end), audit events (policy, default 7 years), failed jobs (90 days).

## Implementation notes (W2)

The Alembic migrations in `backend/migrations/` implement this model. Small additions made
while building it:

- `institutions.is_demo`: development login only works for demo tenants.
- `credentials.superseded_by_id`: the reissue pointer. The "not superseded" condition of the
  live-credential partial unique index uses it, and it is the only column the immutability
  trigger lets change after issue.
- `dev_seed` values on `users.email_verified_by`, `memberships.source`, `sync_runs.kind` and
  `eligibility_evaluations.triggered_by`, so seeded rows are always distinguishable.
- `award_rules.type` includes `group` for the single permitted nesting level.
- `keys.private_keys` also has `algorithm`, `is_dev` and `destroyed_at` (signer start-up guard
  and the 30-day destruction of retired keys).
- `lti_launch_state` keeps a UUID primary key with `state` unique.
- `background_jobs` is a view over `jobs.procrastinate_jobs`, filtered to the current tenant
  via `args.institution_id`.
- RLS: `institutions` is readable by everyone (needed to resolve a tenant) and updatable only
  for the current tenant. `audit_events` allows NULL-tenant system rows to be inserted. The LTI
  state and nonce tables are pre-tenant and have no RLS.
