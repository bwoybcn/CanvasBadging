# ADR-0003: Node/TypeScript signer built on Digital Bazaar libraries

Date: 2026-11-13 · Status: Accepted

## Context
`eddsa-rdfc-2022` needs RDF Dataset Canonicalization, a cryptosuite, and the Data Integrity proof algorithm. Spec §3.2 and §7.3 say: no bespoke crypto, and prefer mature implementations. The Digital Bazaar stack (`@digitalbazaar/vc` 7.3.0, `@digitalbazaar/eddsa-rdfc-2022-cryptosuite` 1.3.0, `@digitalbazaar/ed25519-multikey`, `@digitalbazaar/data-integrity`, `@digitalbazaar/vc-bitstring-status-list`, `jsonld` 9, all BSD-3-Clause, released 2025–2026) is the reference-grade implementation used by W3C test suites and by DCC wallets. Python has `pyld` (canonicalisation) and `cryptography` (Ed25519) but no maintained `eddsa-rdfc-2022` suite, so we would be assembling the proof algorithm ourselves. Spec §3.4 also asks for keys kept apart from ordinary data.

## Decision
A small Node 22 LTS / TypeScript HTTP service (`signer/`, Fastify) exposing keygen, sign, sign-status-list and verify. It owns the `keys` schema DB role and the KEK. It is stateless otherwise, and pure: the same input gives an equivalent signed output. The api and worker never see private keys.

Independent verification (spec §9.1 and §22.7) uses a different implementation: a test-only Python verifier (`pyld` RDFC + `cryptography` Ed25519 + multibase), the 1EdTech validator, and a manual import into Learner Credential Wallet / VerifierPlus. A credential passes only if all of them agree.

## Consequences
- A second runtime to build, scan and patch (`npm audit` in CI, Renovate).
- A clear security boundary: compromise of the api does not leak key material, although it could still request signatures, which the signer limits to issuers marked active and logs.
- The signer's verify is used by our verification page. Independence is preserved by the test verifier, not by production code.

## Alternatives
Pure-Python signing with `pyld` + `cryptography` (single language, but hand-assembled proof algorithm). ACA-Py (heavy agent framework, not designed as a library). Spruce/DIDKit bindings (project direction uncertain).
