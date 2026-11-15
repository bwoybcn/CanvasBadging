# Production installation guide (spec §18.4)

This guide installs OpenCredential for one institution, or for several on one installation,
next to a Canvas LMS. It covers the thirteen topics in spec §18.4. Read the
[security guide](../security/security-guide.md) alongside it, and complete its
pre-production review before go-live.

> The image tags, hostnames and sizes below are examples. Nothing here needs a particular cloud
> provider (spec §18.5): the stack is four containers and PostgreSQL.

## Components

| Component | Image or command | Reachable from | Notes |
|---|---|---|---|
| Reverse proxy | any (Caddy, nginx, an ingress) | Internet | TLS, rate limiting, routes everything to `api` |
| `api` | `docker/api.Dockerfile`, `oc api` | proxy only | FastAPI. Also serves the SPA (`OC_STATIC_DIR`), the public verification pages, DID documents and status lists. Stateless; run two or more. |
| `worker` | same image, `oc worker` | nothing inbound | Canvas sync, evaluation, issuance, status lists, retention. One or more. |
| `signer` | `docker/signer.Dockerfile` | `api` and `worker` only | The only process that holds `SIGNER_KEK` and decrypts keys. Port 8790. |
| PostgreSQL 16+ | managed or self-run | services only | Holds everything, including the job queue. There is no Redis. |
| Artwork store | a volume at `OC_STORAGE_DIR` | `api` | Shared between API replicas (NFS, or one replica) |

## 1. Environment configuration

Settings come from environment variables (backend prefix `OC_`). With `OC_ENV=production` the
services refuse committed development secrets and short secrets, and the development sign-in is
removed.

| Variable | Example | Required |
|---|---|---|
| `OC_ENV` | `production` | yes |
| `OC_DATABASE_URL` | `postgresql+psycopg://oc_app:…@db:5432/opencredential` | yes |
| `OC_DATABASE_OWNER_URL` | `postgresql+psycopg://oc_owner:…@db:5432/opencredential` | migrations only |
| `OC_SECRET_KEY` | 32+ random bytes | yes |
| `OC_SIGNER_URL` | `http://signer:8790` | yes |
| `OC_SIGNER_SHARED_SECRET` | 32+ random bytes, same value on the signer | yes |
| `OC_TOKEN_ENCRYPTION_KEY` | 32+ random bytes | yes |
| `OC_PUBLIC_BASE_URL` | `https://credentials.liverpool.ac.uk` | yes |
| `OC_STATIC_DIR` | `/srv/opencredential/frontend` (the built `frontend/dist`) | yes, on `api` |
| `OC_STORAGE_DIR` | `/var/lib/opencredential/assets` | yes |
| `OC_LTI_PRIVATE_KEY_FILE` | `/var/lib/opencredential/lti/tool_key.pem` | yes |
| `OC_LOG_JSON` / `OC_LOG_LEVEL` | `true` / `INFO` | no |
| `OC_SESSION_TTL_MINUTES` | `30` (5 to 240): how long a session lasts without activity | no |
| `OC_SESSION_MAX_MINUTES` | `480` (5 to 1440): how long after the Canvas launch an active session can keep being renewed. At or below the value above, sessions are never renewed. | no |
| `OC_SYNC_MIN_INTERVAL_SECONDS` | `300` (how often a course can be refreshed on demand) | no |
| `OC_CANVAS_TIMEOUT_SECONDS` / `OC_CANVAS_MAX_RETRIES` | `20` / `4` | no |

Signer: `OC_ENV`, `SIGNER_DATABASE_URL` (as `oc_signer`), `SIGNER_KEK` (32 bytes, base64),
`OC_SIGNER_SHARED_SECRET`, and optionally `SIGNER_PORT`.

## 2. Canvas LTI registration

