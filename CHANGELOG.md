# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- **`OC_ENV` is now required** by the api, the worker and the signer, and must be exactly
  `development`, `test` or `production` (whole-product review, finding 4). An unset or
  misspelt value used to mean development mode, which accepts the secrets committed to this
  repository. **Upgrading:** set `OC_ENV` wherever you start a service without Docker Compose
  or a `backend/.env` file. `compose.yaml` is the development stack and fixes the mode itself.
- In production the api and the worker refuse to start, and the signer refuses to sign, while
  an active signing key was wrapped with the committed development key-encryption key, not
  only while one is flagged as a development key (migration 0015). The worker now makes the
  same startup checks as the api.
- A basic **request limit inside the app** for the routes anyone can reach without signing in
  (finding 5): 60 a minute for each client address on the public badge checks
  (`POST /api/v1/verify`, share pages) and 600 a minute on the LTI login and launch steps. A
  refused request gets 429 with `Retry-After`. The proxy limit stays the first line.
  `OC_RATE_LIMIT_VERIFY_PER_MINUTE` and `OC_RATE_LIMIT_SIGNIN_PER_MINUTE` change them.
- `OC_FORWARDED_ALLOW_IPS` says which proxy's `X-Forwarded-For` the api believes. **Upgrading
  behind a proxy on another host or container:** set it to the proxy's address, or every
  visitor counts as the proxy and shares one allowance.

### Added
- **A production kit** (finding 6): `docker/compose.production.yaml` runs the whole stack on
  one host in production mode behind an nginx proxy with TLS and rate limits, with every secret
  required and nothing but the proxy published. `docker/production.env.example` lists the
  settings. CI builds, starts and checks it on every change (`scripts/smoke-production.sh`).
  The deployment guide opens with a quick start for it.
- **A release build**: the Release workflow checks the version, builds the api and signer
  images, pushes them to the GitHub container registry and publishes the release with its
  notes from this file (`docs/development/releasing.md`).
- **Someone is told when background work fails.** `GET /healthz/jobs` is for a monitoring tool:
  200 while a worker is running and no job has failed in the last day, otherwise 503 with the
  reason. With `OC_ALERT_WEBHOOK_URL` set, the worker posts to that chat channel within ten
  minutes of a job failing, and once a day while failed jobs are still waiting
  (`OC_ALERT_WEBHOOK_FORMAT`: `text` or `teams`). Both carry task names and counts only.
- `oc api --workers N` (or `OC_API_WORKERS`) starts several API processes, so one burst of slow
  requests no longer holds up everyone else.
- A **Help** link in the menu of every screen. The Help page names who to ask at the
  institution, links to the guides and answers the most common questions. Institution
  administrators set the contact (a name, an email address and a help page of their own) in
  Institution settings (whole-product review, finding 10; migration 0014).
- The wizard takes an optional link to each skill's official description.

### Changed
- **Less is read from Canvas, and for less long** (whole-product review, finding 2; migration
  0016):
  - Submissions and marks are read and kept only for the assignments that a published badge's
    rules use. Every assignment's submissions for every student used to be copied every 30
    minutes. The list of assignments (names and points, no student data) is still kept for the
    badge editor. Submissions held for an assignment no badge uses any more are deleted at the
    next refresh, and nightly.
  - A mark that Canvas has not released to the student is never stored, only the fact that one
    exists, so students still see "Awaiting published result". Unreleased marks already held
    are cleared by the migration.
  - Publishing or restoring a badge that uses an assignment not read before queues a refresh
    from Canvas at once. Until it has run, that requirement shows as not yet confirmed rather
    than "not submitted".
  - **A course that has ended in Canvas stops being read.** Once a day each course is checked:
    concluded, deleted, or past the end date of the course or its term counts as ended. The
    course is read for 60 more days so marks released late still count, then archived: no more
    reads and nothing more awarded from Canvas activity. Issued badges are not affected. The
    progress and submissions held for it are deleted a year after it ended. This retention
    rule existed before but never ran, because nothing ever recorded that a course had ended.
    Both periods are settings under Administration, Personal data and retention
    (`sync_days_after_course_end`, `snapshot_days_after_course_end`). Course staff see a
    notice on the course's Badges home, and can switch badges back on if the course is opened
    again in Canvas.
  - **Upgrading:** tick **Allow Include Parameters** on the Canvas API developer key
    (docs/integrations/canvas.md, step 3). Without it a course is only seen to have ended when
    it was concluded by hand or is past its own end date, not when its term ended.

### Fixed
- Findings 7 to 9 of the whole-product review of 16 November:
  - A person who holds only the **Badge reviewer** role was shown "This page is for course
    staff" instead of the Review queue, and had no menu link to it. The server now tells the
    screens who can review (`may_review` on the profile, from the institution's approver
    roles), so course staff who are approvers get the Review queue link too.
  - Skills typed into a badge never reached the issued badge or its public page. They are now
    written into every badge as Open Badges alignments, with their framework and code. A skill
    without a link of its own points at the badge's published definition, which lists the same
    skills.
  - Erasing a person's data did not hold while they were still enrolled in Canvas: the next
    class-list refresh or launch created them again with their name and email. Erasure now
    leaves a keyed one-way fingerprint of each Canvas identifier (`erased_identities`,
    migration 0014). Class-list refreshes leave the person out, a launch tells them why, and
    `oc admin readmit` lets them return if they ask.
