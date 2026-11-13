# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Release hardening (W8, spec Phase 8): course activation ("Switch on micro-credentials for this
  course", with an initial Canvas read and an institution policy for first launch); course award
  history, CSV export and in-app revocation requests for lecturers; honest refresh messages that
  show the last successful Canvas read; security response headers; the issuing job publishes a
  new status list itself, so fresh credentials verify at once; security, cross-tenant and
  malicious-input test suites; Playwright E1–E12 and WCAG 2.2 AA checks in CI; a destructive
  backup and restore drill in CI; threat model, security guide, production, lecturer, API,
  demonstration and DPIA guides; conformance, accessibility, security, dependency, end-to-end,
  traceability-evidence and Definition of Done reports.
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
