# Runbook: issuer signing-key compromise

Spec §15.5, ADR-0005. This procedure is covered by an automated drill,
`test_key_compromise_procedure` in `backend/tests/integration/test_issuance_and_verification.py`, which runs
steps 3 to 7 against a `did:web` issuer on every CI run. W8 adds a live tabletop drill.

## What counts as a compromise

Treat any of these as a compromise of the issuer key and start at step 1. Do not wait to be sure.

- The signer KEK (`SIGNER_KEK`), or a backup of the `keys` schema together with the KEK, was
  exposed: for example a leaked secret store, a lost laptop with a live session, or a backup
  copied to the wrong place.
- The signer host or its database role (`oc_signer`) was accessed by someone who should not have
  had access.
- A credential turns up that we did not issue, but it verifies against one of our keys.

Exposure of `oc_app` or of the API alone does **not** expose private keys. That role cannot read
schema `keys`, and a test enforces this. Even so, rotate the key (step 3b) as a precaution.

## Who

- **Incident lead:** the institution's information security contact.
- **Operator:** a platform engineer with shell access to run `oc` and to read the signer logs.
- **Key manager:** an institution administrator (`inst_admin`). Only this role can call the key
  endpoints.
- **Communications:** the badge programme owner, who writes to affected learners.

## Steps

### 1. Contain

1. Stop the signer, or cut its network access, until you know how the key was exposed. Issuance
   requests queue safely while it is down. They retry with backoff, and nothing is lost (spec
   §17.2).
2. Rotate any exposed secret: the KEK, the `oc_signer` password and the api-to-signer shared
   secret. A new KEK means re-wrapping the data keys (W8 adds `signer rewrap`). Until then,
   restore from the secret store into a fresh signer.
3. Keep the evidence: the signer logs (which never contain key material), the audit log
   (`app.audit_events`) and the database snapshot.

### 2. Scope

1. Identify the key: the `issuer_keys.id` behind the exposed `verificationMethod`. The id is the
   `#key-<uuid>` fragment in a `did:web` issuer's DID document.
2. List what it signed:
   `SELECT id FROM app.credentials WHERE issuer_key_id = '<key id>' AND status = 'issued';`
3. Look for credentials the key may have signed outside the system. Any credential whose `id` is
   not in `app.credentials` is a forgery, and steps 3 and 4 neutralise it too.

### 3. Revoke the key and publish a replacement

As the key manager, call the compromise endpoint:

```
POST /api/v1/issuers/{issuer_id}/keys/{key_id}/compromise
{"reason": "<short description, kept in the audit log>"}
```

One transaction then does all of the following:

- **(a)** For a `did:web` issuer whose compromised key is the active one, it creates and
  activates a **replacement key** first, so that there is something to re-sign the status lists
  with.
- **(b)** It marks the compromised key `revoked` and removes it from the DID document's
  `verificationMethod` and `assertionMethod`. From then on, a verifier that re-resolves the DID
  rejects **every** credential signed by that key, genuine or forged. Our verifier reports these
  as *invalid* ("verification method not published by the issuer").
- **(c)** It tells the signer to **destroy** the private key material. This happens as soon as
  the transaction commits (never before, so a failed response leaves the signer and the database
  in step), and a queued `signer_key_lifecycle` job retries it if the signer is unreachable.
- **(d)** It revokes every credential the key signed in the status list, with reason code
  `key_compromise`, and records a status event and an audit event for each one.
- **(e)** It re-signs and republishes **all** of the issuer's status lists with the issuer's
  current key (the replacement, or the existing active key when the compromised key had already
  been rotated out), so that list credentials signed by the compromised key stop being needed.

The response gives you `revoked_key_id`, `replacement_key_id`, `credentials_revoked` and
`status_lists_republished`. Record these in the incident log.

A `did:key` issuer (development only) has no replacement. Its identity *is* the key, so the
issuer itself is burned. Create a new issuer and reissue under it.

### 4. Confirm what the public now sees

1. `GET https://<verification host>/issuers/<slug>/did.json` no longer lists the compromised
   key.
2. `GET /status/<slug>/<list id>` returns a list credential signed by the replacement key. Its
   bit is set for each affected credential.
3. Verify one affected credential, using a downloaded copy:
   `curl -X POST https://<host>/api/v1/verify -d @copy.json`. The result is `invalid`. It is not
   `verified`, and with the key gone a `revoked` result is not reachable either.
4. Remember caching. The DID document and the status list are served with `max-age=300`, and the
   status list has `ttl` 300000 ms, so a correct verifier sees the change within about five
   minutes. A verifier that pinned our DID document will see it late (ADR-0005). Name this in the
   notification.

### 5. Notify

Make the notifications within 72 hours. If the incident is a personal-data breach, UK GDPR
reporting rules also apply; the incident lead decides that.

- **Affected learners.** Tell them that their credential was revoked for security reasons
  through no fault of their own, that a replacement is coming (step 7), and that they should
  replace any copy they have shared or uploaded.
  *Until W6 adds learner notifications, the communications lead sends this by email from the
  list in step 2.*
- **Relying parties we know about** (for example LinkedIn uploads or employers the learner
  named): the same message, with the verification URL.
- **Internally:** governance (spec §7) and the issuer's approver.

### 6. Clean up

- Retired (not compromised) keys stay published so that old credentials still verify. The
  `destroy_retired_keys` periodic job destroys their private material after 30 days.
- A compromised key's private material is destroyed immediately, in step 3c. Its public key
  stays in `issuer_keys` (state `revoked`) for the record, but it is never published again.

### 7. Reissue

Reissuance is an explicit, authorised operation (spec §6.6). It applies only to credentials that
are already revoked:

```
uv run oc reissue <credential id>... --justification "key compromise <incident ref>"
```

For each credential, this:

- creates a new award decision with the next `issuance_seq` (its own idempotency key, so running
  it twice returns the same replacement);
- issues a fresh credential signed by the replacement key;
- marks the old credential as superseded.

The learner's achievement, evidence and dates are carried over unchanged from the original
decision. The replacement has a new id, a new recipient salt and a new status-list index.

### 8. Review

Within two weeks, write a short post-incident note covering the timeline, the root cause, the
credentials affected, and what changes. If the cause was a design weakness, record the decision
as a new ADR that supersedes ADR-0005.

## Why we do not delete old keys on routine rotation

Routine rotation (`POST /issuers/{id}/keys/rotate`) *retires* the old key: it can no longer sign,
but its public key **stays** in the DID document. Deleting it would break the verification of
every credential it signed, which is exactly the harm this procedure deliberately causes in a
compromise. Only a compromise removes a public key.
