# Wallet import: tested routes and limits (spec §9.1-9.2)

OpenCredential issues standard **Open Badges 3.0 / W3C Verifiable Credentials 2.0** credentials
(`eddsa-rdfc-2022` Data Integrity proofs, Bitstring Status List). There is no proprietary format.
A wallet or host that accepts OB 3.0 files can take them directly.

## Two ways to hand a credential to a wallet

| Route | What to give the wallet |
|---|---|
| File import | The file from **Download** (`<badge>-<date>.json`, `application/ld+json`). |
| Add from URL | `https://<verification host>/verify/<share id>/credential.json` (needs the public link turned on). Served without login, with `Access-Control-Allow-Origin: *`. |

## What has been tested

| Implementation | Independent of us? | How | Result |
|---|---|---|---|
| `@digitalcredentials/verifier-core` 1.0.0-beta.11, the verification engine inside **Learner Credential Wallet** and **VerifierPlus** (Digital Credentials Consortium) | Yes | CI job *Independent OB 3.0 verifiers*: every credential a demo student downloads through the student export endpoint, and every copy fetched from a public link, is verified | Signature valid, unexpired, not revoked, OB 3.0 JSON Schema valid |
| 1EdTech OB 3.0 inspector (official validator) | Yes | Same CI job, same student-obtained files | Pass |
| Independent Python verifier (`backend/tests/independent`) | Separate code base from our signer | Pytest, scenarios 6, 7, 9 | Pass, including after the learner's account is closed |

## Not yet tested (needs a public host)

- **Learner Credential Wallet app import** on a phone. LCW verifies with the same engine we run in
  CI, so the file is expected to import. Its "add from URL" also needs the verification host to be
  publicly reachable over HTTPS, which the local Canvas test install (`localhost`) is not. Manual
  check once the verification domain is chosen:
  1. Install LCW (iOS or Android), choose **Add credential → Import from file**, pick a downloaded
     file: it should show the badge as verified.
  2. Turn on the public link, choose **Add from URL** in LCW with
     `https://<host>/verify/<share id>/credential.json`.
  3. Revoke a test credential as an administrator; LCW should show it as revoked on refresh.
- **Hosts that only take OB 2.0 or a proprietary API** (for example some badge platforms' own
  backpacks) are not supported. We document this rather than claim universal wallet support.

## Deferred (spec §21 Phase 2F)

Direct wallet transfer protocols (VC-API / CHAPI exchanges, OB 3.0 Host API with OAuth dynamic
client registration) are not in the MVP. ADR-0014 keeps room for them.
