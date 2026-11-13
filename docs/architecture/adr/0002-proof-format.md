# ADR-0002: Proof format and data model version

Date: 2026-11-13 · Status: Accepted

## Context
Spec §7.3 asks us to pick the proof format the 1EdTech conformance tests accept. The OB 3.0 errata moved the allowed list into the Conformance and Certification Guide (revision 15 Jun 2026). For Issuers it lists only Linked Data (Data Integrity) proofs: `eddsa-rdfc-2022` or `ecdsa-sd-2023`. VC-JWT/RS256 remains an example in the spec but is not listed as a certifiable issuer proof. Verifiers/displayers must handle both cryptosuites. The ecosystem verifiers we will use for independent testing (Learner Credential Wallet, VerifierPlus) are Data Integrity based.

## Decision
- Embedded proof `DataIntegrityProof`, cryptosuite `eddsa-rdfc-2022`, Ed25519 keys expressed as Multikey, `proofPurpose: assertionMethod`.
- VCDM 2.0 (`https://www.w3.org/ns/credentials/v2`), OB context `context-3.0.3.json`, `validFrom`/`validUntil`.
- All contexts pinned and served from a local document loader. No runtime context fetching.
- Every credential is validated in JSON-LD safe mode and against the official AchievementCredential JSON Schema before signing.
- No VC-JWT in MVP. `ecdsa-sd-2023` verification is added only if we verify third-party credentials (LATER).

## Consequences
Credentials are certifiable as issued and verifiable by the main open wallets. RDF canonicalisation is needed, which drives ADR-0003. Selective disclosure (`ecdsa-sd-2023`) is not offered. Recipient privacy relies on ADR-0007 instead.

## Alternatives
VC-JWT (simpler, JOSE libraries everywhere): not accepted for issuer certification today. `ecdsa-sd-2023`: newer, fewer wallets verify it, and selective disclosure is not needed for MVP.
