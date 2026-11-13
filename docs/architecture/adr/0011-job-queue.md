# ADR-0011: Postgres-backed job queue (no Redis)

Date: 2026-11-13 · Status: Accepted

## Context
Spec §3.2 suggests "Redis-backed worker, where required". Issuance correctness depends on enqueuing work atomically with the decision that causes it (§17.2). Spec §0.1 also says to avoid unnecessary dependencies.

## Decision
Use `procrastinate` (MIT, Postgres LISTEN/NOTIFY, actively maintained). Jobs are enqueued in the same transaction as the business write. Retries use exponential backoff with jitter, capped at 8 attempts. Exhausted jobs stay in a failed state that the admin UI can see and retry. Periodic tasks (reconciliation, status republish, retention) use procrastinate's periodic deferrer. Every task is idempotent by design and keyed by `queueing_lock` where duplicates must be prevented.

## Consequences
One fewer service to run and back up, plus transactional enqueue for free. Throughput is far beyond a university's badge volume. Rate limiting uses Postgres or in-process token buckets instead of Redis. If Redis is needed later (for example for caching), it stays optional.

## Alternatives
arq/RQ on Redis (needs an outbox for atomicity, plus another stateful service). Dramatiq (LGPL, Redis/RabbitMQ).
