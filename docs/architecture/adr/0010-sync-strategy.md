# ADR-0010: Synchronisation and "released grade" semantics

Date: 2026-11-13 · Status: Accepted

## Context
Canvas Live Events have no module-completion event. `grade_change` has `muted` and `grading_complete` but no posted flag, and delivery is retried only 3 times. Submissions carry `posted_at` ("posted to the student, or nil").

## Decision
- **Source of truth:** REST polling into snapshot tables. Initial sync on activation, then scheduled every 30 min for courses with published badges (configurable), on-demand refresh (rate-limited), and nightly full reconciliation.
- **Live Events (optional):** if an admin configures an HTTPS subscription (signed JWT, verified against Canvas JWKS), `submission_*`, `grade_change` and `module_*` events only schedule a targeted re-read. They never feed rules directly.
- **Released** = `posted_at` is not null. Score rule `met` also needs `workflow_state = graded`, `grade_matches_current_submission = true`, not excused, `points_possible > 0`.
- **Unknown, not failed:** any fetch error, partial page, permission error or snapshot older than `max_snapshot_age_minutes` makes the affected rule `unknown` with a code, so no issuance happens (spec §4.4, §17.1).
- Changes to source activities (deleted or unpublished module, removed completion requirements, changed points) set `award_rules.source_status` and alert the lecturer. Badges stay published but issuance pauses for affected rules.

## Consequences
Awards can lag Canvas by up to the polling interval (default 30 min), which is acceptable for badges. API load is roughly 1 module call per learner per course per cycle plus 1 submissions call per course. W3 measures this on the sandbox and tunes the defaults.
