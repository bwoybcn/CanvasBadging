# Requirements traceability: evidence (W8 final)

Date: 13 November 2026. This document gives every row of the [requirements traceability
matrix](../architecture/rtm.md) a status and the evidence behind that status. The RTM says what was
planned; this says what proves it today.

**Status values.**
*Pass* means a named test passes in CI on the release branch, or, for a documentation row, the
named document exists and was followed.
*Partial* means the core is proven and a named part is not. The gap is stated.
*Open* means the row is not met. Every *Open* row is a release condition below.

**How to check.** CI runs every backend test against PostgreSQL 16 and the real signer, the
Playwright suite (E1–E12 and the accessibility checks) against the running stack, and the
independent verifiers (DCC verifier-core and the 1EdTech inspector) against credentials the stack
issued. The full backend suite (290 tests) also passed locally on 13 November.

## Summary

| | Rows |
|---|---|
| Pass | 193 (one of them, R-20, a recorded deviation in format) |
| Partial: a named part needs a person, real hosted Canvas, or the verification domain | 9 |
| Fail or open | 0 |
| Total | 202 |

**No MUST row is failing.** Seven of the nine partial rows depend on things outside the code: a
manual screen-reader pass, NRPS on a hosted Canvas, the verification domain for wallet import,
and rate limiting at the reverse proxy. They are the four [release
conditions](#release-conditions). The other two (R-1.1, the fixed product name, and R-3.1-01, E1–E12
not automated against real Canvas) are noted but do not block release.

## Key to evidence

Backend test files are under `backend/tests/`. Short names used below:

