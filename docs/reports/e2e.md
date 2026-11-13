# End-to-end test report (spec §19.3)

This report covers two runs:

1. **Automated:** the twelve §19.3 scenarios (E1–E12) run with Playwright against the whole
   stack on every pull request.
2. **Real Canvas:** a manual end-to-end run, scripted with Playwright, against a real Canvas
   install over HTTPS.

## 1. Automated scenarios E1–E12

**Where:** `tests/end_to_end/specs/scenarios.spec.ts`, CI job "End-to-end scenarios and
accessibility (Playwright)". Results are uploaded as the `e2e-results` artefact.

**Stack under test:** PostgreSQL 16, migrations, the Node signer, the demo seed, the API serving
the built SPA, and the real procrastinate worker. The scenarios use the demo institution, whose
course reads from the fake LMS adapter (the passport demo data set). Everything else is real:
LTI-style bearer sessions, signing, status lists, the worker, the public verifier.

**Result (local run on a freshly seeded database, 13 Nov 2026):** 12 of 12 passed. The CI run for
the final commit of the pull request is the record of evidence.

| # | Scenario | What the test does | Result |
|---|---|---|---|
| E1 | Lecturer creates a badge | Goes through all seven steps of the wizard, saves a draft, previews (marked "not issued"), submits; a reviewer ticks the checklist and approves; the lecturer publishes | Pass |
| E2 | Student completes requirements | A completed module leads, through sync, evaluation and the worker, to an issued credential the student can see | Pass |
| E3 | Duplicate event | Processes the same completion three more times; still exactly one credential | Pass |
| E4 | Incomplete grade | A missing or unreleased mark stays "pending" and issues nothing | Pass |
| E5 | Manual award | The lecturer awards with a justification; the decision is recorded and issued | Pass |
| E6 | Student export | The download is OB 3.0 (contexts, types, proof) and the API verifier says `verified` | Pass |
| E7 | External verification | Someone with no account uploads the file on `/verify` and sees "Verified" | Pass |
| E8 | Revocation | An administrator revokes with a reason; the file downloaded earlier now verifies as revoked | Pass |
| E9 | Canvas account closure | After the learner's account is closed, the exported file still verifies | Pass |
| E10 | Unauthorised access | Another learner's credential gives 404 and leaks nothing | Pass |
| E11 | LinkedIn | The "Add to profile" link carries the certification fields; the public URL works without signing in | Pass |
| E12 | Interrupted issuance | The signer is stopped during issuance and then restarted; the job retries and exactly one credential results | Pass |

### Defects the scenarios found (all fixed in W8)

| Defect | Effect | Fix | Regression test |
|---|---|---|---|
| Inside `oc worker`, every issuance job failed after signing, while queueing the status-list publication (procrastinate refused a second `open()`) | Credentials were signed but the job was marked failed. New status lists were not published until the hourly job ran, so new credentials showed "Unable to verify". | `jobs/defer.py` reuses the worker's open app | `test_w8_worker.py` |
| A credential in a brand-new status list showed "Unable to verify" for about 10 seconds after issue, because the first publication waited for the delayed job (found by E6 in CI) | A student who downloaded and checked a credential at once was told it could not be verified | The issuing job publishes a new list itself; the queued job is only a fallback | `test_worker_issues_and_publishes_a_new_status_list_at_once`, `test_worker_queues_publication_when_the_first_one_fails` |

## 2. Real Canvas, over HTTPS

**When and where:** 13 November 2026, 16:08 to 16:20 UTC, on the project owner's Windows
machine. The stack ran under `docker compose up -d --build` from branch
`claude/project-thread-droesb` at commit `777a6d6`, with `OC_PUBLIC_BASE_URL=https://localhost:8443`
behind the development Caddy front door. Canvas was the open-source build of 30 April 2026 at
`http://localhost:3000`, course 4 "OpenCredential W3 Test Course". The browser was Microsoft
Edge, headless, driven by Playwright. Caddy's local CA was not trusted, so certificate errors
were ignored for the run.

