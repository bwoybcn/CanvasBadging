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
| Badges must be approved before publishing | On |
| Who approves definitions | Department and institution administrators |
| Authors may approve their own badges | Off |
| Default for badges that use marks | A lecturer confirms each award (per-badge choice allowed) |
| Always require confirmation for mark-based badges | Off |
| Manual awards need a second member of staff | Off |
| Who may revoke | Department and institution administrators |
| Department administrators may delegate roles | On |

Institution administrators can always approve and revoke whatever the lists say. Every policy
change is audited with the fields changed.

## 5. Templates (§10.4)

Templates pre-fill a new badge: title pattern, descriptions, criteria structure, evidence
expectations, category, skills terms, standard validity and artwork conventions. They are
institution-wide or belong to a unit (offered to courses inside it). Authors choose one when
starting a badge and can change anything before review. Archive a template to stop offering it.

## 6. Manual awards

Lecturers make manual awards with a written justification from **Awards to confirm**; with the
second-approval policy on, a different member of staff confirms them there. Administrators see
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
