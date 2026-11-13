# ADR-0015: Frontend stack

Date: 2026-11-13 · Status: Accepted

## Decision
React + TypeScript + Vite, TanStack Query for server state, React Router, and Instructure UI (`@instructure/ui`, MIT), so the tool looks native inside Canvas and starts from accessible components. Built as static assets served by the api container. The public verification page is server-rendered (Jinja2) so it works without JavaScript and gives crawlers the OG tags. Tests: vitest + Testing Library, Playwright + axe.

## Consequences
InstUI is large, so routes are lazy-loaded. Admin, lecturer and student areas share one SPA with role-based routing.
