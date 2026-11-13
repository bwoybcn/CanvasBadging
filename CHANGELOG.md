# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Student collection and portability (W6, spec Phase 6): "My credentials" across courses,
  credential detail with live verification, signed download, student-controlled public links
  (off by default, 128-bit random ids, preview of exactly what becomes public, withdraw without
  revoking), server-rendered public verification page with learner-free Open Graph tags, a
  "Check a credential" upload page, public badge images, LinkedIn Add-to-Profile values and
  prefilled link, student and wallet guides, and `noindex` on every response.
- Phase 1 foundation (W2): repository layout, AGPL-3.0-or-later licence and project docs.
- Backend: FastAPI app, settings with production guards, problem+json errors, request ids,
  structured logs, health/readiness probes, development-only login.
- PostgreSQL schema for the spec §12 domain (38 tables) with Alembic migrations, row-level
  security on every tenant table, composite tenant foreign keys, immutability triggers for
  published versions, issued credentials and audit events, and a signer-only `keys` schema.
- Background worker on procrastinate (Postgres-backed queue) with an LTI state purge job.
- Signer service skeleton: Ed25519 key generation (did:key) with envelope-encrypted storage.
  Signing and verification are not implemented yet (W4) and return 501.
- React + TypeScript + Instructure UI frontend shell with development sign-in.
- Demo data: Academic Skills Passport (9 badges in 3 themes) and 12 synthetic learners with
  LMS snapshots and eligibility results.
- Docker Compose environment, CI (lint, types, Pytest, Vitest, dependency and licence audit,
  compose smoke test).
- Architecture, traceability matrix, standards check and ADRs (W1).
