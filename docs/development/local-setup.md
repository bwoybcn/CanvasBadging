# Local development

## With Docker Compose (recommended)

```bash
docker compose up --build        # first run builds images, migrates and seeds
scripts/smoke.sh                 # Phase 1 exit check
docker compose down -v           # stop and wipe the database
```

| URL | What |
|---|---|
| <http://localhost:8000/app/> | Frontend (development sign-in) |
| <http://localhost:8000/docs> | Interactive API docs |
| <http://localhost:8000/readyz> | Readiness: database, migration revision, signer |
| <https://localhost:8443> | Same app behind Caddy with a self-signed certificate, for LTI launches from a local Canvas at <http://localhost:3000> |

Services: `postgres` (16), `migrate` (one-shot), `signer`, `seed` (one-shot), `api`, `worker`,
`caddy`. The database is published on `127.0.0.1:5432` (override with `OC_POSTGRES_PORT`).

## Without Docker

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, PostgreSQL 16+.

```bash
# 1. Database and roles (once). Uses the same bootstrap as Compose.
POSTGRES_USER=postgres sh docker/postgres/init/01-roles.sh

# 2. Backend
cd backend
uv sync
cp ../.env.example .env              # development values
uv run oc migrate                    # as oc_owner

# 3. Signer (separate terminal)
cd signer && npm ci && npm run dev   # listens on :8790; reads OC_ENV from backend/.env

# 4. Seed, api and worker
uv run oc seed                       # demo institution, dev issuer key, badges, learners
uv run oc api                        # http://localhost:8000
uv run oc worker

# 5. Frontend with hot reload (proxies /api and /dev to :8000)
cd frontend && npm ci && npm run dev # http://localhost:5173/app/
```

`uv run oc seed --reset` drops and rebuilds the whole database (development only).

The api, the worker and the signer all need `OC_ENV` (`development` here). The backend reads it
from `backend/.env`, and `npm run dev` passes the same file to the signer. If you start the
signer another way, set it yourself: `OC_ENV=development node dist/server.js`. A service
started without it stops with "OC_ENV is not set".

## Database roles

| Role | Used by | Rights |
|---|---|---|
| `oc_owner` | migrations, `oc seed` | owns schemas `app`, `jobs`, `keys`; bypasses RLS as owner |
| `oc_app` | api, worker | DML on `app` and `jobs`, subject to row-level security; no access to `keys`; audit events insert-only |
| `oc_signer` | signer | `keys.private_keys` only |

Request handlers always open `tenant_session(institution_id)`, which sets
`app.institution_id` for the transaction. Without it, tenant tables return nothing.

## Tests

```bash
cd backend
uv run pytest                       # unit tests always; DB tests need Postgres
```

Integration tests (`-m db`) create a fresh `opencredential_test` database using the superuser
URL in `OC_TEST_ADMIN_URL` (default `postgresql://postgres:postgres@localhost:5432/postgres`).
The seed and API tests also need the signer pointed at that database:

```bash
OC_ENV=test SIGNER_DATABASE_URL=postgresql://oc_signer:oc_signer_dev@localhost:5432/opencredential_test node signer/dist/server.js
```

They skip if the signer is unreachable, unless `OC_TEST_REQUIRE_SIGNER=1` (set in CI).

Frontend and signer: `npm test` in each folder.

## Demo data

`examples/academic-skills-passport/passport.json` holds the spec §11.3 Academic Skills Passport:
Academic Communication, Research Skills and Digital Skills, three badges each, covering every
MVP rule type (module completion, multiple modules, submission, score threshold, manual
approval, ALL and ANY) and all three award policies. Twelve synthetic students have Canvas-like
module progress and submissions (including unreleased and excused grades), and the seed records
their expected eligibility outcomes. `backend/tests/integration/test_seed_and_api.py` pins a
set of these outcomes as golden data for the rules engine. The seed never issues credentials.
