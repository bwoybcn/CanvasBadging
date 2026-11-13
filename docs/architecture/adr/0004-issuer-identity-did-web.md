# ADR-0004: Issuer identity with did:web

Date: 2026-11-13 · Status: Accepted

## Context
Spec §7.4 calls for distinct, institution-controlled, discoverable issuer identities, with `did:web` suggested. The OB Implementation Guide recommends an HTTPS profile associated with `did:web` and a `verificationMethod` that is a fragment of the issuer id. Gary has deferred the University of Liverpool verification domain. The local Canvas is plain http on localhost.

## Decision
- Each `Issuer` (university-, faculty- or department-level) gets `did:web:<verification_host>:issuers:<slug>`, resolved at `https://<verification_host>/issuers/<slug>/did.json`. The DID document lists all non-revoked keys in `verificationMethod` (Multikey) and `assertionMethod`.
- The credential's `issuer` object embeds the OB `Profile` (id = DID, name, url, image, email), so verifiers need no extra fetch for display.
- `verification_host` is per institution and configurable. Until UoL chooses it, configs use the placeholder `credentials.example.ac.uk` and the app refuses to activate a production issuer while the placeholder is set.
- Dev and the local Canvas trial use `did:key` issuers (self-resolving, verifiable offline), with names suffixed "(DEVELOPMENT)".
- An issuer cannot sign until an `inst_admin` records approval of its name, DID and domain (§7.4 "institution must approve").

## Consequences
The institution must control DNS/TLS for the verification host for as long as credentials should verify (documented in the preservation guide). Changing the host later changes the DID, so it is not done lightly. Old credentials keep the old DID, which must stay served or be redirected.

## Alternatives
Plain HTTPS URL issuer ids (allowed, but key discovery is less standard for Data Integrity verifiers). `did:key` in production (no rotation, and the identifier is not tied to the institution's domain).
