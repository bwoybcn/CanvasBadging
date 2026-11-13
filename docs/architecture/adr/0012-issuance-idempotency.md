# ADR-0012: Idempotent issuance pipeline

Date: 2026-11-13 · Status: Accepted

## Decision
1. An `AwardDecision` row is the only thing that can lead to a credential. It has a unique `idempotency_key` = SHA-256(institution | learner | achievement_version | award kind | issuance_seq), and either an `evaluation_id` or a manual `justification` (CHECK constraint).
2. `credentials.award_decision_id` is UNIQUE. A partial unique index on (version_id, user_id) over non-failed, non-superseded credentials stops two active credentials for the same learner and version even across decisions.
3. The worker locks the decision, creates or reuses the `pending_signature` credential row (fixed `credential_uri`, status index, salt), calls the signer, then stores `signed_json` and marks it `issued` in one transaction with the audit event.
4. A crash after signing but before commit just re-signs on retry. Only one row exists, and the signer is deterministic apart from the proof `created` timestamp. A crash after commit is a no-op on retry.
5. Reissue requires `credential.reissue`, increments `issuance_seq`, and revokes the old credential with reason `superseded`.

Tests: E3, E12, plus a fault-injection test that kills the worker at each step.
