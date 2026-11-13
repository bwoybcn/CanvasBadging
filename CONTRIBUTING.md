# Contributing to OpenCredential

Thank you for helping. OpenCredential is licensed AGPL-3.0-or-later; by contributing you agree
your contribution is licensed the same way.

## Ground rules (from the specification)

- No mocked or simulated issuance. A credential is either really signed and verifiable, or it
  is not shown as a credential.
- No claims of conformance, interoperability or production readiness without test evidence.
- Accessibility (WCAG 2.2 AA) and student privacy are requirements, not extras.
- Record significant decisions as an ADR in `docs/architecture/adr/`. Supersede an ADR with a
  new one rather than editing an accepted one.

## Development workflow

1. Read [docs/development/local-setup.md](docs/development/local-setup.md).
2. Branch from `main`. Keep pull requests focused.
3. Run the checks CI runs:
   - backend: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run pytest`
   - signer and frontend: `npm run lint && npm test && npm run build`
4. Database changes go through Alembic (`uv run alembic revision --autogenerate -m "..."`), then
   review the generated file. Row-level security policies, triggers and grants are hand-written.
   The schema-drift test fails if models and migrations disagree.
5. API changes: regenerate `docs/api/openapi.json` with
   `uv run oc openapi --out ../docs/api/openapi.json` and review the diff. A test fails if the
   snapshot is stale.
6. New dependencies must be on the licence allowlist in ADR-0018 (`scripts/check_licences.py`).

## Code conventions

- Every source file starts with `SPDX-License-Identifier: AGPL-3.0-or-later`.
- Tenant data is always read through `tenant_session(institution_id)`; never take the tenant
  from a request body.
- Module boundaries are enforced by import-linter (see `backend/pyproject.toml`).
