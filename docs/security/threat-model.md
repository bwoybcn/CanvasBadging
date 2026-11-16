# Threat model (spec §15.4)

This document covers each of the 15 threats that spec §15.4 lists. For each one it gives the
attack, the controls in the code, the tests that prove those controls, and what risk remains.
Test names point to `backend/tests/` unless a path says otherwise. `E1`–`E12` are the Playwright
scenarios in `tests/end_to_end/specs/scenarios.spec.ts`.

Reviewed for release on 13 November 2026 (W8). Review it again whenever a new route, role,
integration or key type is added. The pre-production checklist in
[security-guide.md](security-guide.md#pre-production-security-review) asks for this.

## Assets and trust boundaries

| Asset | Where it lives | Who may touch it |
|---|---|---|
| Issuer signing keys (Ed25519) | `keys.private_keys`, encrypted under `SIGNER_KEK`; decrypted only inside the signer | Signer DB role `oc_signer` only. The app role cannot read the table. |
| Issued credentials | `issued_credentials` (immutable, append-only) | Issuance service; students read their own |
| Revocation state | Bitstring status lists, served publicly | Authorised revokers (institution policy) |
| Canvas API tokens | `canvas_tokens`, encrypted under `OC_TOKEN_ENCRYPTION_KEY` | Backend only; never sent to a browser |
| Learner personal data | `users`, memberships, snapshots, evidence | The learner, scoped staff, retention jobs |
| Audit log | `audit_events` (append-only trigger) | Read by institution admins; purge only by retention function |

Trust boundaries:
1. Browser (inside the Canvas iframe) to API, via a bearer session token.
2. Canvas to OpenCredential, via an LTI 1.3 launch and the REST API.
3. API and worker to the signer, on an internal network with a shared secret.
4. Public internet to the verification pages, status lists and DID documents.
5. Application role to database, with row-level security per institution.

## Threats

### 1. Forged LTI launch

**Attack.** Someone posts a hand-made `id_token` to `/lti/launch`, or replays a captured one, to
sign in as a lecturer.

**Controls.** OIDC login with `state` and `nonce` bound to the browser. The token signature is
checked against the platform JWKS (unknown `kid` causes one refetch, then refusal). The checks
cover `iss`, `aud`/`azp`, `deployment_id`, `exp`/`iat` with bounded clock skew, the message type
and the version. `alg` is restricted to RS256/384/512 (`none` and HS* are refused). State is single use
and burned even on a failed launch. Disabled registrations cannot log in.

**Tests.** `integration/test_lti_launch.py`: `test_bad_signature_rejected`,
`test_disallowed_algorithms`, `test_invalid_claims_rejected`, `test_unknown_kid_refetches_once_then_rejects`,
`test_malformed_token`, `test_replayed_launch_is_rejected`, `test_same_token_with_fresh_state_is_rejected`,
`test_nonce_reuse_is_rejected`, `test_rejected_launch_still_burns_state`, `test_unknown_state`,
`test_expired_state`, `test_missing_state_and_token`, `test_login_rejections`,
`test_disabled_registration_cannot_log_in`.

**Residual risk.** This depends on Canvas keeping its private key safe. If the platform is
compromised, launches from it are trusted. That is inherent to LTI.

### 2. Privilege escalation

**Attack.** A student sends `role: "lecturer"` in a request, edits the session token, or calls
staff routes directly.

**Controls.** Roles come only from the validated LTI roles claim and from delegated memberships
stored on the server. Request bodies never carry authority. Session tokens are HS256 JWTs signed
with `OC_SECRET_KEY`. They expire after 30 minutes and are checked on every request. A valid
token can be exchanged for a fresh one (`POST /api/v1/session/renew`) for up to 8 hours after
the Canvas launch (`OC_SESSION_MAX_MINUTES`); the launch time travels in the token and cannot
be moved, and renewal re-checks that the account is still active. Every
route declares its permission check in `authz/policy.py`. Delegation cannot grant a role above
the granter's own scope (`can_grant`). Expired memberships stop counting.

**Tests.** `test_roles_follow_canvas_and_ignore_client_input`, `test_role_mapping` (W3);
`unit/test_sessions.py` (`test_rejects_other_key`, `test_rejects_expired`,
`test_rejects_garbage_and_alg_none`); `test_delegated_role_management`,
`test_expired_roles_stop_working`, `test_department_admin_scope_for_issuers` (W7).
`integration/test_security.py` runs the full matrix: `test_every_api_route_refuses_anonymous_callers`
(every route in the OpenAPI document), `test_forged_or_malformed_tokens_are_refused`,
`test_tampered_session_token_is_refused`, `test_student_cannot_change_anything_that_is_not_theirs`
(every mutating route as a student) and `test_student_reads_only_their_own_records`.

**Residual risk.** A stolen session token is valid until it expires (at most 30 minutes), and
whoever holds it can renew it until the session limit (8 hours from the launch by default).
Renewal does not cancel the earlier token, which runs out on its own time. Set
`OC_SESSION_MAX_MINUTES` to the session lifetime to switch renewal off. The
token sits in `sessionStorage`, so an XSS bug could read it. The CSP and output escaping
(threat 9) are the defence there.

### 3. Cross-tenant access

**Attack.** An administrator at institution A reads or changes institution B's badges, learners
or credentials by guessing ids.

**Controls.** PostgreSQL row-level security is on every tenant table, keyed to
`app.institution_id`, which is set per transaction from the session. The app role does not own
the tables, so it cannot bypass RLS. Composite foreign keys include `institution_id`, so a row
cannot point into another tenant. Not-found and forbidden look the same to the caller (404).

**Tests.** `integration/test_tenant_isolation.py` (all 7 tests);
`test_every_tenant_table_has_rls` (migrations);
`test_session_from_one_tenant_cannot_see_user_of_another`;
`test_admin_of_one_institution_cannot_touch_another` (W8, every admin route against the other
tenant's ids); `test_scenario_10_unauthorized_access`; Playwright `E10`.

**Residual risk.** The owner role (used only for migrations) bypasses RLS by design. Keep its
credentials out of the running services ([production guide](../deployment/production.md#database-roles)).

### 4. Fraudulent issuance

**Attack.** A lecturer issues a badge from an issuer they have no authority over, or before the
badge is approved, or on stale or partial Canvas data.

**Controls.** An issuer can sign only after an institution administrator authorises it with a
recorded basis of authority. Badges must be approved and published before any award. Org units
marked "may not issue" are blocked. Rules use three-valued logic, so unknown Canvas data never
counts as met. Stale or failed sync results stop evaluation. A change in Canvas pauses the
affected badges.

**Tests.** `test_unapproved_issuer_cannot_issue` (W4);
`test_issuer_must_be_delegated_and_outsiders_are_refused`,
`test_stale_or_failed_canvas_data_never_issues`, `test_canvas_change_pauses_affected_badges`,
`test_rules_are_checked_against_canvas` (W5);
`test_issuer_needs_explicit_authority_before_it_can_be_used`, `test_departments_that_may_not_issue` (W7);
`unit/test_rules_engine.py` (`test_never_met_without_release`, `test_module_unknown_states`);
`unit/test_expected_outcomes.py`; Playwright `E1`, `E2`.

### 5. Unauthorised manual award

**Attack.** A lecturer awards a manual badge to a friend with no justification, or outside their
course.

**Controls.** Manual awards need the award permission in that course, a written justification
(stored and audited), and, when the institution's policy requires it, a second approver who is
not the requester.

**Tests.** `test_scenario_5_manual_award_with_justification`,
`test_second_approval_policy_for_manual_awards`, `test_lecturer_confirms_a_requirement_rule_e` (W5);
the W8 student matrix; Playwright `E5`.

### 6. Signing-key compromise

**Attack.** Someone steals an issuer's private key and signs their own credentials.

**Controls.** Keys are generated in the signer and stored encrypted with envelope encryption (AES-256-GCM data key
wrapped by `SIGNER_KEK`, bound to the key id). The app role cannot read the key table. The signer API never returns key
material. Production refuses to start with development secrets or an active development key.
There is a written and tested compromise procedure: retire the key, publish a new
verification method, decide what to do with credentials signed in the exposure window, and keep
the historical public key so honest credentials still verify.

**Tests.** `test_app_role_cannot_read_private_keys` (W4 and tenant isolation);
`test_signer_holds_encrypted_key_only`; `test_production_refuses_active_dev_key`;
`unit/test_settings.py` (refuses development secrets); signer `test/signer.test.ts`
("generates and stores an encrypted key, never returning the secret", "refuses committed
development secrets in production") and `test/proofs.test.ts` ("will not sign with a retired or
destroyed key"); `test_key_compromise_procedure`; `test_did_web_rotation_keeps_old_credentials_verifiable`.
Runbook: [key-compromise.md](key-compromise.md).

**Residual risk.** `SIGNER_KEK` is an environment variable, not an HSM. Anyone with root on the
signer host can recover keys. For production at scale, see the
[security guide](security-guide.md#keys) on moving the KEK into a secrets manager.

### 7. Replay attacks

**Attack.** Someone replays an LTI launch, an OAuth callback, or an issuance request.

**Controls.** LTI state and nonce are single use (threat 1). The OAuth `state` is a signed,
short-lived JWT bound to the user. Issuance is idempotent: one decision per learner, badge and
version, enforced by a unique constraint, and the signer call carries an idempotency key.

**Tests.** `test_replayed_launch_is_rejected`, `test_nonce_reuse_is_rejected`,
`test_forged_oauth_state_is_refused` (W3); `test_duplicate_event_creates_no_duplicate`,
`test_second_decision_for_same_learner_is_a_duplicate` (W4).

### 8. Duplicate issuance

**Attack or fault.** The same Canvas event is processed twice, or a worker dies after signing
but before saving.

**Controls.** A unique decision key per learner and badge version. The credential id is fixed
before signing, so a retry produces the same credential. A reconciliation view lists approved
awards that were not issued.

**Tests.** `test_scenario_3_duplicate_events_create_nothing_new` (W5);
`test_interrupted_issuance_recovers_without_duplicates`, `test_signer_outage_is_transient` (W4);
`test_worker_issues_and_queues_status_list_publication` (W8, real worker);
`test_reconciliation_of_awards_not_issued` (W7); Playwright `E3`, `E12`.

### 9. Exposure of private evidence

**Attack.** A public share page, its Open Graph tags or a search engine leaks a learner's name,
email, grades or evidence.

**Controls.** Nothing is public by default. A share link is an opaque 128-bit random id
(`secrets.token_urlsafe(16)`), unrelated to any user or credential id. The student previews exactly what will be public before sharing.
Evidence appears only when the badge allows it *and* the student shares it. Open Graph tags carry
achievement data only. Unshared and non-public routes send `X-Robots-Tag: noindex`. All public
HTML is escaped, and the SPA has a strict Content Security Policy.

**Tests.** `test_sharing_is_off_by_default_opaque_and_owner_only`,
`test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data`,
`test_public_check_page_and_robots` (W6); `unit/test_ob3.py`
(`test_only_disclosed_evidence_and_expiry`, `test_name_only_when_policy_allows`);
`test_script_in_badge_text_is_escaped_on_public_pages`, `test_security_headers` (W8);
Playwright `E11` and the axe run on a share page.

### 10. Credential tampering

**Attack.** A holder edits their downloaded credential, for example changing the achievement
name, and presents it.

**Controls.** An `eddsa-rdfc-2022` Data Integrity proof over the canonicalised credential. Any
change breaks the signature. Issued rows are immutable in the database (trigger), and
corrections are made by reissue with a recorded supersession.

**Tests.** `test_tampered_is_invalid` (W4); signer "signs an OpenBadgeCredential that verifies,
and detects tampering"; `integration/test_immutability.py`
(`test_issued_credential_content_is_immutable`, `test_issued_credential_cannot_be_deleted`);
Playwright `E7`, `E9`. Independently, the CI conformance job (DCC verifier-core and the 1EdTech
inspector) checks the proofs.

### 11. False verification results

**Attack or fault.** The verifier says "valid" for a revoked credential because the status list
could not be fetched, or says "fraud" when it was only an outage.

**Controls.** Five distinct outcomes: verified, revoked, expired, invalid, and
unable_to_verify. An infrastructure failure gives *unable to verify*, never valid or invalid.
The page explains that a valid signature is not proof of the educational claim.

**Tests.** `test_status_infrastructure_failure_is_unable_to_verify`, `test_expired`,
`test_downloaded_copy_is_recognised_as_revoked` (W4);
`test_scenario_7_external_verifier_reports_valid_then_revoked` (W6); Playwright `E7`, `E8`.

### 12. Misleading issuer identity

**Attack.** A department presents itself as "University of Liverpool", or the vendor appears as
the issuer.

**Controls.** An issuer profile needs institution approval and a recorded authority basis before
it can sign. Department issuers are labelled with their level. `did:web` identities are served
only from the institution's configured verification host. The development `did:key` is refused
in production.

**Tests.** `test_issuer_needs_explicit_authority_before_it_can_be_used`,
`test_did_web_issuer_on_configured_host` (W7); `test_production_refuses_active_dev_key`;
signer "refuses to sign for an issuer that does not control the key".

**Residual risk.** The verification domain is not yet chosen (Gary's decision, deferred). Until
it is, credentials are signed with demo identities that do not claim to be the university.

### 13. Unauthorised revocation

**Attack.** A lecturer revokes a student's credential out of spite, or a student revokes someone
else's.

**Controls.** Revocation needs a revoker role under the institution's policy within the
credential's scope, plus a written reason. Lecturers can only *request* a revocation, which an
admin approves. Revocation never deletes the credential, and the audit log records who did it
and why.

**Tests.** `test_revocation_requires_a_reason` (W4); `test_scenario_8_authorised_admin_revokes`,
`test_scenario_10_unauthorized_access` (W7); the W8 student matrix (revoke and revocation
approval routes); `frontend/src/pages/__tests__/admin.test.tsx` ("revokes a credential with a
reason and explains the effect"); Playwright `E8`.

### 14. Exposure of student identifiers

**Attack.** Someone harvests emails or Canvas ids from public credentials or share URLs.

**Controls.** The credential subject is a salted SHA-256 hash with a fresh salt per credential.
No email address is included, and no name unless the institution allows it (the flagged default
is no name). Share ids are opaque and unrelated to user ids. The audit log stores actor names
and ids, not learner names.

**Tests.** `unit/test_ob3.py` (`test_recipient_is_salted_hash_without_email_or_name`,
`test_salts_are_fresh_per_credential`); `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data`;
`test_no_canvas_token_or_secret_in_any_api_response` (W8); Playwright `E11`.

**Residual risk.** Anyone who holds a credential and guesses the learner's email can test the
guess against the hash. This is documented in ADR-0007 and the student guide.

### 15. External API failure

**Attack or fault.** Canvas is down, throttles us (403 with `X-Rate-Limit-Remaining`), returns
half a roster, or the signer is down.

**Controls.** Retries with backoff and a bounded number of attempts. A partial pagination
failure raises an error instead of returning a short list. A partial roster never revokes
memberships. Stale data blocks evaluation. A signer outage leaves the decision approved and
retryable, and it is shown in Failed issuance. The pagination `next` link may not point to
another origin.

**Tests.** `unit/test_canvas_adapter.py` (`test_canvas_throttle_403_is_retried_then_succeeds`,
`test_throttle_exhausted_is_transient`, `test_server_errors_and_timeouts_are_transient`,
`test_partial_pagination_failure_raises_not_partial_list`, `test_next_link_to_another_origin_is_refused`);
`test_partial_roster_never_revokes` (W3); `test_stale_or_failed_canvas_data_never_issues` (W5);
`test_signer_outage_is_transient` (W4); `test_failed_jobs_are_visible_and_retryable_per_tenant` (W5);
Playwright `E12` (signer stopped during issuance, then restarted).

## Threats beyond §15.4 that W8 also tested

| Threat | Control | Test |
|---|---|---|
| SQL injection | SQLAlchemy bound parameters only; no string-built SQL | `test_injection_strings_in_queries_are_inert` |
| Path traversal in asset and public routes | UUID path parameters; storage paths built from ids | `test_path_traversal_is_refused` |
| Malicious SVG artwork | Allow-list sanitiser, PNG chunk filter, size limits | `unit/test_artwork.py`, `test_malicious_svg_upload_is_sanitised`, `test_svg_upload_cannot_carry_script` |
| Oversized or malformed request bodies | Pydantic validation, upload size limits, problem+json errors | `test_malformed_and_oversized_bodies_fail_cleanly` |
| Canvas token leakage to the browser | Tokens stay on the server, encrypted at rest | `test_oauth_flow_stores_encrypted_tokens_and_never_returns_them`, `test_no_canvas_token_or_secret_in_any_api_response` |
| Clickjacking and content sniffing | `nosniff` on all responses, CSP on the SPA; framing is allowed because Canvas embeds the tool | `test_security_headers` |
| Vulnerable dependencies | `pip-audit` and `npm audit` in CI, Dependabot weekly | CI job "Dependency audit and licences"; [dependency report](../reports/dependency-scan.md) |

## Known gaps

* **General API rate limiting.** The app limits only the routes anyone can reach without
  signing in (the public badge checks and the LTI sign-in steps), per client address and per
  process, and Canvas sync per course. There is no limit per signed-in user. The general limit
  is the reverse proxy's: the production kit's proxy sets one, and an installation with its own
  proxy must too. It is listed in the [security report](../reports/security.md) as a release
  condition for public deployment.
* **The signer KEK is an environment variable**, not an HSM or a cloud KMS (threat 6, residual risk).