- The lower findings from the third round of hands-on testing:
  - "Remove Requirement" buttons keep their width beside a long message.
  - On the Issuers page, each issuer's delegation controls name that issuer ("Let a course or
    department award as …", "Add delegation for …").
  - Publishing an automatic badge says it is awarded automatically.
  - Staff who open Badges in a course where they have no role are told that the staff links are
    for their other courses.
  - Canvas's Student View "Test Student" is marked on launch (`users.is_test_user`, migration
    0013) and left out of progress lists, the award picker and syncs.
  - The one-student award form marks students who already have the badge and says so before
    **Award badge** is pressed.
  - The Badges list has a "Last changed" column and labels badges that share a title.
- The medium findings from the third round of hands-on testing:
  - The wizard marks unpublished Canvas modules and assignments "(not published in Canvas)", and
    warns when one is chosen: students cannot see it, so nobody could earn the badge. The
    readiness warning says the same.
  - The requirements step says when the course's modules and assignments were last read from
    Canvas, and has **Refresh from Canvas**. Lists more than an hour old are refreshed on their
    own.
  - Confirming or declining a waiting award now says what happened. The "Why" column shows what
    the student did, for example "Catalogue quiz: 80% (needs 70%)".
  - A saved draft can jump straight to any step whose earlier steps are complete, instead of
    paging through every step from the start.
- Two people editing the same draft badge no longer silently overwrite each other (third round
  of hands-on testing). Each badge response carries a `revision`. The wizard sends it back as
  `If-Match`, so a save from a form opened before a colleague's save is refused with
  409 `DRAFT_CHANGED`. The wizard says so and offers **Load the latest version**. A save
  without `If-Match` still works as before.
- The badge wizard, from the first round of hands-on testing:
  - Step 4 needs artwork before **Next**, instead of being marked "(done)" and blocking
    "Submit for review" later.
  - The list of problems updates as they are fixed, and goes when none are left.
  - Steps already done can be opened from the step list.
  - Requirements: a course with no usable modules or assignments says so, instead of an empty
    list, and the introduction explains that "Staff confirm" is met by staff, not by Canvas.
  - The awarding default reads "Follow the institution's setting (today: award automatically)",
    so it is no longer mistaken for a second "Automatic" option.
  - Plain names for badge types ("Co-curricular activity", "Learning programme", "Short
    accredited course"), artwork templates without licence codes, and "What a member of staff
    confirms" instead of "the lecturer".
- Awarding and review, from the first round of hands-on testing:
  - Badge lists (including the review queue) show how the listed version awards. A badge in
    review set to "Staff confirm each award" was listed as "Automatic".
  - **A list of students**: the award button comes after the results table and says how many
    entries it covers ("Award to 2 students (of 6 entries)").
  - **One student**: the student list says "Choose a badge first" until a badge is chosen.
  - **Publish** asks first, and says what publishing does.
  - Disabled buttons say what is missing (Award badge, Approve, Return to author).
  - "1 requirement, which students must meet" instead of "1 requirement(s)".
- Student, public and administration pages, from the first round of hands-on testing:
  - A badge signed with a development (test) key says "Test badge: … it is not an official
    award" on its public page and on **Check a credential file**, and the setup checklist says
    so instead of claiming such badges cannot be checked.
  - The public page lists the badge's learning outcomes. The sharing preview shows dates as
    "15 November 2026", not a timestamp. The verification explanation says "badge", not
    "credential".
  - The home page gives students and staff their own instructions, has a skip link, and every
    page has its own browser title ("Award badges · Badges").
  - Headings on the progress and badge pages go in order (axe `heading-order`).
  - Administration shows its menu beside the page, so the setup checklist is not pushed out of
    sight. Areas are called areas throughout ("New area name"). Policy labels no longer say
    "(default)" next to unticked boxes, and say "staff" rather than "a lecturer".
  - Linking Canvas sub-accounts says plainly when no course needed moving, and warns before
    creating a second area with the name of an existing one.
- Small fixes from the second round of hands-on testing:
  - The short label on badge artwork is made of whole words of letters and digits, so a title
    with an emoji or "<" no longer prints half a word and a box on the badge.
  - **Check a credential file** warns "do not rely on" a file's details only when the file is
    invalid. A revoked or expired badge is genuine, just no longer valid.
  - A shared badge page names the holder once, not again in the facts table.
  - When the session has ended, the page shows only how to carry on, not menus and buttons
    that would fail.
  - **Administration › Courses** asks before switching badge teams on or off (the course page
    already did).
  - A badge waiting only for staff tells students "Waiting for staff to confirm", not "Waiting
    for information".
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
- Certificates print Chinese, Japanese and emoji. Characters Liberation Sans lacks fall back to
  bundled Droid Sans Fallback (Chinese and Japanese, Apache-2.0) and Noto Emoji (black and white,
  OFL), and Chinese and Japanese lines break between characters. A badge with an emoji in its
  name, or a student whose name is in Chinese, no longer has its certificate refused. The fonts
  add about 6 MB.
- Authors are warned when the certificate still cannot show their wording (for example Arabic
  or Hebrew script): "The printable certificate cannot show some characters…" appears among the
  things a reviewer will look at, while the wording can still change. It does not block the badge.
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
