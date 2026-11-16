# Definition of Done (spec §22)

Date: 13 November 2026. Each outcome of spec §22 with the evidence that demonstrates it. Row-level
detail is in [rtm-evidence.md](rtm-evidence.md). As §22 requires, nothing here is marked done
because a screen exists: each line names a passing test or a recorded run.

| § | Outcome | Status | Demonstrated by |
|---|---|---|---|
| 22.1 | Institutional installation | Done | The [Canvas install guide](../integrations/canvas.md) was followed on a local Canvas, and the app ran there end to end over HTTPS ([e2e.md §2](e2e.md#2-real-canvas-over-https)). The gap that run found (no way to switch a course on) is fixed and tested. [production.md](../deployment/production.md) covers production. |
| 22.2 | Lecturer authoring | Done | E1; `test_scenario_1_lecturer_creates_previews_and_publishes`; the real-Canvas run (wizard with a real Canvas module, review by a second person, publish); the [lecturer guide](../lecturers/README.md) needs no technical knowledge |
| 22.3 | Student discovery | Done | E2; frontend "shows a student what is confirmed and what is pending" |
| 22.4 | Progress tracking | Done | E2, E4; Canvas adapter unit tests; the real-Canvas run (Canvas marked the module complete, and Course progress showed it after a refresh) |
| 22.5 | Automatic awards | Done | E2, E3; `test_scenario_2_completion_records_eligibility_and_requests_issuance`; the real-Canvas run issued a credential automatically |
| 22.6 | Manual awards | Done | E5; `test_scenario_5_manual_award_with_justification`, `test_second_approval_policy_for_manual_awards` |
| 22.7 | Genuine Open Badges 3.0 | Done | [conformance.md](conformance.md): in CI, every credential the stack issues passes the 1EdTech inspector and DCC verifier-core (signature, schema, status list). **Not certified**, and the report says so. |
| 22.8 | Export and portability | Done | E6, E9; DCC verifier-core is the independent verification workflow; [wallets.md](../students/wallets.md) documents wallet and host handling. Import into a named wallet waits for the verification domain (release condition 3 in [rtm-evidence.md](rtm-evidence.md#release-conditions)). |
| 22.9 | External sharing | Done | E7, E11; the real-Canvas run (shared page showed "Verified" without the holder's name) |
| 22.10 | LinkedIn | Done | E11; `test_scenario_11_linkedin_gets_certification_fields_and_a_working_url` |
| 22.11 | Institutional administration | Done | E8; `test_governance.py` (14 tests: issuers, policies, delegation, templates, revocation, reports, audit, retention, erasure, reconciliation); W8 course activation policy |
| 22.12 | Security and privacy | Done | [security.md](security.md) (authorisation, authentication, cross-tenant, malicious input, secrets, headers, dependencies); [threat-model.md](../security/threat-model.md); E10; privacy tests and [dpia-notes.md](../privacy/dpia-notes.md). Private by default: no name or email in credentials, sharing off until the learner turns it on. |
| 22.13 | Accessibility | Done, with a recorded open item | [accessibility.md](accessibility.md): axe WCAG 2.2 A/AA on every screen, keyboard, structure, reflow and reduced motion, on desktop and phone. Findings are recorded; a manual screen-reader pass is the recorded unresolved item. |
| 22.14 | Fully open source | Done | AGPL-3.0-or-later (`LICENSE`); a licence allowlist in CI; source, Alembic migrations, configuration and operations docs in the repository; no paid or mandatory cloud dependencies |
| 22.15 | Reproducibility | Done | [demo.md](../demo.md) from a clean clone: CI runs the same `docker compose up` and `scripts/smoke.sh` on every change, and the Playwright job reproduces the walk-through |

## Release conditions

Four items sit outside the code and are listed in [rtm-evidence.md](rtm-evidence.md#release-conditions):
rate limiting at the reverse proxy, a manual screen-reader pass, choosing the verification
domain, and confirming NRPS on a hosted Canvas. An independent penetration test and a KMS for
`SIGNER_KEK` are recommended.
