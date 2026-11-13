# Vetted dependencies

Checked 13 Nov 2026 against PyPI and npm registry metadata (latest version, declared licence, release date). Each one is compatible with AGPL-3.0-or-later under [ADR-0018](adr/0018-licence-policy.md). Versions are the latest available today. W2 pins exact versions in lockfiles, and Renovate keeps them current.

## Backend (Python 3.12+)

| Package | Version | Licence | Latest release | Use |
|---|---|---|---|---|
| fastapi | 0.162.5 | MIT | 2026-11-11 | HTTP API |
| pydantic | 2.14.3 | MIT | 2026-11-05 | validation |
| sqlalchemy | 2.1.8 | MIT | 2026-11-04 | ORM |
| alembic | 1.20.1 | MIT | 2026-10-22 | migrations |
| psycopg | 3.3.9 | LGPL-3.0-only | 2026-11-12 | Postgres driver (dynamic linking, compatible) |
| procrastinate | 3.11.0 | MIT | 2026-11-11 | job queue (ADR-0011) |
| joserfc | 1.8.0 | BSD-3-Clause | 2026-11-03 | LTI JWT/JWKS (ADR-0008) |
| httpx | 0.28.1 | BSD-3-Clause | 2024-12-06 | Canvas and signer clients (stable, low churn) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3 | 2026-09-30 | envelope encryption of Canvas tokens |
| structlog | 26.1.0 | MIT OR Apache-2.0 | 2026-06-06 | structured logs |
| python-multipart | 0.0.33 | Apache-2.0 | 2026-10-31 | uploads |
| defusedxml | 0.7.1 | PSF | 2021-03-08 | safe SVG parsing (old but stable; the sanitiser is our own allowlist on top) |
| cairosvg | 2.9.1 | LGPL-3.0-or-later | 2026-09-07 | PNG rendition of sanitised SVG |
| pillow | 13.0.0 | MIT-CMU | 2026-10-16 | PNG validation and resize |
| jinja2 | — | BSD-3 | — | server-rendered verify page |
| hvac (optional) | 2.4.0 | Apache-2.0 | 2025-10-30 | Vault Transit KEK |
| boto3 (optional) | 1.44.2 | Apache-2.0 | 2026-11-12 | S3-compatible asset storage |

Rejected: PyLTI1p3 2.0.0 (MIT, but no release since 2022-11), Authlib (fine licence, larger than needed next to joserfc), arq/rq/dramatiq (need Redis), nh3/bleach (HTML sanitisers, not SVG).

## Signer (Node 22 LTS, TypeScript)

| Package | Version | Licence | Latest release |
|---|---|---|---|
| @digitalbazaar/vc | 7.3.0 | BSD-3-Clause | 2026-02-05 |
| @digitalbazaar/data-integrity | 2.5.0 | BSD-3-Clause | 2024-09-06 |
| @digitalbazaar/eddsa-rdfc-2022-cryptosuite | 1.3.0 | BSD-3-Clause | 2026-02-05 |
| @digitalbazaar/ed25519-multikey | 1.3.1 | BSD-3-Clause | 2025-01-26 |
| @digitalbazaar/vc-bitstring-status-list | 2.0.1 | BSD-3-Clause | 2025-03-07 |
| @digitalbazaar/security-document-loader | 3.2.0 | BSD-3-Clause | 2026-01-21 |
| jsonld | 9.0.0 | BSD-3-Clause | 2025-11-21 |
| jsonld-signatures | 11.6.0 | BSD-3-Clause | 2026-02-05 |
| fastify | 5.12.8 | MIT | 2026-11-02 |
| ajv (JSON Schema) | — | MIT | — |

## Frontend

| Package | Version | Licence |
|---|---|---|
| react | 19.3.1 | MIT |
| @instructure/ui | 11.7.10 | MIT |
| vite, @tanstack/react-query, react-router | — | MIT |

## Test tooling

| Package | Version | Licence |
|---|---|---|
| pytest | 9.2.0 | MIT |
| hypothesis | 6.170.15 | MPL-2.0 |
| respx | 0.23.1 | BSD-3-Clause |
| testcontainers | 4.15.0 | Apache-2.0 |
| pyld (test verifier only) | 3.3.0 | BSD-3-Clause |
| @playwright/test | preinstalled | Apache-2.0 |
| @axe-core/playwright | 4.14.0 | MPL-2.0 |
| vitest | — | MIT |
| schemathesis, pip-audit, pip-licenses, license-checker | — | MIT / Apache-2.0 / MIT / BSD-3 |

Versions marked "—" were not checked today. W2 records them when it creates the lockfiles.
