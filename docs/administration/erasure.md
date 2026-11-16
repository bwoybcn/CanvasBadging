# Erasure, revocation and withdrawing sharing

Spec §12.5 requires three separate operations and a description of how erasure requests
interact with immutable credential records and public verification. This is that description.

| Operation | Who | What changes | What does not |
| --- | --- | --- | --- |
| **Erase personal data** | Institution administrator, on the person's request | Name, email and Canvas identifiers removed; staff roles ended; Canvas progress and submission snapshots deleted; eligibility history deleted (or emptied where an award relies on it); notes on requirement approvals cleared; awards not yet issued cancelled; the account marked deleted; existing sessions ended; public share pages taken down | Credentials already issued and their revocation status |
| **Revoke a credential** | A revoker under the institution policy | The credential's bit in the revocation list; verifiers report it revoked, including downloaded copies | The learner's personal data; the signed credential (immutable) |
| **Withdraw public sharing** | The learner (W6), and automatically on erasure | The public share page stops working | The credential and its status |

## Signing in after erasure

Erasure takes effect at once. Any session the person already had stops working on its next
request (it is refused with `ACCOUNT_INACTIVE`), rather than lasting until it expires, so they
cannot view their collection, change sharing settings or export data afterwards. A new launch
from Canvas is refused too. Public verification does not need a session and keeps working.

## Erasure while the person is still enrolled in Canvas

Canvas still lists an enrolled person in its class lists, and they can still choose **Badges**
in a course menu. OpenCredential does not create them again. When their data is erased it keeps
a marker for each of their Canvas identifiers (the LTI subject, the Canvas user id and the
student ID number). A marker is a keyed one-way fingerprint (HMAC-SHA256, keyed from
`OC_TOKEN_ENCRYPTION_KEY`); the identifier itself is deleted and cannot be read back from it.

* A class-list refresh leaves the person out and carries on with everyone else. The refresh's
  audit record counts them under `erased_skipped`.
* If the person opens Badges from Canvas they are told their data was erased at their request
  and who to ask if they want to use Badges again.
* Nothing is awarded to them, because they no longer have an account here.

If the person later asks to use Badges again, the service operator removes the markers:

```sh
oc admin readmit --institution <slug> --user-id <id of the erased account>
```

The id is in the audit record of the erasure (`privacy.erase`). The person then starts again
with a new, empty account the next time they open Badges or their class list is read. Nothing
that was erased comes back, and badges issued before the erasure stay with the old, nameless
record. The change is audited (`privacy.readmit`).

The markers depend on `OC_TOKEN_ENCRYPTION_KEY`. If that key is ever replaced, markers made
with the old key no longer match, so replace it only as part of a planned change and list the
erased accounts first.

## Public share pages

Erasure takes down the person's public share pages, because afterwards they can no longer sign
in to do it themselves and no one else can. Their credentials are not revoked: a copy they
downloaded, or one held in a wallet, still verifies.

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
* **Markers that stop Canvas bringing the person back** (see above): fingerprints of their
  Canvas identifiers, kept so that the erasure holds while they are still enrolled.

After erasure, records show the learner as "Erased learner"; a verifier who holds the learner's
copy can still verify it, but OpenCredential can no longer link it to a named person.

## Legal basis note

Under UK GDPR art. 17(3)(b) and (e), records the institution must keep to meet a legal
obligation or to establish, exercise or defend legal claims (here, the integrity of awards it has
made) may be retained. Each institution's data protection officer should confirm this position
and the retention periods before go-live; the defaults are a starting point, not legal advice.
