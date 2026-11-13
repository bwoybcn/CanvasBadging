# ADR-0008: LTI 1.3 implementation

Date: 2026-11-13 · Status: Accepted

## Context
Spec §3.2 asks for an established, maintained LTI 1.3 library. The main Python option, PyLTI1p3, last released 2.0.0 in November 2022 and is built around Django/Flask adapters. The security-critical part (JWT/JWKS validation) is generic.

## Decision
A small in-house `lti` module covering only what we use: OIDC login initiation, resource link launch validation, JWKS caching with kid rotation, client-credentials assertion for NRPS, and generating the Canvas config JSON. All JOSE work uses `joserfc` (BSD-3, maintained). Claim validation follows the 1EdTech Security Framework and LTI Core 1.3, with one negative integration test per check (iss, aud, azp, exp, iat, nonce replay, state, deployment, message type, version, signature, unknown kid). Third-party-cookie resilience: server-side state + signed state value; postMessage platform storage if Canvas offers `lti_storage_target` (to be confirmed by W3 on the sandbox).

## Consequences
We own about 500 lines of protocol code and must keep it current, but no stale dependency sits in the auth path. If W3 finds a maintained library that fits FastAPI cleanly, a superseding ADR may adopt it.
