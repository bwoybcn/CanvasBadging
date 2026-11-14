# Administration guide

How an institution governs its credential scheme in OpenCredential (spec §2.3, §2.4, §10,
§12.5; Phase 7). Everything below is done in the **Administration** area of the app
(`/app/admin`) or through the `/api/v1/admin/...` API; nothing requires editing the database.

Who can do what:

| Area | Institution administrator | Department administrator |
| --- | --- | --- |
| Institution settings, policy, retention | Yes | No |
| Faculties and departments | All; decides which may issue | Adds units inside their own |
| Staff roles | Any role, anywhere | Lecturer, course admin, issuer manager, department admin, inside their units, while the policy allows delegation |
| Issuers | Create at any level; **authorise**; suspend | Create department or programme issuers in their units; delegate them |
| Templates | Institution-wide or any unit | Their units |
| Issued credentials, reports, CSV | Whole institution | Courses and issuers in their units |
| Revocation | Always | When the policy lists department administrators (default) |
| Audit log, personal data, failed issuance | Yes | No |

Students always come from Canvas enrolments and cannot be granted here. The last institution
administrator cannot be removed. Roles granted with an expiry stop working at that time.

## 1. Institution settings (§10.1)

Name, description, website, brand colours, achievement categories and LinkedIn organisation.
Brand colours are chosen from a colour swatch, or pasted as a code such as #212b58.
The settings page also shows the **public verification domain**, read-only. The verification
domain is where issuers' `did:web` documents and revocation lists are published (ADR-0004).

Only the service operator sets the verification domain, after checking that the institution
controls it:

```sh
oc admin set-verification-host --institution <slug> --host badges.example.ac.uk
oc admin set-verification-host --institution <slug> --clear
```

The rules for the domain are:

- Each domain can belong to only one institution.
- The change is audited (`institution.verification_host_set`).
- Once any issuer has signed with a `did:web` on that host, the domain cannot be changed, because
  that would break verification of every credential already issued. Plan new issuers on a new
  host instead.

## 2. Faculties, departments and courses

Build the hierarchy (faculty → department → programme). Each unit has **May issue credentials**
(spec §10.3 "which departments can issue"). A unit can issue only if it and every unit above it
may. When a unit may not issue, its issuers are not offered to authors, badges in its courses
cannot be created or published, and issuers in it cannot be authorised. Place each Canvas
course in its department so department administrators and templates apply to it.

### Linking Canvas sub-accounts to areas

Canvas keeps courses in a tree of accounts: the root account, then sub-accounts (often one per
faculty or service, sometimes deeper for departments), then courses. Instead of building areas by
hand, an institution administrator can link the sub-accounts that matter:

1. Under **Canvas sub-accounts** on the departments page, choose **Read sub-accounts from
   Canvas**. The Canvas connection must belong to an account administrator who can see them.
2. Tick the sub-accounts that should be areas, for example each faculty, its departments and the
   Library. Choose a kind for the new areas, or leave it automatic (faculty at the top, department
   below a linked one), then **Link selected**.
3. Each ticked sub-account becomes an area named after it, nested as in Canvas. Courses already
   opened from it join that area straight away, and new courses join on their first launch, from
   the nearest linked sub-account above them.

Sub-accounts nobody ticks, such as sandboxes or terms, are ignored. Canvas's internal **Site Admin** account is never listed. A course already in an area is
never moved, so a manual placement always wins. **Unlink** stops placing new courses but keeps the
area and its courses. Read the tree again after sub-accounts change in Canvas; ones that
disappear are forgotten unless linked. The launch sends the course's sub-account through the
`canvas_account_id=$Canvas.account.id` custom field; on installs without it, linking looks the
course up through the Canvas API instead.

### Recognition courses and badge teams

Badges that are not tied to a module (volunteering, library workshops, CPD) live in a Canvas
"recognition course" per provider or scheme, for example **Library Skills** or **WP
Volunteers**, placed in the provider's sub-account so its issuer and review settings apply.
Create the provider as an org unit of kind **service** (or faculty for a faculty's own
scheme) and put the course in it. Authors pick **Start from a badge template** on the first
step of the create wizard to use one of the ready-made templates.
Students join through a self-enrolment link or an SIS feed.

