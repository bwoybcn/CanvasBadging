# ADR-0016: Tenancy

Date: 2026-11-13 · Status: Accepted

## Context
Spec §3.4 needs strict multi-tenant isolation and single-institution self-hosting. Gary: University of Liverpool first, trialled on a local Canvas, with multi-tenancy designed in.

## Decision
Shared database and schema. `institution_id` on every tenant row, composite FKs that include it, and PostgreSQL RLS on all tenant tables (app role has no BYPASSRLS). The tenant is set per transaction from the session. Tenant resolution at launch comes from the registered (iss, client_id). A single-tenant install is simply one institution row. A cross-tenant test suite runs on every PR.

## Consequences
RLS adds a little query planning cost and needs care in migrations (policies created with tables). Background jobs must set the tenant explicitly. A helper refuses to run a tenant query without it.
