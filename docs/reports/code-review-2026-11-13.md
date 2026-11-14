# Code and security review, 13 November 2026

**Scope:** the whole of `main` at `f609653` (everything since the initial README commit, PRs 1, 3, 4, 5, 15, 16, 17 and 18).

**Method:** two of Claude Code's built-in review processes, both run in report-only mode. No code was changed and no PR comments were posted.

- **`/code-review` at high effort.** It looks for correctness bugs.
- **`/security-review`.** One pass searched for vulnerabilities. Each candidate was then checked by an independent pass that tried to prove it false. The signer bypass was reproduced against the exact Fastify and find-my-way versions in the lockfile. Candidates below 8/10 confidence are dropped by this process; one of them is kept under "below the bar" because it matters once there is more than one institution.

**Not re-reported:** the release conditions in `rtm-evidence.md` (proxy rate limiting, manual screen-reader pass, verification domain, NRPS on hosted Canvas).

## Summary

| # | Severity | Area | Finding |
|---|----------|------|---------|
| S1 | **High** | Signer | Shared-secret check can be skipped with a percent-encoded path. |
| S2 | Medium | Public verifier | SSRF to internal hosts through did:web or status-list URLs. |
| C1 | **High** | Issuance / privacy | An erased or rejected decision can still be signed and issued. |
| C2 | **High** | Course activation | Student-triggered sync issues credentials in inactive courses. |
| C3 | Medium | Key compromise | A compromised *retired* key leaves status lists signed by the revoked key. |
| C4 | Medium | Keys | Signer changes happen before the DB commits, so a failure leaves them out of step. |
| C5 | Medium | Eligibility | After 5 failed syncs, stale snapshot data is treated as usable. |
| C6 | Medium | Manual awards | A rejected manual award blocks every later manual award for that learner. |
| C7 | Medium | Awards list | Lecturers can see an empty or partial "to confirm" list. |
| C8 | Low | Jobs | Retired keys are destroyed again every night, and the destruction is never recorded. |
| C9 | Low | Maintainability | Idempotency key and decision logic are duplicated in two modules. |
| S3 | Medium (multi-tenant only) | Governance | A tenant admin can claim any verification host. Below the confidence bar. |

**Status:** S1, S2 and C1 to C4 are fixed in the same pull request as this report, each with regression tests (`signer/test/signer.test.ts`, `backend/tests/unit/test_verification_sources.py`, `backend/tests/integration/test_w8_review_fixes.py` and `backend/tests/integration/test_w8_course_activation.py`). C5 to C9 and the first part of S3 (unique verification host, local DID answers only under the owning host) are fixed in a follow-up pull request, with tests in `backend/tests/integration/test_w8_review_followups.py`. Still open from S3: who may set the verification host (operator, or proof of domain control), which needs a decision.

**Suggested order:** S1, C1 and C2 before any pilot. S2, C3 and C4 before production. The rest can follow.

## Security findings

### S1. Signer authentication bypass. High, confidence 9/10

**Where:** `signer/src/app.ts:48`

**What the code does:** the only authentication is an `onRequest` hook that checks `req.url.startsWith("/v1/")`. `req.url` is the raw request target. Fastify's router (find-my-way) percent-decodes the path before matching it.

**What gets through:** reproduced against fastify 5.12.8 and find-my-way 9.10.0, all with no `Authorization` header.

- `POST /%761/sign`, `POST /v%31/sign` and `POST /%76%31/keys/<id>/destroy` reach their handlers. So does the absolute-form `POST http://signer:8790/v1/sign`.
- Plain `/v1/sign` correctly returns 401.

**Why it matters:**

- Anything that can reach port 8790 on the compose network can sign an OpenBadgeCredential with any institution's key. Key ids are visible in every credential's `proof.verificationMethod`.
- The same caller can `destroy` or `retire` live keys, or create new ones.
- The shared secret is the only thing between "on the internal network" and "can mint any institution's credentials". ADR-0003 relies on that control.

**Fix:**

- Authenticate on the routed path, not the raw URL. Either register the `/v1` routes in an encapsulated Fastify plugin (`prefix: "/v1"`) with the hook inside it, or require auth on everything except `/healthz` and `/readyz` matched on `req.routeOptions.url`.
- Add tests for `/%761/sign` and an absolute-form target.

