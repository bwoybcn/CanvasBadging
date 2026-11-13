# W5 delivery notes: badge authoring, award rules and eligibility

Scope: spec Phases 3 and 4 (§20), with §5 (authoring), §6 (rules engine and awarding policies), §11 (educational metadata) and §17 (background jobs). Canvas is reached only through the `LmsAdapter` protocol; every test in this workstream runs against `FakeLmsAdapter`, not a real Canvas.

## What is built

| Area | Where |
|---|---|
| Draft fields, categories, completion vs competency, credit-wording check | `backend/opencredential/authoring/service.py` |
| Lifecycle DRAFT → IN_REVIEW → APPROVED → PUBLISHED → ARCHIVED, reject to draft, new version | `authoring/service.py`, `/api/v1/achievements/*` |
| Immutable published versions (DB trigger on frozen rule sets) | migration `20261113_0004` |
| Non-issued preview (no proof, placeholder id, "PREVIEW: NOT ISSUED AND NOT VERIFIABLE") | `authoring/preview.py` |
| SVG allow-list sanitiser, PNG chunk filter, size limits, alt text | `authoring/artwork.py` |
| Four original CC0 templates (roundel, shield, hexagon, ribbon) | `authoring/artwork_templates/` |
| Rules engine, types A–F, ALL/ANY with one level of grouping, three-valued (met / not met / unknown), explanation codes, inputs hash | `backend/opencredential/rules/` |
| Sync of modules, progress, assignments and submissions into snapshots; source change detection | `backend/opencredential/sync/` |
| Eligibility recording, awarding policies (automatic, lecturer-confirmed, manual with justification), idempotent decisions | `backend/opencredential/eligibility/` |
| Procrastinate tasks: sync, evaluate course/learner, scheduled sync, stalled-job recovery; failed-job view and retry | `backend/opencredential/jobs/`, `/api/v1/admin/jobs` |
| Institution awarding policy (Gary's decision: per-badge automatic or lecturer-confirmed, admin default, optional force) | `/api/v1/institutions/current/policy`, ADR-0017 |
| Screens: Create micro-credential wizard, badge page with review and preview, review queue, awards to confirm and manual award, course progress, student "My badges", awarding policy | `frontend/src/pages/` |

## Spec §19.3 scenarios 1–5 (against the fake LMS)

| Scenario | Test |
|---|---|
| 1. Lecturer creates, previews, submits, gets approval and publishes | `test_scenario_1_lecturer_creates_previews_and_publishes` |
| 2. Completion is recorded and issuance requested | `test_scenario_2_completion_records_eligibility_and_requests_issuance` |
| 3. Duplicate events create nothing new | `test_scenario_3_duplicate_events_create_nothing_new` |
| 4. Missing or unreleased grade stays pending | `test_scenario_4_missing_or_unreleased_grade_stays_pending` |
| 5. Manual award with justification | `test_scenario_5_manual_award_with_justification` |

All in `backend/tests/integration/test_w5_scenarios.py`. The same file covers rejection, competency mismatch, credit wording, rule source checks, issuer delegation, malicious SVG, stale and failed Canvas data, Canvas changes, second approval, Rule E, failed-job retry with tenant isolation and admin-only policy. `test_w5_jobs_and_seed.py` runs a real procrastinate worker over sync and evaluation jobs, and checks that the engine reproduces all 108 seeded golden outcomes. `backend/tests/unit/test_rules_engine.py` holds the U-RULES-* cases.

## Hand-off contracts

**W4 (issuance).** When a decision becomes `ready`, W5 defers `oc:issue_credential` on queue `issuance` with kwargs `decision_id`, `institution_id`, `subject_type="award_decision"`, `subject_id` and queueing lock `issue:{decision_id}`. The task must be idempotent on `decision_id`, set the decision to `issued`, and copy `award_decisions.evidence` (only items with `public: true`) into the credential's evidence. Until W4 registers the task, these jobs wait in the queue.

**W3 (Canvas).** Implement `integrations.base.LmsAdapter` (`list_modules`, `list_module_progress`, `list_assignments`, `list_submissions`) and call `integrations.registry.register(factory)`. Raise `LmsTransientError` for 429/5xx/timeouts (the job retries with backoff), `LmsPermissionError` or `LmsNotFound` otherwise. Canvas types must stay inside `integrations.canvas` (import-linter enforces this). Students are matched by `ExternalIdentity(kind="canvas_user_id")`.

## Still to verify against real Canvas

These cannot be proven with fakes and stay open until W3 runs against the local Canvas sandbox:

1. Phase 4 exit condition: real Canvas activity (module completion, a released mark) producing an eligibility record end to end.
2. `posted_at` semantics: that Canvas sets it only when a mark is released to the student under each grade-posting policy, so "released" means what we assume (ADR-0010).
3. Module requirement behaviour: modules without requirements, "complete one item" requirements, locked or unpublished modules, and progress for students who joined late.
4. Roster: the learner list currently comes from memberships; NRPS (LTI names and roles) is W3's job.
5. API load and pagination for large courses, and Canvas rate limiting under the 30-minute schedule.
6. Excused, missing and late submissions as Canvas actually reports them.

## Known gaps in this workstream

- SVG artwork is not rendered to PNG; credentials embed the SVG. Adding a rasteriser (for example cairosvg) needs a dependency decision.
- The public, unauthenticated artwork route (for verification pages and wallets) belongs to W4/W6.
- Learner names in the seed and tests are synthetic.
- Screens are tested with Vitest; the Playwright E1/E2 journeys and the axe accessibility checks are W8.
- Migration 0002 now freezes its own copy of the tenant table list (it used to import the live list, which would break when later migrations add tables).
