# W7 delivery: institutional governance

Spec Phase 7 (§20), §2.3–2.4, §10, §12.5. Exit condition: *an institution can govern its
credential scheme without manually editing application data*. Built on W4 (issuance,
revocation) and W5 (authoring, rules, awards), both now on `main`.

## What was added

* **Schema** (migration `0005`): `issuers.level`, `issuers.authority_basis`,
  `org_units.may_issue` / `status`, `badge_templates.description` / `created_by` / `status`, and
  `app.purge_audit_events()`, the only path that can delete audit events (older than the
  retention period, minimum one year, enforced by the append-only trigger).
* **Services** in `backend/opencredential/governance/`: `institution`, `issuers`, `people`
  (org units, course placement, delegated roles), `templates`, `revocation` (authorised revoke
  and requests), `records` (issuance records, summary, CSV), `audit_log`, `privacy` (export and
  erasure), `retention`, `reconciliation`. Each checks the actor's scope itself; the session is
  tenant-scoped by RLS.
* **Authorisation** (`authz/policy.py`): administrative scope (`admin_org_units`), which units
  may issue (`org_unit_may_issue`, enforced when choosing an issuer, creating and publishing a
  badge, and authorising an issuer), who may grant which role (`can_grant`), who may revoke
  (`can_revoke`, policy `revokers` within each role's scope). Expired memberships no longer count.
* **API**: `api/routes/governance.py` (see `docs/api/openapi.json`, tag *institutional
  administration*); the policy endpoint gained `approver_roles`, `revokers` and
  `dept_admins_may_delegate`; `POST /credentials/{id}/revoke` now uses the policy;
  `GET /awards` accepts `kind`; `POST /achievements` accepts `template_id`.
* **Jobs**: nightly `apply_retention`.
* **UI**: Administration area with ten pages (overview, institution settings, policy, issuers,
  departments and roles, templates, issued credentials and revocation, reports, audit log,
  personal data and retention, failed issuance).
* **Docs**: [../administration/README.md](../administration/README.md) and
  [../administration/erasure.md](../administration/erasure.md) (D-ERASURE).

## Behaviour changes to earlier workstreams

* Exporting another learner's credential without authority now returns **404**, the same as a
  missing credential (scenario 10: denied without disclosure). It was 403.
* Revocation authority follows the institution policy across org-unit hierarchies (W4's check
  matched only the issuer's own org unit).
* `jobs.defer` reopens the shared procrastinate app if a worker run closed it.

## Evidence (RTM)

| RTM | Test (`backend/tests/integration/test_w7_governance.py` unless noted) |
| --- | --- |
| R-10.1 | `test_institution_configuration`, `test_did_web_issuer_on_configured_host` |
| R-10.2 | `test_issuer_needs_explicit_authority_before_it_can_be_used`, `test_department_admin_scope_for_issuers` |
| R-10.3 | `test_policy_configuration`, `test_departments_that_may_not_issue`, `test_delegated_role_management`, `test_expired_roles_stop_working` |
| R-10.4 | `test_templates_prefill_new_badges` |
| R-10.5 | `test_scenario_8_authorised_admin_revokes` (records, summary, CSV), `test_reconciliation_of_awards_not_issued` |
| R-10.6 | `test_scenario_8_authorised_admin_revokes` (categories, actor names, no learner names, allow-listed data) |
| R-12.5 | `test_personal_data_export_and_erasure_are_separate_from_revocation`, `test_retention_purges_expired_data_but_keeps_credentials`, D-ERASURE |
| R-2.4-08, E8 | `test_scenario_8_authorised_admin_revokes` (downloaded copy verifies as revoked) |
| E10 | `test_scenario_10_unauthorized_access` |
| UI | `frontend/src/pages/__tests__/admin.test.tsx` |

E8 and E10 here run against PostgreSQL and the real signer through the HTTP API; the Playwright
versions against the Canvas sandbox belong to W8.

## Not done here

* Bulk revocation and bulk role import (CSV upload): not in the MVP list; add if UoL asks.
* Department administrators do not see the audit log or failed jobs (job rows carry no org unit).
* Production backups and recovery (§2.4) are W8 (deployment).