Many staff often share such a course. Switch on **Badge teams** (course home page in
OpenCredential) so each badge is edited and awarded only by its owner, the colleagues they add
on the badge's **Team** tab ("edit and award" or "award only") and administrators over the
course. Other staff in the course can still see every badge. Any lecturer in the course can
switch badge teams on (after a confirmation that explains colleagues lose access); only an
institution or department administrator can switch them off, from the course home page or from
**Departments and roles → Courses**. A badge's owner, or an administrator, can hand the badge to
another member of course staff on its **Team** tab, for example when the owner leaves.

A recognition course whose live badges are all awarded by staff (manual awards, list awards or
staff approval, with no module, assignment or score rule) reads nothing from Canvas progress. It
gets a roster refresh every six hours instead of a full sync every 30 minutes, and the data
freshness page does not mark it stale. Publishing a badge with a Canvas-data rule brings back the
full sync on the next run.

## 3. Issuers and delegated authority (§10.2)

1. Create the issuer (name, short name, level: university, faculty, department or programme).
   It starts **Not yet authorised**: it has no identity, cannot sign, and is not offered to
   authors. *Creating an issuer does not create an awarding body.*
2. An institution administrator **authorises** it and records the basis of its authority
   (for example "Senate resolution S/2026/14"). Authorisation creates the signing identity:
   `did:web:<verification domain>:issuers:<short name>` with a key held by the signer, or, when
   no domain is configured outside production, a development `did:key`.
3. **Delegate** it to the departments or courses whose staff may award under it.
4. **Suspend** stops new awards. Credentials already issued stay valid; revoke them separately
   if they must stop verifying. Key rotation and key-compromise response are in
   [../security/key-compromise.md](../security/key-compromise.md).

## 4. Approval and awarding policy (§10.3, §6.5)

| Setting | Default |
| --- | --- |
| Colleague review of new and changed badges | Required (other modes: author decides, not required) |
| Areas may set review less strictly | Off (institutions opt in) |
| Who approves definitions | Department and institution administrators, plus named badge reviewers |
| Authors may approve their own badges | Off |
| Default for badges that use marks | A lecturer confirms each award (per-badge choice allowed) |
| Always require confirmation for mark-based badges | Off |
| Manual awards need a second member of staff | Off |
| Who may revoke | Department and institution administrators |
| Department administrators may delegate roles | On |

Institution administrators can always approve and revoke whatever the lists say. Every policy
change is audited with the fields changed.

### Colleague review by area

Review, self-approval and second approval of manual awards can differ by faculty, department or
service, so a volunteering or library workshop badge need not follow the rules for a module
badge. Set them under **Departments and roles → Colleague review by area**:

- **Required**: a reviewer approves every badge before it can be published.
- **Author decides**: the author chooses "Ask a colleague to review it first" (the default) or
  "Publish without review".
- **Not required**: badges can be published straight away. The automatic approval is recorded.

A unit inherits from the unit above it, then from the institution, until it sets its own; the
nearest setting wins. Department administrators can set their own units. **Areas may set
review less strictly** is off by default, so a unit can only be stricter than the institution
until an institution administrator switches it on (Policy page), for example to let the Library
switch review off for workshop badges.

Two kinds of badge always need review, whatever the area says: badges that claim **assessed
proficiency**, and badges whose wording refers to credit or a qualification. The wording check
is a prompt, not a control: it looks for words such as "credit" or "CATS", so a badge phrased
differently is not caught. Where it matters, keep review required for the area.

**Badge reviewer** is a role for a named colleague (a senior librarian, a programme lead) who
may review badges in a unit and the units below it. Institution and department administrators
grant it under **Staff roles**.

Changing a setting never unpublishes anything. **Badges published without review** lists live
badges that nobody else checked, with what review would be now, so you can follow them up after
making review stricter.

## 5. Templates (§10.4)

Templates pre-fill a new badge: title pattern, descriptions, criteria structure, evidence
expectations, category, skills terms, standard validity and artwork conventions. They are
institution-wide or belong to a unit (offered to courses inside it). Authors choose one when
starting a badge and can change anything before review. Archive a template to stop offering it.