**Result: pass, end to end.** The one failure (NRPS) is a known Canvas defect on this install and
is expected.

| Step | Result | Evidence |
|---|---|---|
| 1. HTTPS LTI launch for a teacher, a TA and a student: `/lti/login`, then `/lti/launch`, then `/app` with the right name, course and role | Pass. The `SameSite=None; Secure` state cookie was accepted. With the cookie deleted, the platform-storage path (`POST /lti/verify`) also worked. | [teacher-launch-https.png](evidence/real-canvas/teacher-launch-https.png) |
| 2. Author, review and publish against a real Canvas module | Pass. The module "Seminar Skills (E2E)" (Canvas id 22, `must_view`) was synced. The teacher built the badge in the seven-step wizard with a real module requirement and automatic award. The TA (a second institution admin, so not self-approval) approved it, and the teacher published it. The issuer was created and authorised through the admin API (development `did:key`). | [teacher-requirement-real-canvas-module.png](evidence/real-canvas/teacher-requirement-real-canvas-module.png), [ta-approved.png](evidence/real-canvas/ta-approved.png), [teacher-published.png](evidence/real-canvas/teacher-published.png) |
| 3. Completion, then a credential, then "Verified" | Pass. The student viewed the page and Canvas marked module 22 complete. "Refresh from Canvas" ran sync, evaluation (met), issuance and status-list publication in the worker with no errors. Credential `urn:uuid:01a1d5b3-eb2d-7eba-a759-ac870ade9c27` was issued at 16:18:20 UTC and shows as Valid in My credentials. The shared page shows "Verified", without the holder's name. | [student-module-complete-in-canvas.png](evidence/real-canvas/student-module-complete-in-canvas.png), [teacher-refresh-from-canvas.png](evidence/real-canvas/teacher-refresh-from-canvas.png), [student-my-credentials.png](evidence/real-canvas/student-my-credentials.png), [verify-page.png](evidence/real-canvas/verify-page.png) |
| 4. NRPS roster | Expected failure. The token was issued, but Canvas answered `GET /api/lti/courses/4/names_and_roles` with HTTP 500 (`URI::InvalidComponentError`, a port in the domain). OpenCredential recorded `sync.roster_failed code=LMS_TRANSIENT`, kept the existing roster (a partial roster never revokes), and the sync finished `ok`. | Worker log |

### Findings from the real-Canvas run

| # | Finding | Status |
|---|---|---|
| a | There was no way to switch a course on: no endpoint and no button, although the home page told lecturers to "activate the course". Scheduled reconciliation only reads active courses, so a real course would never refresh on its own. | **Fixed in W8.** `POST /api/v1/courses/{id}/activate` and `/deactivate`, a button on the launch page, an initial sync on activation, and the institution policy `course_activation_required` honoured on first launch. Tests: `test_w8_course_activation.py`, frontend "lets a lecturer switch micro-credentials on from the launch page". |
| b | When a refresh was refused as too soon, the message did not say that nothing new had been read from Canvas | **Fixed in W8.** Course progress shows the last successful read and the last attempt. A refused refresh now says the figures come from the earlier read. |
| c | Moving the tool to a new URL (here, to HTTPS at :8443) needed a separate API call to update the deployed tool, because Canvas keeps the old launch URL on the installed tool with no sign of it in the UI | **Documented** in [Canvas install guide, "Changing the tool's address"](../integrations/canvas.md#changing-the-tools-address) |
| d | NRPS returns 500 on Canvas installs whose domain includes a port | Canvas defect, outside OpenCredential. The local roster path copes with it. Production Canvas (Instructure-hosted, no port) is not affected. |

### Not covered by the real-Canvas run

* Grade-based rules (minimum score, release policy) against a real Canvas gradebook: covered by
  E4 and by the W3 adapter tests against recorded Canvas responses, not by a live run.
* NRPS on a Canvas without the port defect: covered by `test_roster_sync_provisions_and_revokes`
  against a recorded response.
* A trusted certificate on a real domain: needs the verification domain (a decision for Gary,
  deferred).