| Short name | File |
|---|---|
| W3-LTI | `integration/test_w3_lti_launch.py` |
| W3-CAN | `integration/test_w3_canvas_access.py` |
| W4 | `integration/test_w4_issuance.py` |
| W5 | `integration/test_w5_scenarios.py` |
| W5-JOBS | `integration/test_w5_jobs_and_seed.py` |
| W6 | `integration/test_w6_sharing.py` |
| W7 | `integration/test_w7_governance.py` |
| W8-SEC | `integration/test_w8_security.py` |
| W8-ACT | `integration/test_w8_course_activation.py` |
| W8-WRK | `integration/test_w8_worker.py` |
| TEN | `integration/test_tenant_isolation.py` |
| IMM | `integration/test_immutability.py` |
| MIG | `integration/test_migrations.py` |
| SEED | `integration/test_seed_and_api.py` |
| U-x | `unit/test_x.py` (for example U-rules_engine, U-canvas_adapter, U-ob3, U-artwork) |
| FE | `frontend/src/**/*.test.tsx` (Vitest, by test title) |
| E1–E12 | `tests/end_to_end/specs` (Playwright), described in [e2e.md](e2e.md) |
| A11Y | the Playwright accessibility projects, described in [accessibility.md](accessibility.md) |
| CONF | the CI job "Independent OB 3.0 verifiers", described in [conformance.md](conformance.md) |
| RC | the real-Canvas run of 13 November, in [e2e.md](e2e.md#2-real-canvas-over-https) |

## §0–1 Process and principles

| ID | Status | Evidence |
|---|---|---|
| R-0.1 | Pass | CONF: credentials issued by the running stack pass the 1EdTech inspector and DCC verifier-core. The only signing path is the signer; test doubles live under `tests/` |
| R-0.2 | Pass | [conformance.md](conformance.md) ties every claim to CI run evidence and says plainly that OpenCredential is **not certified** |
| R-0.3 | Pass | RTM, [standards-check.md](../standards/standards-check.md), [architecture.md](../architecture/architecture.md) and [open-questions.md](../architecture/open-questions.md) merged in PR1 before code |
| R-0.4 | Pass | ADRs in `docs/architecture/adr/`, [dependencies.md](../architecture/dependencies.md), [open-questions.md](../architecture/open-questions.md), delivery notes W5–W7 |
| R-1.1 | Partial | The Canvas menu label is configurable (`oc lti config --label`, `test_tool_jwks_and_canvas_config`) and so is the institution's name and branding (`test_institution_configuration`). The product name "OpenCredential" in the app header is fixed. Minor; not a release blocker |

## §2 Users and permissions

| ID | Status | Evidence |
|---|---|---|
| R-2.1-01 | Pass | E2; W5 `test_scenario_2_completion_records_eligibility_and_requests_issuance`; FE "gives students the student view" |
| R-2.1-02 | Pass | FE "shows a student what is confirmed and what is pending"; U-rules_engine (explanations per rule) |
| R-2.1-03 | Pass | E2; U-rules_engine; FE "shows a student what is confirmed and what is pending" |
| R-2.1-04 | Pass | E2, E6; FE "groups earned credentials by course and shows status and privacy" |
| R-2.1-05 | Pass | W6 `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data`; U-ob3 `test_only_disclosed_evidence_and_expiry` |
| R-2.1-06 | Pass | E6; W6 `test_scenario_6_student_export_is_valid_ob3_with_verifiable_proof`; CONF (48 student copies) |
| R-2.1-07 | Pass | E11; W6 `test_phase6_exit_earn_download_share_and_outsider_verifies` |
| R-2.1-08 | Pass | W6 `test_scenario_11_linkedin_gets_certification_fields_and_a_working_url`, `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data` |
| R-2.1-09 | Pass | FE "groups earned credentials by course and shows status and privacy"; W6 `test_phase6_exit_earn_download_share_and_outsider_verifies` |
| R-2.1-10 | Pass | W6 `test_sharing_is_off_by_default_opaque_and_owner_only`; FE "stops sharing without revoking" |
| R-2.1-11 | Pass | FE "previews exactly what becomes public before sharing, then shares"; W6 `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data` |
| R-2.1-12 | Pass | W8-SEC `test_student_cannot_change_anything_that_is_not_theirs`, `test_student_reads_only_their_own_records`; E10 |
| R-2.2-01 | Pass | E1; W5 `test_scenario_1_lecturer_creates_previews_and_publishes`; RC |
| R-2.2-02 | Pass | W5 `test_scenario_1_lecturer_creates_previews_and_publishes` (edits refused after approval); IMM `test_frozen_version_cannot_change` |
| R-2.2-03 | Pass | E1; U-rules_engine `test_spec_example_parses`, `test_invalid_rule_sets_are_rejected`; FE "edits a draft through every step and saves fields and rules" |
| R-2.2-04 | Pass | W5 `test_rules_are_checked_against_canvas`; RC (module picker listed real Canvas modules) |
| R-2.2-05 | Pass | U-artwork (9 tests); W5 `test_malicious_svg_upload_is_sanitised` |
| R-2.2-06 | Pass | E1; FE "shows a preview that is clearly not a credential" |
| R-2.2-07 | Pass | W5 `test_scenario_1_lecturer_creates_previews_and_publishes`, `test_reject_returns_to_draft_and_review_checks` |
| R-2.2-08 | Pass | W5 `test_scenario_1_lecturer_creates_previews_and_publishes`, `test_issuer_must_be_delegated_and_outsiders_are_refused` |
| R-2.2-09 | Pass | E2, E4; RC (Course progress against real Canvas data) |
| R-2.2-10 | Pass | E5; W5 `test_scenario_5_manual_award_with_justification` |
| R-2.2-11 | Pass | W5 `test_released_grade_then_lecturer_confirmation`; FE "confirms a lecturer-confirmed award" |
| R-2.2-12 | Pass | W8-ACT `test_course_staff_see_and_export_their_course_award_history`; FE "shows the course award history and lets staff ask for a revocation, without revoking anything" |
| R-2.2-13 | Pass | W7 `test_scenario_8_authorised_admin_revokes` (request recorded, credential unchanged until approved); FE as R-2.2-12 |
| R-2.2-14 | Pass | W8-ACT `test_course_staff_see_and_export_their_course_award_history` (CSV, audited, `no-store`) |
| R-2.2-15 | Pass | W5 `test_issuer_must_be_delegated_and_outsiders_are_refused`; W7 `test_issuer_needs_explicit_authority_before_it_can_be_used` |
| R-2.3-01 | Pass | W7 `test_department_admin_scope_for_issuers`; W5 `test_reject_returns_to_draft_and_review_checks` |
| R-2.3-02 | Pass | W5 `test_reject_returns_to_draft_and_review_checks`; FE "lets a reviewer approve only after every checklist point" |
| R-2.3-03 | Pass | W7 `test_templates_prefill_new_badges` |
| R-2.3-04 | Pass | W7 `test_department_admin_scope_for_issuers`, `test_departments_that_may_not_issue` |
| R-2.3-05 | Pass | W7 `test_scenario_8_authorised_admin_revokes` (revocation requests), `test_reconciliation_of_awards_not_issued` |
| R-2.3-06 | Pass | W7 `test_delegated_role_management`, `test_expired_roles_stop_working` |
| R-2.4-01 | Pass | W3-CAN `test_oauth_flow_stores_encrypted_tokens_and_never_returns_them`, `test_registry_builds_canvas_adapter_for_active_integration`; RC (installed on real Canvas) |
| R-2.4-02 | Pass | W7 `test_institution_configuration` |
| R-2.4-03 | Pass | W4 `test_did_web_rotation_keeps_old_credentials_verifiable`, `test_key_compromise_procedure`; W7 `test_did_web_issuer_on_configured_host` |
| R-2.4-04 | Pass | W7 `test_policy_configuration`; W8-ACT `test_activation_policy_is_set_by_an_institution_administrator` |
| R-2.4-05 | Pass | W7 `test_templates_prefill_new_badges` |
| R-2.4-06 | Pass | W7 `test_delegated_role_management` |
| R-2.4-07 | Pass | W7 `test_scenario_8_authorised_admin_revokes` (records, summary, CSV) |
| R-2.4-08 | Pass | E8; W7 `test_scenario_8_authorised_admin_revokes` |
| R-2.4-09 | Pass | W7 `test_retention_purges_expired_data_but_keeps_credentials` |
| R-2.4-10 | Pass | W7 `test_personal_data_export_and_erasure_are_separate_from_revocation`; backup/restore drill in CI ([backup-restore.md](../operations/backup-restore.md), [drill log](evidence/backup-restore-drill.log)) |
| R-2.4-11 | Pass | W7 `test_scenario_8_authorised_admin_revokes` (audit categories and filters) |
| R-2.4-12 | Pass | W7 `test_did_web_issuer_on_configured_host`. The production domain itself is a university decision (release condition 3) |
| R-2.5-01 | Pass | E7, E9; W6 `test_scenario_7_external_verifier_reports_valid_then_revoked`, `test_scenario_9_export_survives_account_closure` |
| R-2.5-02 | Pass | E7; CONF |
| R-2.5-03 | Pass | E7; W6 `test_public_check_page_and_robots` |
| R-2.5-04 | Pass | E7; W6 `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data` |
| R-2.5-05 | Pass | E7, E8; W4 `test_expired`, `test_downloaded_copy_is_recognised_as_revoked` |
| R-2.5-06 | Pass | U-ob3 `test_only_disclosed_evidence_and_expiry`; W6 `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data` |
| R-2.5-07 | Pass | E7 asserts the "what verification means" text; wording in [students/README.md](../students/README.md) |

## §3–4 Architecture and Canvas

| ID | Status | Evidence |
|---|---|---|
| R-3.1-01 | Partial | E1–E12 run in CI against the fake LMS, which implements the same adapter interface. The core path (install, launch, author, review, publish, progress, award, share, verify, revoke) was run end to end on a real Canvas over HTTPS on 13 November (RC). The full E1–E12 set has not been automated against real Canvas |
| R-3.1-02 | Pass | CI "Module boundaries (import-linter)" step; contracts in `backend/pyproject.toml` |
| R-3.2 | Pass | [dependencies.md](../architecture/dependencies.md); CI licence allowlist (ADR-0018) |
| R-3.2-02 | Pass | Signer uses Digital Bazaar suites and Node `crypto`; backend uses `cryptography` and `joserfc`. No bespoke primitives (code review, [threat-model.md](../security/threat-model.md)) |
| R-3.4-01 | Pass | TEN (7 tests); MIG `test_every_tenant_table_has_rls`; W8-SEC `test_admin_of_one_institution_cannot_touch_another`; E10 |
| R-3.4-02 | Pass | CI "Docker Compose smoke test"; [deployment/production.md](../deployment/production.md) |
| R-3.4-03 | Pass | W7 `test_did_web_issuer_on_configured_host`; TEN `test_cannot_write_into_another_tenant` |
| R-3.4-04 | Pass | The Canvas HTTP client exposes only GET (the one POST is the OAuth token exchange); U-canvas_adapter; scopes in [canvas.md](../integrations/canvas.md#3-create-the-api-developer-key) |
| R-3.4-05 | Pass | TEN and W4 `test_app_role_cannot_read_private_keys`; SEED `test_signer_holds_encrypted_key_only` |
| R-3.4-06 | Pass | W7 `test_did_web_issuer_on_configured_host` |
| R-3.4-07 | Pass | E6, E9 |
| R-3.4-08 | Pass | Fake LMS and recorded fixtures (U-canvas_adapter); local Canvas used for RC |
| R-4.1-01 | Partial | W3-LTI (23 tests) and RC prove LTI 1.3. NRPS is tested with recorded responses (W3-CAN `test_roster_sync_provisions_and_revokes`, `test_partial_roster_never_revokes`). The live NRPS call fails on the local Canvas because of a known Canvas port bug; check it on a hosted Canvas |
| R-4.1-02 | Pass | [canvas.md](../integrations/canvas.md) followed on the local Canvas (RC), including the new "Changing the tool's address" step |
| R-4.1-03 | Pass | W3-LTI `test_tool_jwks_and_canvas_config` |
| R-4.1-04 | Pass | W3-LTI `test_role_mapping`; FE "shows the Canvas user and course context with the lecturer view", "gives students the student view" |
| R-4.1-05 | Pass | W3-LTI `test_relaunch_reuses_user_and_course` |
| R-4.1-06 | Pass | W8-ACT `test_first_launch_follows_the_institution_activation_policy`, `test_lecturer_activates_course_and_an_initial_sync_is_queued`, `test_only_active_courses_join_scheduled_reconciliation`; FE "lets a lecturer switch micro-credentials on from the launch page" |
| R-4.2-01 | Pass | W3-LTI `test_invalid_claims_rejected`, `test_bad_signature_rejected`, `test_disallowed_algorithms`, `test_expired_state` and 12 more |
| R-4.2-02 | Pass | W3-LTI `test_replayed_launch_is_rejected`, `test_nonce_reuse_is_rejected`, `test_same_token_with_fresh_state_is_rejected` |
| R-4.2-03 | Pass | W3-LTI `test_roles_follow_canvas_and_ignore_client_input` |
| R-4.2-04 | Pass | W3-LTI `test_cookie_blocked_browser_uses_platform_storage`; RC (launch inside the Canvas iframe) |
| R-4.3-01 | Pass | W3-CAN `test_roster_sync_provisions_and_revokes`; U-canvas_adapter |
| R-4.3-02 | Pass | U-canvas_adapter `test_modules_with_requirements_and_pagination`, `test_module_progress_states`; RC |
| R-4.3-03 | Pass | U-canvas_adapter `test_submissions_released_unreleased_excused` |
| R-4.3-04 | Pass | U-canvas_adapter `test_submissions_released_unreleased_excused`; U-rules_engine `test_unreleased_mark_is_not_recorded` |
| R-4.3-05 | Pass | [canvas.md](../integrations/canvas.md#3-create-the-api-developer-key) lists every scope; RC ran with only those scopes |
| R-4.3-06 | Partial | As R-4.1-01: NRPS proven with recorded responses, live call blocked by the local Canvas port bug |
| R-4.3-07 | Pass | ADR-0009; no AGS read path in the code |
| R-4.4-01 | Pass | W8-ACT `test_lecturer_activates_course_and_an_initial_sync_is_queued`, `test_only_active_courses_join_scheduled_reconciliation`; W5-JOBS `test_worker_consumes_sync_and_evaluation_jobs` |
| R-4.4-02 | Pass | U-canvas_adapter `test_next_link_parsing`, `test_canvas_throttle_403_is_retried_then_succeeds`, `test_low_bucket_slows_down` |
| R-4.4-03 | Pass | W5 `test_canvas_change_pauses_affected_badges` |
| R-4.4-04 | Pass | U-canvas_adapter `test_partial_pagination_failure_raises_not_partial_list`, `test_permission_and_not_found_are_explicit`; W5 `test_stale_or_failed_canvas_data_never_issues` |
| R-4.4-05 | Pass | Polling by design (ADR-0010, Gary's decision). The optional Live Events hint is not built; it is not required for MVP |
| R-4.4-06 | Pass | W5 `test_stale_or_failed_canvas_data_never_issues`; U-canvas_adapter `test_server_errors_and_timeouts_are_transient` |
| R-4.5 | Pass | `LmsAdapter` protocol with the fake and Canvas implementations; W3-CAN `test_registry_builds_canvas_adapter_for_active_integration`; import-linter |

## §5–6 Authoring and rules

| ID | Status | Evidence |
|---|---|---|
| R-5.1-01 | Pass | E1; FE "blocks a step until its problems are fixed", "edits a draft through every step and saves fields and rules" |
| R-5.1-02 | Pass | W5 `test_scenario_1_lecturer_creates_previews_and_publishes` (validation per required field); FE "blocks a step until its problems are fixed" |
| R-5.2-01 | Pass | W5 `test_scenario_1_lecturer_creates_previews_and_publishes`; seed categories (SEED `test_seed_content`) |
| R-5.2-02 | Pass | W5 `test_completion_badge_cannot_claim_competency` |
| R-5.3-01 | Pass | U-artwork `test_png_validation`, `test_alt_text_required`, `test_bad_svgs_are_rejected` |
| R-5.3-02 | Pass | U-artwork `test_malicious_svg_is_neutralised`; W8-SEC `test_svg_upload_cannot_carry_script` |
| R-5.3-03 | Pass | U-artwork `test_templates_render_and_are_safe`, `test_template_inputs_validated_and_contrast_warned` |
| R-5.4-01 | Pass | W5 `test_scenario_1_lecturer_creates_previews_and_publishes`, `test_reject_returns_to_draft_and_review_checks` |
| R-5.4-02 | Pass | W7 `test_policy_configuration` |
| R-5.4-03 | Pass | IMM `test_frozen_version_cannot_change`, `test_frozen_version_cannot_be_deleted` |
| R-5.5-01 | Pass | E1; FE "shows a preview that is clearly not a credential" |
| R-5.5-02 | Pass | E1 asserts "not issued and not verifiable"; FE as above |
| R-6.1 | Pass | U-rules_engine `test_deterministic_hash`, `test_engine_agrees_with_seed_oracle_for_every_learner_and_badge` |
| R-6.2-A | Pass | U-rules_engine `test_module_completed`, `test_module_incomplete_is_not_met_not_unknown`; E2 |
| R-6.2-B | Pass | U-rules_engine `test_multiple_modules` |
| R-6.2-C | Pass | U-rules_engine `test_submission_states` |
| R-6.2-D | Pass | U-rules_engine `test_score_rule`, `test_decimal_threshold_has_no_float_error`; E4 |
| R-6.2-E | Pass | U-rules_engine `test_manual_approval`; W5 `test_lecturer_confirms_a_requirement_rule_e`; E5 |
| R-6.2-F | Pass | U-rules_engine `test_nested_group`, `test_combine_is_kleene`, `test_invalid_rule_sets_are_rejected` |
| R-6.4-01 | Pass | W5 `test_scenario_2_completion_records_eligibility_and_requests_issuance` (source per result) |
| R-6.4-02 | Pass | U-expected_outcomes; U-rules_engine `test_module_unknown_states` |
| R-6.4-03 | Pass | E3; W5 `test_scenario_3_duplicate_events_create_nothing_new`; W4 `test_duplicate_event_creates_no_duplicate` |
| R-6.4-04 | Pass | U-expected_outcomes `test_unreleased_grade_is_unknown_not_met`, `test_excused_is_unknown`; E4 |
| R-6.4-05 | Pass | W5 `test_canvas_change_pauses_affected_badges` |
| R-6.4-06 | Pass | `POST /evaluations` and course refresh queue a re-evaluation (W5 `test_scenario_1_lecturer_creates_previews_and_publishes` asserts the `evaluate_course` job) |
| R-6.4-07 | Pass | U-rules_engine `test_invalid_rule_sets_are_rejected`; W5 `test_rules_are_checked_against_canvas` |
| R-6.4-08 | Pass | W5 `test_scenario_2_completion_records_eligibility_and_requests_issuance`; IMM `test_audit_events_append_only` |
| R-6.4-09 | Pass | E4; W5 `test_scenario_4_missing_or_unreleased_grade_stays_pending`, `test_badge_can_choose_automatic_unless_institution_forces_confirmation` |
| R-6.5-01 | Pass | W5 `test_badge_can_choose_automatic_unless_institution_forces_confirmation`, `test_released_grade_then_lecturer_confirmation`, `test_scenario_5_manual_award_with_justification`; E2, E5 |
| R-6.5-02 | Pass | MIG `test_schema_matches_models` (NOT NULL and foreign keys); W5 `test_scenario_5_manual_award_with_justification` |
| R-6.6 | Pass | E3, E12; W4 `test_interrupted_issuance_recovers_without_duplicates`, `test_second_decision_for_same_learner_is_a_duplicate` |

## §7–9 Credentials, learners and sharing

| ID | Status | Evidence |
|---|---|---|
| R-7.1 | Pass | CONF (1EdTech inspector and JSON Schema through DCC verifier-core); W4 `test_issued_credential_is_genuine_ob3` |
| R-7.2 | Pass | U-ob3 `test_mandatory_fields`; CONF |
| R-7.2-02 | Pass | U-ob3 `test_only_disclosed_evidence_and_expiry` |
| R-7.3-01 | Pass | ADR-0002 (`eddsa-rdfc-2022`); CONF |
| R-7.3-02 | Pass | CONF: DCC verifier-core, an independent implementation, verifies every issued credential |
| R-7.3-03 | Pass | W7 `test_did_web_issuer_on_configured_host`; W4 `test_did_web_rotation_keeps_old_credentials_verifiable` |
| R-7.3-04 | Pass | W4 `test_did_web_rotation_keeps_old_credentials_verifiable` |
| R-7.3-05 | Pass | SEED `test_signer_holds_encrypted_key_only`; W8-SEC `test_no_canvas_token_or_secret_in_any_api_response`; U-settings |
| R-7.3-06 | Pass | W7 `test_institution_configuration` |
| R-7.4 | Pass | W4 `test_unapproved_issuer_cannot_issue`; W7 `test_issuer_needs_explicit_authority_before_it_can_be_used` |
| R-7.5-01 | Pass | U-ob3 `test_recipient_is_salted_hash_without_email_or_name`, `test_salts_are_fresh_per_credential` |
| R-7.5-02 | Pass | SEED `test_seed_content`; MIG `test_schema_matches_models` |
| R-7.5-03 | Pass | [students/README.md](../students/README.md), [wallets.md](../students/wallets.md) |
| R-7.6-01 | Pass | E8; W4 `test_status_list_credential_is_signed_and_independently_verifiable`; U-bitstring |
| R-7.6-02 | Pass | W4 `test_expired`, `test_tampered_is_invalid`, `test_status_infrastructure_failure_is_unable_to_verify`, `test_downloaded_copy_is_recognised_as_revoked`; E7 |
| R-7.6-03 | Pass | W4 `test_revocation_requires_a_reason`; W7 `test_scenario_8_authorised_admin_revokes`; IMM `test_issued_credential_cannot_be_deleted` |
| R-7.6-04 | Pass | E8; W4 `test_downloaded_copy_is_recognised_as_revoked`; CONF (revoked copy fails as expected) |
| R-7.7-01 | Pass | CONF (DCC verifier-core uses only public contexts and the DID document) |
| R-7.7-02 | Pass | W4 `test_did_web_rotation_keeps_old_credentials_verifiable`; backup/restore drill re-verifies credentials after restore |
| R-7.7-03 | Pass | [preserving-verification.md](../administration/preserving-verification.md) |
| R-8.1 | Pass | E2; FE "groups earned credentials by course and shows status and privacy" |
| R-8.2 | Pass | E4; U-expected_outcomes; FE "shows a student what is confirmed and what is pending" |
| R-8.3 | Pass | E6; FE "groups earned credentials by course and shows status and privacy" |
| R-8.4-01 | Pass | E6, E11; W6 `test_sharing_is_off_by_default_opaque_and_owner_only` |
| R-8.4-02 | Pass | W6 `test_public_check_page_and_robots`, `test_sharing_is_off_by_default_opaque_and_owner_only` |
| R-9.1 | Partial | Signed download, student-controlled URL, human page, copyable details and independent verification pass (E6, E7, E11, CONF). Import into a named wallet waits for the verification domain, because wallets need a public HTTPS issuer (Gary's decision to choose the domain later). [wallets.md](../students/wallets.md) documents it |
| R-9.2 | Pass | CONF (two independent implementations); [wallets.md](../students/wallets.md) |
| R-9.3 | Pass | E11; W6 `test_scenario_11_linkedin_gets_certification_fields_and_a_working_url` |
| R-9.4 | Pass | W6 `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data`, `test_sharing_is_off_by_default_opaque_and_owner_only` (128-bit ids) |
| R-9.5 | Pass | E9; FE "explains how to keep credentials after leaving" |

## §10–13 Administration, education, data and API

| ID | Status | Evidence |
|---|---|---|
| R-10.1 | Pass | W7 `test_institution_configuration`, `test_did_web_issuer_on_configured_host` |
| R-10.2 | Pass | W7 `test_issuer_needs_explicit_authority_before_it_can_be_used`, `test_department_admin_scope_for_issuers`; FE "authorises an issuer only with a recorded basis of authority" |
| R-10.3 | Pass | W7 `test_policy_configuration`, `test_departments_that_may_not_issue` |
| R-10.4 | Pass | W7 `test_templates_prefill_new_badges` |
| R-10.5 | Pass | W7 `test_scenario_8_authorised_admin_revokes` (records, summary, CSV), `test_reconciliation_of_awards_not_issued` |
| R-10.6 | Pass | W7 `test_scenario_8_authorised_admin_revokes` (actor, action, resource, time; no learner names); W8-ACT (activation and export audited); IMM `test_audit_events_append_only` |
| R-11.1 | Pass | W5 `test_completion_badge_cannot_claim_competency` |
| R-11.2 | Pass | W5 `test_credit_wording_needs_reviewer_approval` |
| R-11.3 | Pass | SEED `test_seed_counts`, `test_seed_content`, `test_seed_is_idempotent` (data, not code) |
| R-11.4 | Pass | U-ob3 `test_only_disclosed_evidence_and_expiry` |
| R-11.5 | Pass | W5 `test_reject_returns_to_draft_and_review_checks`; FE "lets a reviewer approve only after every checklist point" |
| R-12.1 | Pass | MIG `test_schema_matches_models`, `test_downgrade_to_base_and_upgrade_again` |
| R-12.2 | Pass | U-ids; MIG `test_schema_matches_models` |
| R-12.3 | Pass | IMM (6 tests) |
| R-12.4 | Pass | MIG `test_schema_matches_models`; TEN `test_composite_fk_blocks_cross_tenant_reference` |
| R-12.5 | Pass | W7 `test_personal_data_export_and_erasure_are_separate_from_revocation`, `test_retention_purges_expired_data_but_keeps_credentials`; [erasure.md](../administration/erasure.md) |
| R-13-01 | Pass | U-app `test_openapi_snapshot_is_current`; [openapi.json](../api/openapi.json) |
| R-13-02 | Pass | ADR-0014 (OB 3.0 API not implemented; nothing invented) |
| R-13.1 | Partial | OpenAPI, validation, authorisation, tenant isolation, structured errors, correlation ids and audit pass (U-app `test_unauthenticated_is_problem_json_with_request_id`, `test_invalid_request_id_is_replaced`; W8-SEC). Idempotency is by domain keys, not an `Idempotency-Key` header (E3). Cursor paging is on achievements only. General rate limiting is at the reverse proxy (release condition 1); in-app, refresh is limited per course. Property-based API fuzzing (schemathesis) was not run; W8-SEC covers malformed input by hand |
| R-13.1-02 | Pass | W8-SEC `test_every_api_route_refuses_anonymous_callers`; W6 `test_public_check_page_and_robots` |

## §14–15 Accessibility, privacy and security

| ID | Status | Evidence |
|---|---|---|
| R-14.2 | Partial | A11Y: axe (WCAG 2.2 A and AA rules) on every signed-in screen, keyboard, screen-reader structure, 320px reflow and reduced motion, on desktop and phone. A manual pass with NVDA or VoiceOver still needs a person ([accessibility.md](accessibility.md)) |
| R-14.2-02 | Partial | As R-14.2: the automated WCAG 2.2 AA checks pass; the manual review is outstanding |
| R-14.3/4 | Pass | E1 and E2 step counts in [e2e.md](e2e.md); RC |
| R-14.5 | Pass | Each designed error state has a test, spread across suites rather than one E-ERR suite: Canvas unavailable (W5 `test_stale_or_failed_canvas_data_never_issues`), mark not released (E4), refresh refused (W8-ACT, FE), signer outage (E12), revoked (E8), unable to verify (W4 `test_status_infrastructure_failure_is_unable_to_verify`), not shared (W6 `test_sharing_is_off_by_default_opaque_and_owner_only`), not authorised (E10), development sign-in unavailable (FE "explains when development sign-in is unavailable") |
| R-15.1 | Pass | [dpia-notes.md](../privacy/dpia-notes.md) |
| R-15.2 | Pass | [dpia-notes.md §4](../privacy/dpia-notes.md#4-privacy-principles-152-and-how-they-are-met); U-ob3; W6 privacy tests; TEN |
| R-15.3 | Pass | W8-SEC (13 tests); [security.md](security.md); W3-CAN `test_oauth_flow_stores_encrypted_tokens_and_never_returns_them` |
| R-15.4 | Pass | [threat-model.md](../security/threat-model.md): all 15 threats, each with controls and named tests |
| R-15.5 | Pass | W4 `test_key_compromise_procedure`; [key-compromise.md](../security/key-compromise.md) |

## §16–22 Verification, jobs, deployment, testing and process

| ID | Status | Evidence |
|---|---|---|
| R-16.1 | Pass | W4 verification tests; CONF |
| R-16.2 | Pass | W4 `test_status_infrastructure_failure_is_unable_to_verify`, `test_expired`, `test_tampered_is_invalid`; E7, E8 |
| R-16.3 | Pass | W6 `test_scenario_7_external_verifier_reports_valid_then_revoked`, `test_public_check_page_and_robots`; FE "stops sharing without revoking" |
| R-17 | Pass | `integration/test_jobs.py` `test_worker_runs_a_deferred_job`; W5-JOBS; W8-WRK |
| R-17.1 | Pass | W5 `test_failed_jobs_are_visible_and_retryable_per_tenant`; W8-WRK `test_worker_queues_publication_when_the_first_one_fails`; W5 `test_stale_or_failed_canvas_data_never_issues` |
| R-17.2 | Pass | E12; W4 `test_signer_outage_is_transient`, `test_interrupted_issuance_recovers_without_duplicates`; W7 `test_reconciliation_of_awards_not_issued` |
| R-18.1 | Pass | CI licence allowlist (ADR-0018); `LICENSE` (AGPL-3.0-or-later) |
| R-18.2 | Pass | Repository layout per [architecture.md §9](../architecture/architecture.md#9-repository-layout) |
| R-18.3 | Pass | CI "Docker Compose smoke test" from a clean checkout; [demo.md](../demo.md) |
| R-18.3-02 | Pass | SEED `test_production_refuses_active_dev_key`, `test_seed_refuses_production`; U-settings |
| R-18.4 | Pass | [production.md](../deployment/production.md) covers all 13 topics |
| R-18.5 | Pass | Compose stack runs offline; [dpia-notes.md §7](../privacy/dpia-notes.md#7-international-transfers) |
| R-19.1–19.3 | Pass | CI jobs Backend, Frontend, Signer, Playwright |
| R-19.4 | Pass | CONF; [conformance.md](conformance.md) (not certified, and says so) |
| R-19.5 | Partial | As R-14.2 (manual screen-reader pass outstanding) |
| R-19.6 | Pass | [security.md](security.md); [dependency-scan.md](dependency-scan.md); W8-SEC; TEN. The pre-production review checklist is in the [security guide](../security/security-guide.md#pre-production-security-review); an external penetration test is recommended (release condition 4) |
| R-20 | Pass (deviation) | Each phase shipped code, tests and docs. Phase reports are the delivery notes (`docs/architecture/w5-delivery.md` to `w7-delivery.md`) and the W8 reports in `docs/reports/`, not `phase-N.md` files |
| R-22.1–22.15 | Pass | [dod.md](dod.md) |
| R-21 | Pass | Extension points exist: `LmsAdapter`, the rule-type registry, OB3 `alignment`, and ADR-0014 for wallet transport |

## Release conditions

None of these is a code defect. Each needs a decision or a person outside the code.

| # | Condition | Rows | Owner |
|---|---|---|---|
| 1 | Rate limiting at the reverse proxy, as in the [security guide](../security/security-guide.md#network) | R-13.1 | Operator, before public go-live |
| 2 | Manual screen-reader pass (NVDA or VoiceOver) on the student and lecturer journeys | R-14.2, R-14.2-02, R-19.5 | The university's accessibility team, before go-live |
| 3 | Choose the verification domain. That unlocks real `did:web` issuance and wallet import | R-9.1, R-2.4-12 | Gary / the university, before the pilot |
| 4 | Confirm NRPS against a hosted Canvas (the local Canvas has a port bug) | R-4.1-01, R-4.3-06 | Pilot setup |

Also recommended, not required by a MUST row: an independent penetration test (R-19.6), and
holding `SIGNER_KEK` in a KMS or HSM instead of an environment variable
([security.md](security.md#open-items-release-conditions-not-code-defects)).