**Add ready-made templates** adds four starting points for badges outside modules: volunteering
hours, workshop attendance, event participation and CPD activity. They are institution-wide,
skip any template you already have with the same name, and use placeholders in [brackets] for
the author to replace.

## 6. Manual awards

Lecturers make manual awards with a written justification from **Award badges** (the **One
student** tab); with the second-approval policy on, a different member of staff confirms them
on the **Waiting to confirm** tab, one at a time.

The **A list of students** tab handles evidence kept outside Canvas (volunteering hours, workshop
registers). Staff paste student ID numbers or university emails; OpenCredential shows who
matches a student in the badge's course, who already has the badge and which entries match no
student in the course, then makes one manual award per learner with the same
justification. Second approval applies as for single awards. The audit log records one
`award.bulk` event with the counts, never the list itself. Learners must be enrolled in the
course first (self-enrolment link or SIS feed), so a list cannot reach anyone outside it. Entries are only matched against the course's
students, so the preview never reveals who an email or student number belongs to elsewhere. Administrators see
every award kind in records and reports (`/api/v1/awards?kind=manual`).

## 7. Issued credentials and revocation

**Issued credentials** lists every credential in your scope with its course, issuer, award kind
and status, filterable and exportable to CSV (no email addresses). **Revoke** asks for a reason
code and an explanation; the revocation list is republished at once (or queued if the signer is
down), so verifiers, including for copies the learner already downloaded, report it as revoked
(scenario 8). Course staff who are not revokers can **request** revocation; a revoker approves
(which revokes) or declines it.

## 8. Reports (§10.5)

Issued, revoked and active totals; issuance by course, by badge and by month; awards waiting for
confirmation or issuance; credentials not issued and failed jobs. Filter by issue date and
download the summary or all records as CSV. CSV cells that start with `=`, `+`, `-` or `@` are
prefixed with `'` so spreadsheets do not run them as formulas.

## 9. Audit log (§10.6)

Every significant action with actor, action, affected resource and time, grouped into
categories (issuers, definitions, approval, publication, rule changes, manual and automated
awards, revocations, permission changes, key management, policy, personal data, operations).
Staff are named; learners appear only as identifiers, and event details show only an
allow-listed set of fields (ids, codes, counts). Audit events cannot be changed or deleted, except
by the retention purge for events older than the configured period (minimum one year), which is
enforced in the database.

## 10. Personal data and retention (§12.5)

See [erasure.md](erasure.md) for how erasure interacts with credentials.

- **Download** everything held about a person as JSON (learners can download their own from
  `GET /api/v1/learners/me/data-export`).
- **Erase** a person's personal data (type `ERASE` to confirm).
- **Retention**: Canvas snapshots after a course is archived, eligibility history not used by
  an award, failed jobs and audit events. Applied nightly and on demand.

## 11. Failed issuance

Awards older than ten minutes with no credential (never started, stuck before signing),
failed issuance or status-list jobs, and overdue revocation lists. **Try again** re-queues
issuance (safe to repeat: issuance is idempotent on the award); **Cancel award** stops one that
should never be issued, with a reason. Issued awards cannot be cancelled; revoke instead.

## 12. Courses taking part

With the policy **Courses take part only after a lecturer switches micro-credentials on** (Administration, Policy; on by default), a course launched from
Canvas for the first time takes no part until a lecturer, course admin or administrator chooses
**Switch on micro-credentials for this course** on the launch page
(`POST /api/v1/courses/<id>/activate`). Switching on reads Canvas at once and then every 30
minutes. `POST /api/v1/courses/<id>/deactivate` stops the scheduled reads; badges and issued
credentials are not touched. Both actions are in the audit log under *Policy and
configuration*. With the policy off, every course joins at its first launch.

## 13. Operations

Backups, restoration and incident recovery are for whoever runs the servers:
[../operations/backup-restore.md](../operations/backup-restore.md). The pre-production security
review is in [../security/security-guide.md](../security/security-guide.md).
