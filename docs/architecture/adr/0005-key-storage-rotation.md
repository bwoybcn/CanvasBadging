# ADR-0005: Key storage, rotation and compromise

Date: 2026-11-13 · Status: Accepted

## Decision
- Ed25519 keys are generated in the signer. Each private key is encrypted with its own 256-bit DEK (AES-256-GCM). The DEK is wrapped by a KEK supplied as a secret (`SIGNER_KEK`, file or env) or, optionally, by HashiCorp Vault Transit or a PKCS#11 HSM (`kek_ref` records which). Ciphertext lives in schema `keys`, readable only by DB role `oc_signer`.
- Private keys never appear in logs, API responses, backups of app tables, the browser or the repo. CI secret scanning and a log-scrubber test enforce this.
- Lifecycle: `pending → active → retired → (revoked)`. Exactly one active key per issuer.
- **Routine rotation** (default yearly, or on demand): activate a new key, retire the old one. Retired keys stay in the DID document so historical credentials verify (§15.5). Private material of retired keys is destroyed after 30 days (no further signing need).
- **Compromise:** mark the key `revoked` and remove it from `assertionMethod`, so every credential signed by it now fails verification. Revoke those credentials in the status list (republished with the new key), notify affected holders, and offer reissue. Runbook `docs/security/key-compromise.md` (W4), drilled in W8.
- Dev keys are flagged `is_dev`. The api and signer refuse to start in production if any active key is a dev key.
- KEK backup (escrow) is an institutional responsibility. Without it, keys cannot be restored. This is documented in the backup guide.

## Consequences
DID documents grow slowly with retired keys (acceptable). Compromise handling relies on verifiers re-resolving DIDs, so any verifier that cached our DID document will see the change late.

## Alternatives
Plain env-var keys (no separation). Mandatory cloud KMS (violates §18.5 vendor independence; kept as optional).
