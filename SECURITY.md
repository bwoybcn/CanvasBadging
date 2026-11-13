# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately using GitHub's "Report a vulnerability"
(Security Advisories) on this repository. Do not open a public issue. We aim to acknowledge
reports within 5 working days.

Include the affected version or commit, steps to reproduce, and the impact you expect.

## Supported versions

OpenCredential is pre-release. Only the latest `main` receives fixes.

## Security design in brief

- Issuer private keys live only in the signer service, envelope-encrypted (AES-256-GCM per-key
  data key, wrapped by an operator-supplied key-encryption key) in a database schema only the
  signer's role can read ([ADR-0005](docs/architecture/adr/0005-key-storage-rotation.md)).
- Tenants are isolated by PostgreSQL row-level security and composite foreign keys
  ([ADR-0016](docs/architecture/adr/0016-tenancy.md)).
- Published badge versions, issued credentials and audit events are immutable at the database
  level.
- Development secrets and keys are clearly marked and refused in production
  ([docs/security/development-keys.md](docs/security/development-keys.md)).
