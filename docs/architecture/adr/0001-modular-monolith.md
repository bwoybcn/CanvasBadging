# ADR-0001: Modular monolith with a worker and an isolated signer

Date: 2026-11-13 · Status: Accepted

## Context
Spec §3 asks for FastAPI/Python, React, Postgres, background jobs, and keys kept apart from ordinary data. The team is small (AI agents plus one owner), the product is self-hosted by universities, and operational simplicity matters more than independent scaling.

## Decision
One Python codebase (`backend/`, package `opencredential`) with internal modules matching spec §3.3, run as two processes: `api` and `worker`. A separate Node/TypeScript `signer` service is the only process holding private keys (ADR-0003). Module boundaries are enforced with `import-linter` contracts (for example nothing outside `integrations.canvas` imports Canvas types, and `rules` imports no I/O modules).

## Consequences
- Simple deployment: four containers including Postgres.
- Boundaries are kept by lint, not by the network, so discipline in review matters.
- Two languages server-side (Python + Node), justified in ADR-0003.

## Alternatives
Microservices per §3.3 box (too much operational weight for a self-hosted product). Single process doing signing in Python (rejected in ADR-0003).
