# Backend tests

Find the tests for a feature here. Files are named after what they test, not after the stage of
the build that added them. Every test stands on its own: the suite runs in a different, shuffled
order each time (`pytest-randomly`), so a test that only passes after another one fails quickly.

```bash
cd backend
uv run pytest                                 # everything, in a shuffled order
uv run pytest tests/unit                      # no database needed
uv run pytest tests/integration/test_governance.py
uv run pytest -p randomly --randomly-seed=1234   # repeat the order of a failed run
uv run pytest -p no:randomly                  # file order, for stepping through by hand
```

A failed run prints `Using --randomly-seed=…` at the top. Pass that number back to get the same
order again. What the integration tests need (PostgreSQL and the signer) is in
[docs/development/local-setup.md](../../docs/development/local-setup.md).

## Where each feature is tested

`tests/unit` needs nothing running. `tests/integration` uses a real PostgreSQL database, and the
files marked "signer" use the real signer too.

| Feature | Files |
|---|---|
| Opening Badges from Canvas (LTI 1.3 launch, every refusal) | `integration/test_lti_launch.py`, `unit/test_platform_keys.py`, `unit/test_sis_claims.py`; in a real browser, `tests/end_to_end/specs/canvas-sign-in.spec.ts` |
| Sessions | `unit/test_sessions.py`, `integration/test_session_renewal.py` |
| Canvas API sign-in, tokens and the class list | `integration/test_canvas_oauth_and_class_list.py`, `unit/test_canvas_adapter.py` |
| Canvas sub-accounts linked to areas | `integration/test_canvas_accounts.py` |
| Reading progress from Canvas, and stopping when a course ends | `integration/test_course_end_and_minimal_sync.py`, `integration/test_lighter_sync.py` |
| Switching Badges on for a course | `integration/test_course_activation.py` |
| Creating, reviewing and publishing a badge; awards from Canvas data and by hand (scenarios 1 to 5) | `integration/test_authoring_and_award_scenarios.py` |
| Award rules | `unit/test_rules_engine.py`, `unit/test_expected_outcomes.py` |
| Review by a colleague, badge teams, two people editing one draft | `integration/test_area_review.py`, `integration/test_badge_teams.py`, `integration/test_draft_edit_conflict.py` |
| Form errors, restoring an archived badge | `integration/test_form_errors.py`, `integration/test_restore_archived.py` |
| Awarding to a list, confirming all waiting awards | `integration/test_bulk_award.py`, `integration/test_confirm_all.py` |
| Canvas's Test Student | `integration/test_test_student.py` |
| Signing, Open Badges 3.0 content, revocation, checking a badge (signer) | `integration/test_issuance_and_verification.py`, `unit/test_ob3.py`, `unit/test_bitstring.py`, `unit/test_verifier_status.py`, `unit/test_verification_sources.py` |
| Cancelled awards, key rotation and key compromise (signer) | `integration/test_cancelled_awards_and_key_changes.py` |
| What students do with a badge: download, share, LinkedIn (signer) | `integration/test_sharing_and_export.py` |
| Certificate PDF and badge image | `integration/test_certificate_download.py`, `unit/test_certificate.py`, `unit/test_artwork.py`, `unit/test_filenames.py` |
| Administration: issuers, roles, policies, templates, reports, audit, retention, erasure | `integration/test_governance.py`, `integration/test_setup_checklist.py` |
| Security: every route against anonymous callers, students and other institutions; hostile input | `integration/test_security.py`, `integration/test_tenant_isolation.py`, `unit/test_ratelimit.py`, `unit/test_secretbox.py` |
| Records that must never change | `integration/test_immutability.py` |
| Background jobs and the worker | `integration/test_jobs.py`, `integration/test_worker_issuance.py`, `integration/test_worker_sync_and_demo_outcomes.py`, `integration/test_job_health.py`, `unit/test_job_retries.py` |
| Demo data and development sign-in | `integration/test_seed_and_api.py` |
| Database migrations | `integration/test_migrations.py` |
| Settings, startup checks, command line and scripts | `unit/test_settings.py`, `unit/test_app.py`, `unit/test_scripts_and_cli.py`, `unit/test_ids.py` |
| Regressions from the code review of 13 November 2026 | `integration/test_code_review_regressions.py` |

## Shared helpers

| File | What it gives a test |
|---|---|
| `conftest.py` | A fresh, migrated test database for the run |
| `integration/world.py` | `build_world()`: one institution with a course, staff, three students and a stand-in for Canvas |
| `integration/issuance_factory.py` | `build_tenant()`: an institution with an issuer and a real signing key |
| `integration/lti_platform.py` | A stand-in Canvas that signs LTI launches |
| `independent/verifier.py` | A second implementation of the proof check, sharing no code with the signer |

## Writing a test that stands alone

- Build what the test needs in the test or its fixture. Do not count on rows another test left.
- Other tests share the database. Look rows up by the institution or id your test made, never
  "the only row in the table".
- When two things happen in one run they can carry the same time. Name the one you mean
  instead of taking "the latest".

## Other suites

| Suite | Where |
|---|---|
| Signer | `signer/test` (`npm test` in `signer/`) |
| Screens | `frontend/src/**/*.test.tsx` (`npm test` in `frontend/`) |
| Whole journeys in a browser, and accessibility | [tests/end_to_end](../../tests/end_to_end/README.md) |
| Open Badges checks by outside verifiers | [tests/conformance](../../tests/conformance/README.md) |
