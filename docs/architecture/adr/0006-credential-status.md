# ADR-0006: Revocation with Bitstring Status List

Date: 2026-11-13 · Status: Accepted

## Context
Bitstring Status List v1.0 is a W3C Recommendation (15 May 2025). The 1EdTech guide treats `BitstringStatusListEntry` + `statusPurpose: revocation` as the revocation signal.

## Decision
- Per issuer, revocation lists of 131,072 entries (the spec minimum). A new list is allocated when one is 90% used. Indexes are random among the unused ones.
- Each list is published at `/status/<issuer-slug>/<list-id>` as a signed `BitstringStatusListCredential` (issuer key), `ttl` 300000 ms, `Cache-Control: max-age=300`, and `validUntil` = publish time + 30 days. A nightly job republishes before expiry.
- A revocation writes DB status + event, then enqueues a republish (debounced 10 s). The status endpoint serves the last signed list. If none is valid, it returns 503, which verifiers report as "unable to verify", not "revoked".
- Expiry uses `validUntil` on the credential (from the version's validity period). Suspension is not in MVP.

## Consequences
Revocation takes effect for verifiers within about 5 minutes. Lists must stay hosted for as long as credentials should verify (preservation guide).