### S2. SSRF from the public verifier. Medium, confidence 8/10

**Where:**

- `backend/opencredential/verification/sources.py:101-105` (fetch)
- `verification/service.py:201-207` and `:296` (call sites)
- `public/routes.py:151-171` (the public endpoint)

**What the code does:**

- `POST /api/v1/verify` needs no session and fetches URLs taken from the credential the caller submits.
- The did:web document is fetched before the signature is checked, and the issuer's DID controls both host and port (`did:web:10.0.0.5%3A8443:x`).
- `statusListCredential` is fetched for any credential that is correctly signed, including one the caller self-signs with their own did:key.
- `httpx.Client(follow_redirects=True)` checks for https on the first URL only. A 302 from the attacker's server therefore reaches `http://` internal services and `169.254.169.254`.

**What leaks:** HTTP status codes, connection error types and whether the body was JSON are all returned in `checks[].detail`. That is enough to scan internal ports. Response bodies are not returned, and requests are GET only.

**Fix:**

- Resolve each host and refuse private, loopback and link-local addresses.
- Turn redirects off, or re-validate every hop.
- Return a generic "could not fetch" message rather than the status code or error class.

### S3. Below the bar: a tenant admin can claim any verification host. Medium on multi-tenant installs, confidence 7/10

**Where:**

- `governance/institution.py:89-102` (the host is checked against a regex only)
- `governance/issuers.py:264-266` (the DID is built from the host)
- `verification/sources.py:51-60` and `:125-136` (local DID resolution)
- `public/routes.py:59-67` (`did.json` is chosen by the Host header)

**What the code does:**

- An institution admin can set `verification_host` to another tenant's host or to any real domain. Nothing checks that the host is unique or that the institution owns it.
- The admin can then authorise an issuer under it with a name of their choosing.
- This service's verifier resolves that DID from its own database first. So `/verify` and the "Check a credential" page show **Verified** and "known issuer". On a shared deployment, the victim's domain would also serve the attacker's `did.json`.

**Why it is below the bar:** it needs two or more institutions on one deployment. The planned single-institution Liverpool install is barely affected.

**Fix:**

- Make `verification_host` unique across institutions, and have the operator set it or require proof of domain control.
- Resolve local DIDs only when the DID's host matches the owning institution's host.

## Correctness findings with security or trust impact

### C1. Erased or rejected decisions can still be issued. High

**Where:** `backend/opencredential/issuance/service.py:190`

**What the code does:** `_prepare` returns an existing `pending_signature` credential before it checks `decision.status`. `issuance.pending()` picks up pending credentials whatever their decision status, so `reconcile_issuance` re-queues them.

**What goes wrong:**

1. An award is pending signature, for example because the signer timed out.
2. An admin erases the learner, which sets the decision to `rejected`.
3. The next reconcile signs the credential and flips the decision back to `issued`.

The result is a credential issued to an erased person, which breaks the erasure guarantee.

**Fix:**

- In `_prepare`, check `decision.status` before reusing a pending row.
- Have `pending()` join on live decisions only.
- Have erasure cancel any pending credentials.

### C2. On-demand sync ignores course activation. High

**Where:** `backend/opencredential/api/routes/courses.py:135`

**What the code does:** `POST /courses/{id}/sync` is open to students. The sync, and the evaluation that follows it, never check `course.status`.

**What goes wrong:** a student in an inactive or deactivated course can trigger a sync. Automatic awards are then decided and issued in a course that is meant to take no part. This defeats `course_activation_required`.

**Fix:** refuse the sync with 409 when the course is not active, and also check the course status inside `sync_course_task` and `evaluate_course`.

### C3. Compromise of a retired key leaves status lists on the revoked key. Medium

**Where:** `backend/opencredential/status/compromise.py:60`

**What the code does:** status lists are re-signed only when a replacement key was created, and that happens only if the compromised key was the active one.

**What goes wrong:**

- Suppose key A is rotated to key B, and then A is reported compromised within 24 hours. The lists stay signed by A.
- A is no longer in the DID document, so every credential on those lists shows "Unable to verify", including credentials signed by B.
- The `key_compromise` revocations also stay unpublished until the daily job runs.

