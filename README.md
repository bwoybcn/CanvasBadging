# OpenCredential (CanvasBadging)

Open-source micro-credentialling and digital badging for Canvas LMS. OpenCredential launches
inside Canvas over LTI 1.3, lets staff define badges with clear criteria, evaluates award rules
against real Canvas data, and issues signed [Open Badges 3.0](https://www.imsglobal.org/spec/ob/v3p0/)
verifiable credentials that learners own and can share.

Licence: [AGPL-3.0-or-later](LICENSE). Documentation: CC BY-SA 4.0.

## Status

Phase 1 of the [implementation plan](docs/architecture/architecture.md) (repository and local
foundation) is in place. Not yet built: Canvas LTI launch (W3), credential signing and
verification (W4), badge authoring and rules engine (W5), student sharing (W6), governance (W7).
**OpenCredential does not issue credentials yet, and claims no Open Badges conformance yet.**

## Quick start (development)

Requirements: Docker with Compose v2.

```bash
git clone https://github.com/bwoybcn/CanvasBadging.git
cd CanvasBadging
docker compose up --build
```

Then open <http://localhost:8000/app/> and sign in as one of the synthetic demo users. Compose
starts PostgreSQL 16, applies migrations, starts the signer, loads the demo data (the Academic
Skills Passport badges and 12 synthetic students), and runs the api, worker and an HTTPS proxy at
<https://localhost:8443> for LTI launches from a local Canvas. `scripts/smoke.sh` checks that it
all came up.

Every secret in `compose.yaml` and `.env.example` is a **development** value. The api and signer
refuse to start with them when `OC_ENV=production`, and refuse while a development signing key
is active. See [docs/development/local-setup.md](docs/development/local-setup.md) for running
the pieces without Docker, tests and troubleshooting.

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI app and worker (Python 3.12, package `opencredential`), Alembic migrations, Pytest suite |
| `signer/` | Node 22 / TypeScript signer service, the only process that touches private keys |
| `frontend/` | React + TypeScript + Instructure UI single-page app |
| `examples/` | Reusable demonstration data (Academic Skills Passport) |
| `docker/` | Dockerfiles, Postgres bootstrap, dev Caddy config |
| `docs/` | Architecture, ADRs, API, development, security, deployment |
| `tests/` | Cross-cutting suites: end-to-end (Playwright) and standards conformance |
| `scripts/` | Smoke test and licence gate |
| `site/` | Static website that explains the project (plain HTML and CSS, no build step) |

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
