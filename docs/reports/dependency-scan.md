# Dependency scan (spec §15.3, §19.6, RTM S-DEP-01)

## How dependencies are checked

| Check | When | Fails the build on |
|---|---|---|
| `pip-audit --strict` on the backend's locked runtime dependencies (`uv export --frozen --no-dev`) | every pull request (CI job "Dependency audit and licences") | any known vulnerability |
| `npm audit --omit=dev --audit-level=high` for the signer and the frontend | every pull request | high or critical in production dependencies |
| Licence allowlist (ADR-0018, `scripts/check_licences.py`) for Python and both npm projects | every pull request | a licence not compatible with AGPL-3.0-or-later |
| Dependabot (`.github/dependabot.yml`): uv, npm (frontend, signer), GitHub Actions | weekly | opens update pull requests |

Lock files (`uv.lock`, `package-lock.json`) pin every version, and CI installs with
`--frozen` / `npm ci`.

## Results, 13 November 2026 (local run on the W8 branch, and the CI audit job)

| Scope | Tool | Result |
|---|---|---|
| Backend runtime (Python) | pip-audit | **No known vulnerabilities** |
| Signer production dependencies | npm audit | **0 vulnerabilities** |
| Frontend production dependencies | npm audit | **0 vulnerabilities** |
| End-to-end test tooling (`tests/end_to_end`) | npm audit (all) | 0 vulnerabilities |
| Signer and frontend **development** dependencies | npm audit (all) | 10 moderate, all from one advisory: `minimatch` regular-expression denial of service, reached through `eslint` and `typescript-eslint` |

The development-only finding affects the linters, which run on developers' machines and in CI
on trusted input. It is not shipped. It will be cleared when the next `eslint` and
`typescript-eslint` releases arrive through Dependabot. No action is needed for release.

## Licences

All runtime dependencies are on the allowlist in `scripts/check_licences.py` (permissive
licences such as MIT, BSD, Apache-2.0, ISC, MPL-2.0 and PSF, plus LGPL, GPL-3.0-or-later and
AGPL-3.0-or-later). Three packages with missing metadata were reviewed by hand and are listed there. See [architecture/dependencies.md](../architecture/dependencies.md).
