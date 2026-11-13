# ADR-0007: Recipient identification

Date: 2026-11-13 · Status: Accepted

## Context
Spec §7.5: privacy-preserving subject identification, no raw email public by default, and do not assume a simple email hash is adequate. The OB Implementation Guide: put a DID in `credentialSubject.id` only if the learner proves control of it. Otherwise omit `id` and use `identifier` with a hashed, salted `IdentityObject`.

## Decision
- No `credentialSubject.id` in MVP.
- `identifier`: one `IdentityObject` with `identityType: emailAddress`, `hashed: true`, `identityHash` = SHA-256 of (normalised email + salt), and a random 128-bit salt per credential. The email is the one Canvas reports at issuance.
- Learner name is **not** in the signed credential by default. Institution policy `include_recipient_name_in_credential` can turn it on, with a student-facing notice. On the public page the name appears only if the student ticks "show my name" on that share. That display is not covered by the signature, and the page says so.
- Holder binding guidance for verifiers (D-HOLDER): ask the holder for the email address and check it against the hash with the tool on the verification page, or rely on out-of-band identity checks.

## Consequences / known limits
Anyone holding the file can test guessed emails (the salt is inside the credential). This is acceptable because the file is the student's to share. University email addresses close after graduation, so binding weakens over time. A LATER option is letting students add a personal email or DID at issuance. Hashing gives no protection if the verifier already knows the email, which is by design.
