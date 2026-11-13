# ADR-0009: How OpenCredential reads Canvas data

Date: 2026-11-13 · Status: Accepted

## Context
LTI does not grant REST access. Canvas client-credentials tokens cover LTI Advantage services (NRPS, AGS for the tool's own line items) and a few Canvas LTI scopes, but not modules or submissions. REST needs an API developer key and an OAuth2 authorization-code token, which acts as the authorising user and lasts 1 hour with a refresh token. Reading another student's module progress (`student_id=`) and submissions needs a staff-level role.

## Decision
- **LTI developer key:** launch, NRPS (`contextmembership.readonly`). Placement `course_navigation`, `default: disabled`, custom fields `canvas_user_id=$Canvas.user.id`, `canvas_course_id=$Canvas.course.id`, privacy level public by default.
- **API developer key** with scope enforcement and only these scopes (GET only): `url:GET|/api/v1/courses/:id`, `url:GET|/api/v1/courses/:course_id/modules`, `url:GET|/api/v1/courses/:course_id/modules/:module_id/items`, `url:GET|/api/v1/courses/:course_id/assignments`, `url:GET|/api/v1/courses/:course_id/students/submissions`, `url:GET|/api/v1/courses/:course_id/enrollments`, `url:GET|/api/v1/users/:id/profile`. W3 checks each scope string against the sandbox's scope list.
- **Token holder:** an institution-designated integration account (a Canvas account role with read-only course content, grades and enrolment permissions, scoped to the relevant sub-account). An admin authorises it once in our admin UI. Tokens are stored encrypted, refreshed server-side, and never sent to the browser.
- **Fallback option** (institution setting): per-instructor OAuth, where each lecturer authorises on first use and sync uses that lecturer's token for their courses.
- No AGS reads, and no writes to Canvas of any kind.

## Consequences
One-time admin setup with two keys, documented step by step for the local sandbox and for UoL. The integration account is a privileged credential, so its token is protected like a signing key (encrypted, audited use).
