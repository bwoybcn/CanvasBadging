# Data protection notes for a DPIA (spec §15.1, §15.2)

These notes help an institution's data protection officer complete a Data Protection Impact
Assessment (DPIA) for OpenCredential under UK GDPR (and EU GDPR where it applies). They describe
what the software does. **The institution decides** the lawful basis, the retention periods
and its operational responsibilities. Nothing here is legal advice.

## 1. What the processing is for

Issuing digital micro-credentials (Open Badges 3.0) to learners for achievements recorded in
Canvas, letting learners keep and share them, and letting third parties verify them.

**Roles.** The institution is the controller. If OpenCredential is run for the institution by
someone else (a hosting provider or a shared service), that party is a processor and needs a
processing agreement. Instructure (Canvas) is already the institution's processor. OpenCredential
only reads from Canvas, through permissions the institution grants.

**Possible lawful bases** (for the institution to decide): public task or legitimate interests
for recording and issuing awards earned on a course; consent is a poor fit, because a learner
cannot meaningfully refuse having their progress recorded. Sharing is always the learner's own
choice.

## 2. Data inventory

| Data | Source | Where held | Who can see it | Default retention |
|---|---|---|---|---|
| Name (display, given, family), email | Canvas LTI launch and roster | `users` | The person; staff of their courses; administrators in scope | While the account is active; removed on erasure |
| Canvas user id, LTI subject | Canvas | `external_identities` | Administrators | As above |
| Course roles | Canvas launch and roster; delegated staff roles | `memberships` | Administrators in scope | Until removed in Canvas, or the role expires |
| Module progress, submission state, scores (released marks only) | Canvas API | `lms_module_progress`, `lms_submissions` | Course staff; the learner sees their own progress | 365 days after the course is archived (`snapshot_days_after_course_end`) |
| Eligibility evaluations (rule results, with the source of each) | Computed | `eligibility_evaluations` | Course staff, administrators | 730 days, unless an award relies on it (`evaluation_days`) |
| Award decisions and manual-award justifications | Staff | `award_decisions` | Course staff, administrators | Kept with the credential |
| Issued credentials | Signed by the institution's issuer | `credentials` (immutable) | The learner; administrators in scope; anyone the learner shares it with | Kept (needed to answer for what was signed; see [erasure.md](../administration/erasure.md)) |
| Share links and display choices | The learner | `share_grants` | The learner; the public, while shared | Until the learner stops sharing |
| Audit events (actor, action, resource, time) | System | `audit_events` (append-only) | Institution administrators | 7 years (`audit_event_years`, minimum 1) |
| Canvas OAuth tokens (for the integration account) | Canvas | encrypted at rest | Nobody (server use only) | Until revoked |
| Failed job records | System | job queue | Administrators | 90 days (`failed_job_days`) |
| LTI launch state | System | `lti_launch_state` | Nobody | 10 minutes |

No special category data is processed. Marks are processed only once released in Canvas.

## 3. What goes into a credential, and what becomes public

| Field | In the signed credential | On the public page |
|---|---|---|
| Achievement name, description, criteria, image, issuer | Yes | Yes |
| Learner's name | **No** by default (institution policy `include_recipient_name_in_credential`) | Only if the learner chooses "Show my name" |
| Email address | **No.** Only a salted SHA-256 hash, with a fresh salt per credential | No |
| Canvas ids, marks, submissions | No | No |
| Evidence | Only evidence the badge marks as disclosable | Only if the learner chooses "Show evidence" |

Nothing is public unless the learner turns on a share link. Link ids are 128-bit random values.
Pages that are not shared send `noindex`, and Open Graph tags carry achievement data only.
Tested by `test_preview_is_exactly_what_becomes_public_and_og_has_no_learner_data`,
`unit/test_ob3.py` and Playwright E11.

**Residual risk:** someone who holds a learner's credential and already knows or guesses the
learner's email can confirm the guess against the hash. They learn nothing they did not already
suspect. The student guide explains this.

## 4. Privacy principles (§15.2) and how they are met

| Principle | How |
|---|---|
| Data minimisation | Only the Canvas data that badge rules need is read (modules, submissions, released scores). No names in credentials by default. Audit logs show learners only by id. |
| Purpose limitation | Canvas access is read-only and limited to the scopes in [canvas.md](../integrations/canvas.md#3-create-the-api-developer-key). Data is used only for evaluation, awards and the learner's own view. |
| Clear sharing controls | Private by default. The learner previews exactly what becomes public. Stopping sharing works at once and does not revoke the credential. |
| Tenant isolation | PostgreSQL row-level security per institution, tested by `test_tenant_isolation.py` and the W8 cross-tenant suite |
| Minimal public disclosure | See section 3 |

## 5. Data subject rights

| Right | How it is met |
|---|---|
| Access (art. 15) | Learners download their own data (`GET /api/v1/learners/me/data-export`) and their credentials. Administrators export any person's data (Administration, Personal data). |
| Rectification (art. 16) | Names come from Canvas; correct them there and they update at the next launch or sync. A credential with a wrong achievement is revoked and reissued. |
| Erasure (art. 17) | Administration, Personal data, **Erase**. Separate from revocation and from withdrawing sharing ([erasure.md](../administration/erasure.md)). Issued credentials are retained under art. 17(3); the institution must confirm this. |
| Restriction, objection | Handled by the institution's process. Administrators can cancel pending awards, and staff can switch a course off. |
| Portability (art. 20) | Credentials are standard, signed Open Badges 3.0 files that work in other wallets and verifiers. The data export is JSON. |

## 6. Security measures

See the [security guide](../security/security-guide.md) and the
[threat model](../security/threat-model.md). In summary: TLS; role-based access checked on the
server; tenant isolation in the database; signing keys only in a separate signer, encrypted at
rest; Canvas tokens encrypted and never sent to browsers; an append-only audit log; dependency
scanning on every change; and a tested backup and restore.

## 7. International transfers

None are built in. The software runs wherever the institution hosts it (spec §18.5), with no
mandatory cloud services. Third parties who verify a credential fetch the public DID document
and status list from the institution's verification domain. LinkedIn receives only what the
learner chooses to add.

## 8. Risks for the DPIA

| Risk | Likelihood and severity before controls | Controls | Residual |
|---|---|---|---|
| Learner identity disclosed through a public credential | Medium, medium | No name or email by default; opt-in sharing; preview | Low |
| Credential linked to a learner by guessing the email hash | Low, low | Fresh salt per credential; documented | Low (accepted) |
| Cross-institution data leak on a shared installation | Low, high | Row-level security, tested | Low |
| Over-collection from Canvas | Medium, low | Read-only scopes; only rule-relevant data | Low |
| Wrong award from bad or partial Canvas data | Medium, medium | Unknown data never counts as met; stale data blocks evaluation; reviewer workflow; revocation | Low |
| Retention longer than needed | Medium, low | Configurable retention, applied nightly | Depends on the institution's settings |
| Signing key stolen and credentials forged | Low, high | Separate signer, envelope encryption, compromise runbook | Low to medium (KEK held as an environment variable; see the security guide) |

## 9. For the institution to decide before go-live

1. Lawful basis, and the privacy notice text for learners (link it from the Canvas course).
2. Retention periods (Administration, Personal data and retention).
3. Whether credentials should include the learner's name (policy, off by default).
4. The verification domain, and who operates it long term
   ([preserving-verification.md](../administration/preserving-verification.md)).
5. Who handles erasure requests, and confirmation of the art. 17(3) position on issued
   credentials.
6. Processor agreements with any hosting provider.