Follow [../integrations/canvas.md](../integrations/canvas.md) steps 1 to 7, using your production
host in place of `localhost`. In short: create an LTI 1.3 developer key from the tool
configuration at `https://<host>/lti/config.json` (Course Navigation placement, label
"Badges"), deploy it at the root account, register the issuer, client id and
deployment id with `oc canvas register`, then bootstrap the first institution administrator
with `oc admin grant`. If you ever move the tool to a new host, see
[Changing the tool's address](../integrations/canvas.md#changing-the-tools-address).

## 3. OAuth permissions

OpenCredential reads Canvas through an API developer key with **only** the read scopes listed in
[canvas.md, step 3](../integrations/canvas.md#3-create-the-api-developer-key). It never writes to
Canvas. An integration account authorises it once (step 4 and step 6). Tokens are stored
encrypted under `OC_TOKEN_ENCRYPTION_KEY`, refreshed on the server, and never sent to a browser.
Turn on "Enforce scopes" on the key.

## 4. Database setup

```sql
CREATE ROLE oc_owner  LOGIN PASSWORD '…' CREATEROLE;   -- migrations only
CREATE ROLE oc_app    LOGIN PASSWORD '…' NOBYPASSRLS;  -- api and worker
CREATE ROLE oc_signer LOGIN PASSWORD '…' NOBYPASSRLS;  -- signer
CREATE DATABASE opencredential OWNER oc_owner;
REVOKE ALL ON DATABASE opencredential FROM PUBLIC;
GRANT CONNECT ON DATABASE opencredential TO oc_app, oc_signer;
\c opencredential
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

Then run `oc migrate` once with `OC_DATABASE_OWNER_URL` set (as a one-off job, before starting
the services). Migrations create the `app`, `jobs` and `keys` schemas, row-level-security
policies and grants. `oc_app` cannot read `keys.private_keys`, and neither runtime role owns a
table. **Never run `oc seed` in production** (it refuses to).

### Database roles

Give the `oc_owner` password only to the migration job and the backup job. The running services
use `oc_app` and `oc_signer`, which cannot bypass row-level security.

## 5. HTTPS and domain configuration

* One public host serves the app, the LTI endpoints and the public verification pages, for
  example `https://credentials.liverpool.ac.uk`. Set `OC_PUBLIC_BASE_URL` to it.
* The **verification domain** (Administration, Institution settings) is the host in issuers'
  `did:web` identities. Usually it is the same host. It must serve `/issuers/<slug>/did.json`
  and `/status/...` over HTTPS with a publicly trusted certificate,
  because external verifiers fetch them. Choose it carefully: once an issuer has signed with
  it, it can never change. (For Liverpool this decision is still open.)
* Terminate TLS at the proxy, forward `X-Forwarded-Proto: https`, and route all paths to `api`.
  Canvas loads the tool in an iframe, so do not send `X-Frame-Options: DENY`.
* Add the rate limiting from the [security guide](../security/security-guide.md#network).

## 6. Signing-key provisioning

1. Generate `SIGNER_KEK` (`openssl rand -base64 32`). Store it in your secrets manager, and
   keep an offline copy under the same controls as a root CA key.
2. Start the signer with it. The signer refuses the development KEK when `OC_ENV=production`.
3. In Administration, Issuers, create the institution's issuer and **authorise** it with the
   basis of its authority. The signer then generates an Ed25519 key, stores it encrypted, and
   publishes `did:web:<verification domain>:issuers:<slug>`.
4. Retire the demo issuer if one exists. A development `did:key` is refused in production.
5. Rotate keys from the issuer page as your key policy requires. Old public keys stay in the DID
   document, so credentials signed earlier still verify. For compromise, see
   [key-compromise.md](../security/key-compromise.md).

## 7. Backup and restoration

See [../operations/backup-restore.md](../operations/backup-restore.md): `scripts/backup.sh`,
`scripts/restore.sh`, and the destructive drill `scripts/backup-restore-drill.sh`, which CI runs
on every pull request.

## 8. Logging

* Every service logs JSON lines to stdout: `event`, `level`, `timestamp`, `request_id`, and the
  request method, path and status. Collect them with your platform's log shipper.
* Logs never contain tokens, keys, credential bodies or learner names. The audit trail of
  people's actions is in the database (Administration, Audit log), not in the logs.
* `X-Request-ID` is accepted from the proxy (or generated) and is returned in every error body,
  so a user's error report can be matched to a log line.

## 9. Monitoring

| Check | Endpoint or source | Alert when |
|---|---|---|
| Liveness | `GET /healthz` (api), `GET /healthz` (signer) | not 200 |
| Readiness | `GET /readyz` checks the database, the schema revision and the signer | 503 for more than 2 minutes |
| Failed jobs | Administration, Failed issuance; or `jobs.procrastinate_jobs` with `status = 'failed'` | any new failure |
| Awards not issued | Administration, Reconciliation | any entry older than an hour |
| Status-list freshness | the `published_at` of each status list | older than 2 hours (the hourly job has stopped) |
| Canvas sync | `sync_runs` with status `failed`, or the course progress page | repeated failures for a course |
| Errors | proxy and api logs with status 5xx | rate above baseline |

## 10. Upgrade procedures

1. Read `CHANGELOG.md` for the release.
2. Take a backup (section 7).
3. Build or pull the new images.
4. Run `oc migrate` with the owner URL. Migrations are forward-only in production. A downgrade
   path exists for development (`test_downgrade_to_base_and_upgrade_again`), but restore the
   backup rather than downgrade a live database.
5. Restart the signer, then the workers, then the API replicas one at a time.
6. Check `/readyz` and verify one existing credential on `/verify`. Credentials issued before
   the upgrade must still verify (spec §7.7).

## 11. Public verification infrastructure

Everything a third party needs is public, has no authentication, and is served by `api`:

| Path | What it is |
|---|---|
| `/verify` | A page where anyone can upload or paste a credential and check it |
| `/verify/<share id>` | A student's shared credential page (only when they share it), with Open Graph tags but no learner data |
| `/verify/<share id>/credential.json` | The signed credential file, for wallets |
| `POST /api/v1/verify` | Machine-readable verification |
| `/issuers/<slug>/did.json` | `did:web` documents with every public key, current and historical |
| `/status/<issuer>/<list id>` | Signed Bitstring Status Lists (revocation) |

Credentials stay verifiable as long as the DID documents and status lists are served from the
verification domain. If OpenCredential is ever shut down or replaced, follow
[../administration/preserving-verification.md](../administration/preserving-verification.md).

## 12. Data export

* **Learners:** each learner downloads their signed credentials (My credentials, Download) and a
  copy of their personal data (`GET /api/v1/learners/me/data-export`).
* **Administrators:** issuance records as CSV (Administration, Reports and Issued credentials),
  and a person's data export (`GET /api/v1/admin/people/<id>/data-export`) for subject-access
  requests. Erasure is separate from revocation (see [../administration/erasure.md](../administration/erasure.md)).
* **Whole installation:** the database backup (section 7) is a complete, portable export in
  PostgreSQL's open format.

## 13. Incident recovery

See the incident table in
[../operations/backup-restore.md](../operations/backup-restore.md#incident-recovery), and
[key-compromise.md](../security/key-compromise.md) for signing keys.

## Sizing (starting point)

For about 30,000 learners: two `api` replicas (1 vCPU, 1 GB each), one `worker` (1 vCPU, 1 GB),
one `signer` (0.5 vCPU, 256 MB), and PostgreSQL with 2 vCPU, 4 GB and 50 GB of storage. Canvas's
API rate limit, not OpenCredential, is usually what limits how fast it can sync.
