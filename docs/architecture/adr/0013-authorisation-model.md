# ADR-0013: Authorisation model

Date: 2026-11-13 · Status: Accepted

## Decision
Scoped RBAC evaluated by one policy module (`authz/policy.py`), with no decorators that skip it.

| Role | Scope | Source | Can |
|---|---|---|---|
| student | course | LTI Learner role | read own progress, credentials; share/export own |
| lecturer | course | LTI Instructor / TeachingAssistant / ContentDeveloper | author drafts for issuers delegated to the course, submit, view course progress, confirm awards, manual award (if policy), request revocation, course CSV |
| course_admin | course | LTI Administrator in context | lecturer + activate course |
| issuer_manager | issuer | grant | manage issuer profile, delegations |
| dept_admin | org unit | grant | review/approve definitions in scope, templates, revoke (if policy), reports in scope, grant roles ≤ own |
| inst_admin | institution | grant (first one by install bootstrap) | everything in the tenant incl. keys, integrations, policy, audit, erasure |

Rules:
- LTI-derived roles are refreshed at every launch and NRPS sync, and lapse when Canvas no longer reports them.
- Org-scoped roles are granted in-app, audited, and cannot exceed the granter's scope.
- Lecturers can only use issuers delegated to their course or org unit (§2.2 "cannot impersonate an institutional issuer").
- Self-approval of definitions and second approval for manual awards follow institution policy.
- A permission-matrix test enumerates every route × role × scope relation (inside, outside, other tenant).
