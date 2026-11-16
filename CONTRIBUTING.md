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

   Name a test file after the feature it tests, and make each test stand on its own: the backend
   suite runs in a shuffled order every time. [backend/tests/README.md](backend/tests/README.md)
   lists where each feature is tested and how to repeat the order of a failed run.
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

## Words on the screen

Staff and students are not specialists, so every screen, message and user guide uses one small
vocabulary. Code, the API, the database and the technical documents keep the standard terms.

| Say | Not | Notes |
|---|---|---|
| **badge** | micro-credential, credential, achievement | The thing a student earns and holds, and its definition |
| **student** | learner, recipient, holder | "Holder" is fine on the public pages, where the reader is a third party |
| **credential file** | credential, JSON | Only the signed file a student downloads, or that someone uploads to check |
| **award** | issue (as a verb for people) | Staff award a badge; the system issues it |

The item in the Canvas course menu is **Badges** (`DEFAULT_LABEL` in
`backend/opencredential/lti/config.py`), and messages that send someone back there quote it.
Names that belong to someone else stay as they are: "Credential ID" and "Credential URL" are
LinkedIn's field names, and "Learner Credential Wallet" is a product. The end-to-end pass over
every screen (`tests/end_to_end/specs/a11y.spec.ts`) fails if "learner" or "micro-credential"
comes back.

## Repository settings (for the owner)

These are set in GitHub, not in the code, so nothing in the repository can enforce them.
Whole-product review, finding 17.

- **Protect `main`.** Settings, Branches, Add branch ruleset (or "Add classic branch protection
  rule") for `main`: require a pull request before merging, require status checks to pass
  (tick every job of the CI workflow: Backend, Signer, Frontend, Dependency audit and licences,
  Independent OB 3.0 verifiers, End-to-end scenarios and accessibility, Docker Compose smoke
  test, Production kit smoke test), and block force pushes. Until this is set, anyone with
  write access can push straight to `main` without the checks.
- **Delete merged branches automatically.** Settings, General, Pull Requests, tick
  "Automatically delete head branches". Branches of pull requests that were merged before this
  was ticked can be deleted from the Branches page; nothing is lost, the commits are in `main`.
- **Dependency updates** arrive weekly from Dependabot, grouped (`.github/dependabot.yml`). The
  jumps that have to be made on purpose (a new Node or Python version, TypeScript 7) are listed
  there with the reason each is held back.
