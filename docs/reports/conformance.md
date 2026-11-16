# Open Badges 3.0 conformance report (spec §19.4, RTM R-0.2, R-19.4, C-OB3-01)

**OpenCredential is not 1EdTech certified.** Certification needs 1EdTech membership and a
submission to 1EdTech (Conformance and Certification Guide), and that has not been done. This
report records what we tested with 1EdTech's own validator and other independent tools, so that
an institution can decide whether to apply. Nothing in OpenCredential's interface or
documentation may claim certification unless it is granted.

## What was tested

Every pull request runs the CI job **Independent OB 3.0 verifiers (DCC, 1EdTech)**. The method
is in [tests/conformance/README.md](../../tests/conformance/README.md). In short:

1. The real stack starts (PostgreSQL, migrations, signer, demo seed, API).
2. Credentials are issued by the production issuance code (`oc issue-demo`), and one is revoked
   after a copy has been downloaded.
3. Every demo learner signs in and downloads their credentials from the student export endpoint,
   and also fetches them from the public share URL, as a wallet would.
4. Two verifiers that OpenCredential's developers did not write check every file.

## Results (CI run 43, 13 November 2026, commit `f25d01a`)

| Check | Tool | Files | Result |
|---|---|---|---|
| Issuance | `oc issue-demo` | 25 credentials issued, 1 revoked | as expected |
| Student download and public URL | `student_share.py` | 48 files obtained as a student would | all obtained; public pages `noindex`, no learner name |
| Proof (`eddsa-rdfc-2022`), `did:key` resolution, validity period, Bitstring Status List, JSON Schema (`credentialSchema`, fetched from `purl.imsglobal.org`) | Digital Credentials Consortium `@digitalcredentials/verifier-core` 1.0.0-beta.11, the engine behind VerifierPlus and the Learner Credential Wallet | 24 active, 48 student copies | **all valid**: signature valid, unexpired, not revoked, schema valid |
| The same, for the revoked copy | same | 1 | signature valid, **revoked**, as expected |
| Full OB 3.0 probe set: JSON Schema, contexts, types, issuer, proof, expiry, status | **1EdTech `OB30Inspector`** from [digital-credentials-public-validator](https://github.com/1EdTech/digital-credentials-public-validator) at commit `4c6631fb5ea206ee60c2e7128749b44d70801098` | 24 active, 48 student copies | **pass**. One warning on each: the demo issuer's homepage `https://demo-university.example/academic-skills` is not reachable, because it is a reserved example domain. A real installation's issuer URL is its own website. |
| The same, for the revoked copy | same | 1 | fails with "Credential has been revoked", as expected |

The issued files are uploaded as the `conformance-credentials` artefact of each run, so anyone
can re-check them, for example with 1EdTech's web validator.

## Other evidence

| Evidence | Where |
|---|---|
| A second `eddsa-rdfc-2022` implementation in Python (pyld URDNA2015 and `cryptography` Ed25519), sharing no code with the signer, verifies every credential in the issuance tests, including after `did:web` key rotation | `backend/tests/independent/verifier.py`, `test_issuance_and_verification.py` |
| Each credential is validated against the official AchievementCredential JSON Schema before signing (pinned by SHA-256) | `backend/opencredential/issuance/schemas/`, `unit/test_ob3.py::test_mandatory_fields` |
| JSON-LD safe mode: undefined terms are refused at signing | signer test "refuses undefined terms (JSON-LD safe mode)" |
| The bundled OB 3.0.3 context is byte-for-byte the official one | signer test "bundles the official Open Badges 3.0.3 context byte-for-byte" |
| Status list credentials are signed and independently verifiable | `test_status_list_credential_is_signed_and_independently_verifiable` |
| The standards check against current 1EdTech and W3C documents | [standards-check.md](../standards/standards-check.md) |

## Known limits

* **Wallet import** (Learner Credential Wallet "add from URL") needs a credential served from a
  public HTTPS host with a trusted certificate. It waits for the verification domain decision.
  The DCC verifier-core result above is the same engine the wallet uses
  ([students/wallets.md](../students/wallets.md)).
* Only `eddsa-rdfc-2022` is issued. Verifying `ecdsa-sd-2023` credentials from other issuers is
  not needed for an issuer, and is not implemented.
* The OB 3.0 API (Host and Service Provider roles) is not implemented
  ([ADR-0014](../architecture/adr/0014-credential-delivery.md)).

## Steps to certification (for the institution)

1. Join 1EdTech (or work through a member).
2. Put the production verification domain and `did:web` issuer in place.
3. Issue a credential to `conformance@imsglobal.org` as the guide describes, and record the
   recipient retrieving it.
4. Submit the results to 1EdTech. Only after certification is granted may OpenCredential be
   described as certified.
