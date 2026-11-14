# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Colleague review set per faculty, department or service and per badge (migration 0009):
  review modes "required", "author decides" and "not required", inherited down the org tree;
  self-approval and second approval of manual awards per area; a **Badge reviewer** role for
  named colleagues; a list of badges published without review. Badges claiming assessed
  proficiency or using credit wording always need review. The institution can stop areas
  relaxing its settings.
- Award a badge to a list of student ID numbers or emails, with a preview of who matches before
  anything is awarded (`POST /api/v1/awards/bulk`). Student ID numbers are read from launches
  (`canvas_user_sis_id=$Person.sourcedId` custom field or `lis.person_sourcedid`) and the
  Names and Roles roster.
- Badge teams for shared courses (migration 0010): with a course's badge teams on, each badge is
  edited and awarded only by its owner, its named team (editors or awarders) and administrators
  over the course.
- Lighter syncing for staff-awarded courses: a course whose live badges read no Canvas progress
  gets a roster refresh every six hours instead of a full sync every 30 minutes, and is never
  marked stale on the data freshness page.
- Ready-made templates for badges outside modules (volunteering hours, workshop attendance,
  event participation, CPD activity): **Add ready-made templates** on the templates page
  (`POST /api/v1/admin/templates/starters`).
- Authors can start a badge from a badge template in the create wizard ("Start from a badge
  template"). The template fills in the steps, and the wizard asks the author to replace any
  placeholder text in [square brackets] before moving on.
- Org units can be a **service** (a library, careers service), alongside faculty, department and
  programme (migration 0011).
- Link chosen Canvas sub-accounts to areas (migration 0012): administrators read the
  sub-account tree from Canvas, tick the ones that should be areas, and each becomes an area
  nested as in Canvas. Courses in a linked sub-account join its area, now and on first launch
  (new custom field `canvas_account_id=$Canvas.account.id`). Unticked sub-accounts are ignored
  and courses already placed are never moved
  (`GET /api/v1/admin/canvas-accounts`, `POST …/refresh`, `POST …/link`, `DELETE …/{id}/link`).

### Changed
- Usability fixes from the 14 Nov 2026 review:
  - Award to a list: the badge picker lists only live badges you can award, with their course;
    a character count for the justification; the preview says up front when a second member of
    staff must confirm; unmatched entries offer **Refresh the course from Canvas** for students
    who joined today; results are announced to screen readers.
  - Badge teams: switching on asks for confirmation and explains the effect; administrators can
    switch teams off from the course or from **Courses** in Departments and roles
    (`badge_teams` in `/api/v1/admin/courses`).
  - A badge's owner, or an administrator, can hand a badge to another member of course staff
    (`PUT /api/v1/achievements/{id}/owner`); the old owner stays on the team as an editor.
  - Team tab: colleagues without a name no longer show as an internal id, and removing someone
    asks first.
  - Colleague review by area says when a setting is saved; **Badges published without review**
    says so when there are none.
  - `GET /api/v1/achievements?awardable=true`, and `course_title` and `can_award` on badge lists.
- "Badges published without review" uses each live version's latest approval, and includes
  live badges with a new draft in progress.
- An author's explicit request for a colleague's review is honoured where review is not required.
- List awards check staff rights, the live version and second approval once per list rather than
  once per learner.
- A student number linked by a roster sync at the same moment no longer fails a launch.
- Staff wording is neutral, so it suits librarians and service staff as well as lecturers: the
  course role shows as **Course staff**, and requirements read "Confirmation by course staff".
- The switch-on text explains that staff-awarded courses only refresh their class list every
  six hours; publishing a manual badge points to the Awards page; the templates page names
  the fields a template fills in plain words.
- The data freshness list leaves out courses that are switched off.

### Security
- Fixes from the 14 Nov 2026 review of the extracurricular features
  (https://claude.ai/artifact/M8kJDBBuTNBtJyzs4PDUeF):
  - Award to a list matches entries only against the badge's course's students. Anyone else
    reads as "not found", with no name or id, so the preview can no longer be used to look up
    who an email or student number belongs to across the institution.
  - Badge teams also govern revoking and revocation requests: in a course with teams on, course
    staff act only on credentials of badges whose team they are on.
  - With badge teams on, a badge's owner needs to still be staff in the course to award it.
  - The awards queue applies the badge-team rule in SQL, so other teams' awards no longer use up
    the page.
  - Retiring or destroying a key in the signer is retried while the signer is unreachable
    (previously the job gave up at once, so a compromised key could survive a signer outage).

- Fixes from the 13 Nov 2026 code and security review (docs/reports/code-review-2026-11-13.md):
  - The signer checks its shared secret on the route it matched, so percent-encoded or
    absolute-form paths (`/%761/sign`) no longer skip authentication (S1).
  - The public verifier only fetches DID documents and status lists from public internet
    addresses, re-checks HTTPS on every redirect and no longer reports connection error detail (S2).
  - A credential waiting for its signature is never signed once its award has been rejected or
    the learner erased; erasure cancels such rows (C1).
  - Courses that are not switched on are never read from Canvas, so a student's refresh cannot
    evaluate or award there (C2).
  - Compromising a key that was already rotated out re-signs the issuer's status lists with the
    current key (C3).
  - The signer retires or destroys a key only after the database change commits, with a queued
    job as the durable retry (C4).
  - The verification host is operator-only: it is set with `oc admin set-verification-host`, it
    is read-only on the institution settings page, and it can belong to only one institution
    (unique, migration 0008). This service only vouches for a did:web issuer under its own
    institution's host (S3).
  - After any number of failed Canvas reads in a row, the last good snapshot is still treated as
    unavailable, so nothing is awarded from stale data (C5).
  - A rejected manual award no longer blocks a corrected one for the same learner (C6).
  - The awards list is filtered by the caller's courses in the database, so other courses'
    older awards can no longer leave a lecturer's "to confirm" list empty (C7).
  - Destroyed keys are recorded (`destroyed_at`, audited, shown in the key list) and the nightly
    job no longer destroys the same retired keys again (C8).
  - Award decisions are built in one place (`issuance.decisions`); eligibility no longer keeps
    its own copy of the idempotency logic (C9).

### Added
- Release hardening (W8, spec Phase 8): course activation ("Switch on micro-credentials for this
  course", with an initial Canvas read and an institution policy for first launch); course award
  history, CSV export and in-app revocation requests for lecturers; honest refresh messages that
  show the last successful Canvas read; security response headers; the issuing job publishes a
  new status list itself, so fresh credentials verify at once; security, cross-tenant and
  malicious-input test suites; Playwright E1–E12 and WCAG 2.2 AA checks in CI; a destructive
  backup and restore drill in CI; threat model, security guide, production, lecturer, API,
  demonstration and DPIA guides; conformance, accessibility, security, dependency, end-to-end,
  traceability-evidence and Definition of Done reports.
- Student collection and portability (W6, spec Phase 6): "My credentials" across courses,
  credential detail with live verification, signed download, student-controlled public links
  (off by default, 128-bit random ids, preview of exactly what becomes public, withdraw without
  revoking), server-rendered public verification page with learner-free Open Graph tags, a
  "Check a credential" upload page, public badge images, LinkedIn Add-to-Profile values and
  prefilled link, student and wallet guides, and `noindex` on every response.
- Phase 1 foundation (W2): repository layout, AGPL-3.0-or-later licence and project docs.
- Backend: FastAPI app, settings with production guards, problem+json errors, request ids,
  structured logs, health/readiness probes, development-only login.
- PostgreSQL schema for the spec §12 domain (38 tables) with Alembic migrations, row-level
  security on every tenant table, composite tenant foreign keys, immutability triggers for
  published versions, issued credentials and audit events, and a signer-only `keys` schema.
- Background worker on procrastinate (Postgres-backed queue) with an LTI state purge job.
- Signer service skeleton: Ed25519 key generation (did:key) with envelope-encrypted storage.
  Signing and verification are not implemented yet (W4) and return 501.
- React + TypeScript + Instructure UI frontend shell with development sign-in.
- Demo data: Academic Skills Passport (9 badges in 3 themes) and 12 synthetic learners with
  LMS snapshots and eligibility results.
- Docker Compose environment, CI (lint, types, Pytest, Vitest, dependency and licence audit,
  compose smoke test).
- Architecture, traceability matrix, standards check and ADRs (W1).
