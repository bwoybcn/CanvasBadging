# Architecture decision records

Format: context → decision → consequences → alternatives. Status `Accepted` means proposed by W1 and in force until superseded; Gary can veto any of them in review. To change one, add a new ADR that supersedes it, do not rewrite history.

| # | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith + worker + isolated signer | Accepted |
| [0002](0002-proof-format.md) | Data Integrity `eddsa-rdfc-2022`, VCDM 2.0, OB context 3.0.3; no VC-JWT | Accepted |
| [0003](0003-signer-service.md) | Node/TS signer using Digital Bazaar libraries; independent verifier for tests | Accepted |
| [0004](0004-issuer-identity-did-web.md) | `did:web` issuer per issuer on the institution's verification host; `did:key` in dev | Accepted |
| [0005](0005-key-storage-rotation.md) | Envelope-encrypted keys in signer-only schema; pluggable KMS; rotation and compromise rules | Accepted |
| [0006](0006-credential-status.md) | Bitstring Status List for revocation | Accepted |
| [0007](0007-recipient-identity.md) | Salted hashed IdentityObject, no `credentialSubject.id` | Accepted |
| [0008](0008-lti-library.md) | In-house LTI 1.3 launch on `joserfc` | Accepted |
| [0009](0009-canvas-data-access.md) | NRPS + REST via API key and integration-account OAuth token | Accepted |
| [0010](0010-sync-strategy.md) | Polling reconciliation as truth; Live Events as hints; release = `posted_at` | Accepted |
| [0011](0011-job-queue.md) | Postgres-backed queue (procrastinate), no Redis | Accepted |
| [0012](0012-issuance-idempotency.md) | Award decision → idempotent credential row → sign | Accepted |
| [0013](0013-authorisation-model.md) | Scoped RBAC with code policy | Accepted |
| [0014](0014-credential-delivery.md) | File download + public URL; OB API deferred | Accepted |
| [0015](0015-frontend.md) | React + TS + Vite + Instructure UI | Accepted |
| [0016](0016-tenancy.md) | Shared schema + RLS; single-tenant first (UoL) | Accepted |
| [0017](0017-award-policy.md) | Per-badge automatic or lecturer-confirmed awarding for score rules | Accepted |
| [0018](0018-licence-policy.md) | AGPL-3.0-or-later, dependency licence allowlist enforced in CI | Accepted |
