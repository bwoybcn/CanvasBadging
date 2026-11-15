# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- A withdrawn badge says so plainly to its holder. The badge page names the issuer, the date and
  the reason category ("Reason: Issued in error."); the staff explanation stays in the record. It
  no longer says "Verification confirms that this credential … has not been revoked" under
  "Revoked", no longer offers to turn on a public link or add the badge to LinkedIn, and says who
  to contact. `GET /api/v1/credentials/{id}` gains `withdrawal`.
- **Stop sharing** asks first, and says that the link stops working everywhere it was given out
  (LinkedIn, a CV, emails) and that sharing again gives a new link.
- A student who opens a staff page by its address (Award badges, Create a badge, Badges, Review
  queue, a course's progress) sees "This page is for course staff" with links to their own
  badges, instead of forms that the server would refuse. Someone with no administrator role
  sees "This page is for administrators" on administration pages, without the administration
  menu. The server's checks are unchanged.
- A new version of a badge can be thrown away. **Discard this version** on the badge page
  (`POST /api/v1/achievements/{id}/discard-version`) removes a version started with **Start a
  new version**, while it is a draft, in review or approved, and leaves the published version
  live and unchanged. It asks first. Before, a new version could only be finished.
- **Download credential file** works for badges with accented names. A title such as "Gŵyl Dewi"
  or "Café" put a non-Latin-1 letter in the download's file name header, so the server failed
  and the button did nothing. Download names are now plain ASCII ("gwyl-dewi-2026-11-15.json")
  for the credential file, certificate and badge image alike, and an error that arrives with no
  words now says "Something went wrong. Please try again." instead of nothing.
- **Award badges › One student** keeps listing a badge while its next version is drafted. It
  asked only for published badges, so **Start a new version** took the badge off the list even
  though its published version stays live; the list award tab already showed it. Both tabs now
  use the same list of badges with a live version.
- Drop-down lists that looked chosen but were not. The badge wizard showed the first course or
  category as if it were selected, then refused the step ("Choose a category."), and left the
  artwork Template box blank after a template was picked. Course, Issuer, Category, Template,
  Module, Assignment and the badge lists on Award badges now show the placeholder until something
  is chosen, and show a saved choice once its list has loaded.
- A student's badge no longer says "Earned" and "Pending" at once. When course staff award a badge
  by hand, its requirements are not all recorded as met, so **Badges in my courses** showed
  "0 of 1 confirmed" and "Awaiting confirmation by course staff" under "Earned". A badge the
  student holds now says "You have this badge. Nothing more is needed from you." instead of the
  requirement list. Requirement lines no longer double their punctuation ("quiz.: Awaiting").
- Screen readers now hear why a form was refused. When **Next** in the badge wizard finds a
  problem, the "Please fix the following" list is announced and takes focus, instead of focus
  staying on Next in silence. Every error message from the server (award forms, admin pages)
  is announced as it appears.
- **Check a credential file** is written for the people who use it, usually an employer. The
  result now opens with a coloured verdict and a plain sentence ("This badge failed its checks…
  Do not rely on it."), names the badge and issuer, warns that those details cannot be trusted
  when the check fails, and folds the technical checks under "Show the individual checks", as a
  shared badge page does. A file that is not a credential gets advice instead of "The request
  body must be the credential JSON". Long signing-key text no longer pushes the page wider than a
  phone screen. Shared badge pages use the same plainer verdict wording.
- A Canvas administrator who opens **Badges** is told how to get set up, instead of seeing only
  "No course role". Canvas roles still grant nothing here (ADR-0013); the home page explains that,
  names the Badges administrators to ask for a role under **Staff roles**, or, when there are
  none yet, says the service operator makes the first one. `GET /api/v1/learners/me` gains
  `canvas_admin_without_access` and `institution_admins` for this, from the launch's Canvas
  institution or system Administrator role.

### Added
- A setup checklist on the Administration overview for institution administrators
  (`GET /api/v1/admin/setup`): Canvas connected, public address set, an area that may issue, an
  issuer created, authorised and delegated. Each step is ticked from the current state, says
  what is there or what to do, and links to its page; the first one left is marked "Do this
  next". The two steps the service operator does say so. It folds away when all six are done.
- A certificate to print: **Download certificate (PDF)** on a student's badge page and in **My
  badges** (`GET /api/v1/credentials/{id}/certificate`). One A4 page with the badge image, the
  student's name (they can leave it off), the badge, who issued it and when, and the credential
  ID. While the badge has a public link, the certificate carries a QR code that opens it; without
  one it says where to check the credential file. The page says it is a copy for printing and
  that the proof is the credential file or the public page. Revoked and suspended badges have no
  certificate.
- **Download badge image** saves the badge picture as a PNG
  (`GET /api/v1/credentials/{id}/image`).
- New backend dependencies: reportlab (PDF) and resvg-py (draws SVG artwork as PNG), and the
  Liberation Sans font (SIL OFL 1.1) bundled for the certificate text.
- **Award all N** confirms every waiting award on the list in one go
  (`POST /api/v1/awards/confirm-all`, up to 500). Each award still gets the fresh Canvas check
  of a single confirm; any that no longer qualify stay on the list and are named with the
  reason. Manual awards awaiting a second approver are never included. The waiting list can be
  narrowed to one badge and now shows up to 500 awards (it stopped at 100).
- The student picker for a single manual award is searched by typing part of a name.
- An archived badge can be restored (`POST /api/v1/achievements/{id}/restore`, **Restore this
  badge** on the badge page). The published version goes live again as it was, so nothing is
  reviewed again; a newer version that was in progress comes back as a draft. Archiving used to
  be permanent.
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
  Reading sub-accounts needs two more API key scopes, `url:GET|/api/v1/accounts` and
  `url:GET|/api/v1/accounts/:account_id/sub_accounts`: existing installs add them to the API
  developer key and reconnect Canvas. The page can link a sub-account to an existing area, shows
  the tree indented, and does not offer the root account. Canvas's internal "Site Admin"
  account is left out.

### Changed
- **Departments and roles** is now four pages in the administration menu: **Faculties and
  departments** (areas and Canvas sub-accounts), **Courses**, **Staff roles** and **Colleague
  review by area**. The menu is ordered the way an institution is set up. The old address opens
  Faculties and departments.
- One vocabulary on every screen, message and user guide: **badge** for what a student earns
  (no more "micro-credential" or "credential"), **student** (no more "learner"), and
  **credential file** only for the signed file that is downloaded or checked. Renamed with it:
  **My credentials** is now **My badges**, the progress page **My badges** is now **Badges in
  my courses**, **Create micro-credential** is **Create a badge**, **Issued credentials** is
  **Issued badges**, **May issue credentials** is **May issue badges**, the public page
  **Check a credential** is **Check a credential file**, and the audit category "Credential
  definitions" is "Badge definitions". API paths, codes and fields are unchanged.
- The Canvas course menu item is now **Badges** (it was "Micro-Credentials"): the generated
  developer-key configuration, `oc lti config` and every message that sends someone back to
  the course menu use the new name. Canvas stores the menu text in the developer key, so an
  existing installation shows the old name until the key is edited once; see "Renaming the
  menu item on an existing installation" in `docs/integrations/canvas.md`.
- "Awards to confirm" is now **Award badges**, with three tabs: **Waiting to confirm** (with a
  count), **One student** and **A list of students**. The tab is kept in the address
  (`/awards?tab=student`, `?tab=list`), and what is typed on one tab survives a look at another.
- Actions that cannot simply be undone now ask first and say what will happen: archiving a
  badge, deleting a draft, removing someone's role, unlinking a Canvas sub-account, removing an
  issuer delegation and switching badge teams off from a course. The first press changes nothing, and focus lands on the way out.
- Form errors name the field and say what to change ("Short description is too long: use up
  to 280 characters") instead of "Request validation failed". A 422's `errors` entries now
  carry the limit that was broken in `limits`.
- Text boxes stop at the length the server accepts, on every form, and show a character count
  (always on short fields, near the limit on long ones).
- Colours are chosen from a colour swatch instead of typed as hex codes: badge artwork in the
  wizard, brand colours in institution settings and the artwork colour of a badge template. A
  code can still be pasted beside the swatch. Brand colours are now checked on the server too.
- The create-badge wizard saves as it goes. The draft is created when the author leaves step 2
  ("About the badge") and saved again on each **Next** or **Back** and on leaving the wizard,
  so a time-out or a closed tab costs at most the step in hand. A line under the buttons says
  when the draft was last saved. Once the draft exists its course, issuer and template are
  fixed.
- Sessions stay alive while someone is working. A session still ends after 30 idle minutes
  (`OC_SESSION_TTL_MINUTES`), but typing or clicking renews it
  (`POST /api/v1/session/renew`) for up to 8 hours after the Canvas launch
  (`OC_SESSION_MAX_MINUTES`, new). When a session does end, every screen now says so in plain
  words and says to open the tool from Canvas again.
- "Areas may set review less strictly" (`areas_may_relax_review`) is now off by default:
  faculties, departments and services can only make review stricter until an institution
  administrator opts in. Institutions that already saved the setting keep their choice.
- Usability fixes from the 14 Nov 2026 review:
  - Award to a list: the badge picker lists only live badges you can award, with their course;
    a character count for the justification; the preview says up front when a second member of
    staff must confirm; unmatched entries offer **Refresh the course from Canvas** for students
    who joined today; results are announced to screen readers.
  - Badge teams: switching on asks for confirmation and explains the effect; administrators can
    switch teams off from the course or from **Administration → Courses**
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

### Fixed
- Issuance records filter by status entirely in the database, so a page of "active" records is
  no longer cut short by expired ones; records can now also be filtered to "expired". The
  operational summary is counted in PostgreSQL instead of loading every record, and CSV exports
  read records in batches (outside review, 14 Nov 2026).

### Security
- Erasing a person's data now ends their existing sessions at once: every authenticated
  request checks the account is still active, so a session issued before erasure can no longer
  read the collection or change sharing settings until it expires (outside review, 14 Nov 2026).
- Erasure now also takes down the person's public share pages, since they can no longer sign in
  to do it themselves. Credentials stay valid. The erase result reports `share_links_withdrawn`
  instead of `active_share_links`.
- The verifier fails closed on revocation: a credential whose status entry is malformed, uses an
  unsupported status method or points at an unreadable list now shows "Unable to verify", never
  "Verified" (outside review, 14 Nov 2026). Suspension entries are checked too. A credential
  with no status at all still verifies, and the check says it cannot be revoked.
- Owning a course badge no longer grants rights of its own: an owner whose staff role in the
  course has gone can no longer edit, archive, version or manage the team of the badge (outside
  review, 14 Nov 2026). Badges without a course keep owner editing.
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
