# Erasure, revocation and withdrawing sharing

Spec §12.5 requires three separate operations and a description of how erasure requests
interact with immutable credential records and public verification. This is that description.

| Operation | Who | What changes | What does not |
| --- | --- | --- | --- |
| **Erase personal data** | Institution administrator, on the person's request | Name, email and Canvas identifiers removed; staff roles ended; Canvas progress and submission snapshots deleted; eligibility history deleted (or emptied where an award relies on it); notes on requirement approvals cleared; awards not yet issued cancelled; the account marked deleted | Credentials already issued, their revocation status, share links |
| **Revoke a credential** | A revoker under the institution policy | The credential's bit in the revocation list; verifiers report it revoked, including downloaded copies | The learner's personal data; the signed credential (immutable) |
| **Withdraw public sharing** | The learner (W6) | The public share page stops working | The credential and its status |

## Why erasure does not revoke

An issued credential is a signed statement the learner holds independently of OpenCredential
(spec §7.7, §9.5). Revoking it on erasure would take something away from the person asking for
their data to be removed, and would tell every verifier that the achievement is no longer
vouched for, which is not true. If the person also wants the credential revoked, that is a
separate, explicit request.

## What remains after erasure, and why

* **The credential record and its signed JSON.** They are immutable (database trigger, spec
  §12.3) so the institution can always answer for what it signed and revoke it later if needed.
  OpenCredential credentials contain **no name** by default; the recipient is a salted SHA-256
  hash of the email address (ADR-0007), which cannot be reversed without the email.
* **The award decision** (who decided, when, on what basis), needed to justify the credential.
* **The revocation status and status list.** Public verification infrastructure must keep
  answering for credentials in circulation (spec §16, scenario 9).
* **Audit events.** They identify the learner only by an opaque id and are kept for the audit
  retention period, then purged.

After erasure, records show the learner as "Erased learner"; a verifier who holds the learner's
copy can still verify it, but OpenCredential can no longer link it to a named person.

## Legal basis note

Under UK GDPR art. 17(3)(b) and (e), records the institution must keep to meet a legal
obligation or to establish, exercise or defend legal claims (here, the integrity of awards it has
made) may be retained. Each institution's data protection officer should confirm this position
and the retention periods before go-live; the defaults are a starting point, not legal advice.
