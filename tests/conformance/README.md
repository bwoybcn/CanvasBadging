# Standards conformance

Evidence that credentials issued by OpenCredential are valid Open Badges 3.0 credentials, checked
by verifiers that we did not write. Everything below runs in the CI job **Independent OB 3.0
verifiers** (`.github/workflows/ci.yml`, job `conformance`) on every pull request.

## What the job does

1. It starts the real stack: PostgreSQL 16, migrations, the signer, the demo seed and the API on
   `http://localhost:8000`.
2. `run-conformance.sh` issues signed credentials to the demo learners (`oc issue-demo`). It keeps
   one *downloaded copy* aside, then revokes that credential (`oc revoke`), which republishes the
   status list. Our own verifier must agree before anyone else is asked.
3. Two independent verifiers then check the credentials:

| Verifier | Maintainer | What it checks | Expectation |
|---|---|---|---|
| `@digitalcredentials/verifier-core` 1.0.0-beta.11 (`dcc/verify.mjs`), the engine behind VerifierPlus and Learner Credential Wallet | Digital Credentials Consortium | eddsa-rdfc-2022 proof, `did:key` resolution, validity period, Bitstring Status List, and the credential's own `credentialSchema` (fetched from `purl.imsglobal.org`) | active credentials: signature valid, unexpired, not revoked, schema valid. Revoked copy: signature valid, **revoked** |
| 1EdTech OB 3.0 inspector (`OB30Inspector` from [digital-credentials-public-validator](https://github.com/1EdTech/digital-credentials-public-validator), pinned commit) via `1edtech/OpenCredentialConformanceTest.java` | 1EdTech | the official validator's full probe set: JSON Schema, contexts, types, issuer, proof, expiry and status | active credentials pass (the only accepted warning: the demo issuer's homepage `demo-university.example` is unreachable); the revoked copy fails with "Credential has been revoked" |

The issued credentials are uploaded as the `conformance-credentials` artefact, so anyone can
re-check them, for example with the 1EdTech web validator.

## Other evidence (Pytest, `backend/tests`)

- `tests/independent/verifier.py` is a second eddsa-rdfc-2022 implementation, written in Python
  (pyld URDNA2015, `cryptography` Ed25519), that shares no code with the Node signer. Every
  issuance test runs it, including after `did:web` key rotation.
- Every issued credential is validated against the official AchievementCredential JSON Schema
  (`backend/opencredential/issuance/schemas/`, pinned by SHA-256).
- `contexts/` holds byte-for-byte copies of the JSON-LD contexts that the signer pins. A signer
  test checks that they are identical.

## Running it locally

With the stack running (see `docs/development/local-setup.md`), and the signer URL set if it is not on 8790:

```
tests/conformance/run-conformance.sh /tmp/oc-conf
cd tests/conformance/dcc && npm ci && node verify.mjs active /tmp/oc-conf/active/*.json \
  && node verify.mjs revoked /tmp/oc-conf/revoked/*.json
```

Set `DCC_REQUIRE_SCHEMA=1` to make the JSON Schema check mandatory. It needs network access to
`purl.imsglobal.org`.

This is not a 1EdTech certification. Certification is a separate submission (W8).