**Fix:** always republish the affected lists with the issuer's current active key after a compromise.

### C4. Signer changes happen outside the database transaction. Medium

**Where:** `backend/opencredential/institutions/keys.py:156`

**What the code does:** `handle_compromise` and `activate` call the signer's `destroy_key` or `retire_key` before the request's database transaction commits.

**What goes wrong:**

1. During a compromise response, the signer destroys key A.
2. The status-list publish then fails, and the database rolls back.
3. The database still says A is active, but the signer refuses A, so all issuance for that issuer fails.
4. The replacement key created in that first attempt is left orphaned in the signer.

**Fix:** commit the database state first and run the irreversible signer calls afterwards, as an idempotent job.

### C5. The stale-data guard switches off after 5 failed syncs. Medium

**Where:** `backend/opencredential/eligibility/snapshots.py:89`

**What the code does:** the "latest sync failed, so treat the data as unavailable" rule only applies when an ok or partial run is among the last 5 runs.

**What goes wrong:** after 5 failures in a row (for example Canvas 403s or rate limits), the guard turns off. Snapshot rows that are recent but out of date are then used to issue credentials.

**Fix:** look up the latest successful run and the latest failed run directly, rather than only the last 5 runs.

### C6. A rejected manual award blocks every later manual award for that learner. Medium

**Where:** `backend/opencredential/eligibility/service.py:559`

**What the code does:** manual awards always use the idempotency key `(…, 'manual', 1)`.

**What goes wrong:** once a manual award has been rejected, a corrected award for the same learner hits the unique key. The API then wrongly answers "ALREADY_AWARDED".

**Fix:** bump the sequence number, or create a new key whenever the previous decision is not live.

### C7. The lecturer's awards list can come back empty. Medium

**Where:** `backend/opencredential/api/routes/awards.py:257`

**What the code does:** the endpoint fetches `limit*2` decisions across the whole institution, oldest first, and then filters them by permission in Python.

**What goes wrong:** if other courses have older pending awards, a lecturer can see none of their own.

**Fix:** filter by the caller's courses in SQL.

### C8. Retired keys are destroyed again every night. Low

**Where:** `backend/opencredential/jobs/tasks.py:408`

**What the code does:** `destroy_retired_keys` never records that a key was destroyed.

**What goes wrong:**

- The same keys are sent to the signer for destruction every night, and the work grows without limit.
- The admin key list never shows that the private material has gone.

**Fix:** set a `destroyed_at` field or a `destroyed` state, and audit it.

### C9. The idempotency logic exists in two places. Low

**Where:** `backend/opencredential/eligibility/service.py:61`, which duplicates `issuance/decisions.py`.

**What goes wrong:** if one copy changes, duplicate decisions or credentials become possible.

**Fix:** call `decisions.idempotency_key()` and `decide()` from `eligibility/service.py` instead of keeping its own copy.

## Checked and found sound

These are the security review's notes.

- **LTI launch:**
  - The `iss`, `aud`, `azp`, `exp` and `iat` claims are validated, and only RS* algorithms are accepted.
  - State and nonce are single-use and consumed atomically.
  - The issuer is pinned to its registration, and deployment ids are checked per tenant.
  - Browser binding works by cookie or platform storage.
  - Only context roles are used for role mapping.
- **Sessions:** HS256 tokens with `iss`, `aud` and `exp`; roles are re-read from the database on each request. The dev router is not mounted in production.
- **Canvas OAuth:**
  - The state is signed and single-use.
  - Tokens are sealed with AES-GCM and never appear in responses or logs.
  - Pagination stays on the same origin.
- **Isolation and queries:** row-level security is on every tenant table, and no SQL built from strings takes user input.
- **SVG uploads:** an allow-list sanitiser; DOCTYPE and ENTITY are rejected; storage keys are checked against a regex; files are served with CSP and nosniff.
- **Public pages:** output is escaped, `check.js` uses `textContent` only, and the Open Graph tags carry no personal data.
- **Other:** CSV export guards against formula injection, and there is no `eval`, `subprocess` or `pickle` anywhere.
