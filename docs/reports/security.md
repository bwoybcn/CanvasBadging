# Security test report (spec §15, §19.6)

Date: 13 November 2026 (W8). This summarises the security testing behind the release. The
reasoning is in the [threat model](../security/threat-model.md), and the operator's side is in the
[security guide](../security/security-guide.md).

## Summary

| Area (spec §19.6) | Result | Evidence |
|---|---|---|
| Authorisation | Pass. Every API operation (from the app's own OpenAPI document) refuses anonymous callers. Every mutating route refuses a student, except a short allowlist of the student's own actions, and those give 404 for another learner's records. | `test_security.py`: `test_every_api_route_refuses_anonymous_callers`, `test_student_cannot_change_anything_that_is_not_theirs`, `test_student_reads_only_their_own_records` |
| Authentication | Pass. Forged, tampered, expired, `alg: none` and wrong-key tokens are refused; so are forged and replayed LTI launches. | `test_forged_or_malformed_tokens_are_refused`, `test_tampered_session_token_is_refused`, `unit/test_sessions.py`, `test_lti_launch.py` (23 tests) |
| Cross-tenant | Pass. An institution administrator gets 404 on every administrative route when using another institution's ids. Row-level security is on every tenant table and is tested at the database level. | `test_admin_of_one_institution_cannot_touch_another`, `test_tenant_isolation.py`, `test_every_tenant_table_has_rls`, Playwright E10 |
| Malicious input | Pass. SQL injection strings are inert. Script in badge text is escaped on public pages. Path traversal is refused. Malformed and oversized bodies fail cleanly (problem+json, no stack trace). SVG with script or external references is neutralised. | `test_injection_strings_in_queries_are_inert`, `test_script_in_badge_text_is_escaped_on_public_pages`, `test_path_traversal_is_refused`, `test_malformed_and_oversized_bodies_fail_cleanly`, `test_svg_upload_cannot_carry_script`, `unit/test_artwork.py` |
| Secrets | Pass. No Canvas token, key or secret appears in any API response. The app database role cannot read private keys. Production refuses development secrets and keys. | `test_no_canvas_token_or_secret_in_any_api_response`, `test_app_role_cannot_read_private_keys`, `unit/test_settings.py`, `test_production_refuses_active_dev_key` |
| Response headers | Pass | `test_security_headers` |
| Dependency checks | Pass. No known vulnerabilities in runtime dependencies. | [dependency-scan.md](dependency-scan.md) |
| Threat model (15 threats in §15.4) | Each has controls and named tests | [threat-model.md](../security/threat-model.md) |
| Key compromise procedure | Documented and tested | [key-compromise.md](../security/key-compromise.md), `test_key_compromise_procedure` |
| Backup and restore | Destructive drill passes in CI | [backup-restore.md](../operations/backup-restore.md) |
| Pre-production security review | Checklist written; to be completed per installation | [security guide](../security/security-guide.md#pre-production-security-review) |

The full backend suite (290 tests, PostgreSQL and the real signer) passed locally, and CI runs
it on every change.

## Changes made in W8 because of testing

| Change | Why |
|---|---|
| Security headers on every response (`nosniff`, `Referrer-Policy`), a CSP on the SPA, `no-store` on the API, HSTS over HTTPS | Defence in depth against XSS, content sniffing and caching of personal data |
| Worker issuance fix (`jobs/defer.py`) | Not a security defect, but it left new credentials "unable to verify" (threat 11) |
| A new status list is published by the issuing job itself | A fresh credential was "unable to verify" for about 10 seconds (threat 11) |
| Course activation, with an audit record | Without it, courses were never reconciled with Canvas, so stale data could persist (threat 15) |

## Open items (release conditions, not code defects)

| Item | Risk | Owner | Before |
|---|---|---|---|
| General rate limiting is at the reverse proxy. Since 16 November 2026 the production kit's proxy sets it, and the app has a basic limit of its own on the public badge checks and sign-in steps | Brute force, or scraping of the public `/verify` endpoints | Operator ([security guide](../security/security-guide.md#network)): confirm it on the installed proxy | Public go-live |
| `SIGNER_KEK` is an environment variable, not an HSM or KMS | Key theft by someone with root on the signer host | Operator; optional KMS integration later | Go-live, by accepting the risk or adding a KMS |
| Verification domain not chosen; credentials use a development `did:key` | Cannot issue real credentials until decided | Gary / the university | Pilot |
| Independent penetration test | Spec §19.6 asks for a pre-production review; an external test is recommended for a university deployment | The university | Go-live |
