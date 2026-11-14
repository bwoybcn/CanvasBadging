// SPDX-License-Identifier: AGPL-3.0-or-later
/** Minimal API client. The session token lives in memory only (ADR-0015, no cookies). */

export interface Problem {
  status: number;
  code: string;
  title: string;
  detail?: string | null;
  request_id?: string | null;
}

export class ApiError extends Error {
  constructor(public problem: Problem) {
    super(problem.title);
  }
}

export async function apiFetch<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.body) headers.set("content-type", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let problem: Problem = { status: res.status, code: "HTTP_ERROR", title: res.statusText };
    try {
      problem = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(problem);
  }
  return res.json() as Promise<T>;
}

export interface DevUser {
  id: string;
  display_name: string | null;
  roles: string[];
}

export interface Me {
  id: string;
  display_name: string | null;
  institution: { id: string; slug: string; name: string; is_demo: boolean };
  memberships: { role: string; scope_type: string; scope_id: string; scope_name: string | null }[];
  session_method: string;
  email?: string | null;
  /** Present when the session came from a Canvas launch: the course it was opened in. */
  launch_course?: LaunchCourse | null;
}

export interface LaunchCourse {
  id: string;
  title: string;
  course_code: string | null;
  canvas_course_id: string;
  status: string;
  roles: string[];
  view: "lecturer" | "student";
}

/* ---- W5: authoring, rules and awards ------------------------------------------------------ */

export type Json = Record<string, unknown>;

/** JSON request helper: sends ``body`` as JSON with the given method. */
export function apiSend<T>(path: string, token: string | null, method: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, token, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export type AwardPolicy = "automatic" | "lecturer_confirmed" | "manual";

export interface Course {
  id: string;
  title: string;
  course_code: string | null;
  status: string;
  roles: string[];
  badge_teams?: boolean;
}

/** A badge's team where the course has badge teams switched on. */
export interface BadgeTeam {
  enabled: boolean;
  members: { user_id: string; name: string | null; role: "owner" | "editor" | "awarder" }[];
  candidates: { user_id: string; name: string | null }[];
  can_manage: boolean;
}

export interface IssuerRef {
  id: string;
  name: string;
  did: string;
}

export interface Catalogue {
  categories: string[];
  competency_categories: string[];
  demonstration_kinds: Record<string, string>;
  achievement_types: string[];
  review_checklist: string[];
}

export interface Skill {
  name: string;
  framework?: string | null;
  code?: string | null;
  url?: string | null;
}

export interface DraftFields {
  title?: string | null;
  short_description?: string | null;
  description?: string | null;
  learning_outcomes?: string[] | null;
  criteria_narrative?: string | null;
  category?: string | null;
  achievement_type?: string | null;
  demonstration_kind?: string | null;
  evidence_description?: string | null;
  validity_days?: number | null;
  skills?: Skill[] | null;
  asset_id?: string | null;
  award_policy?: AwardPolicy | null;
}

export type LeafRule =
  | { id?: string; type: "module_completed"; module_id: string }
  | { id?: string; type: "modules_completed"; module_ids: string[] }
  | { id?: string; type: "assignment_submitted"; assignment_id: string }
  | { id?: string; type: "assignment_score"; assignment_id: string; operator: ">="; threshold_percent: number }
  | { id?: string; type: "manual_approval"; instructions: string };

export interface GroupRule {
  id?: string;
  type: "group";
  mode: "ALL" | "ANY";
  rules: LeafRule[];
}

export type Rule = LeafRule | GroupRule;

export interface RuleSet {
  mode: "ALL" | "ANY";
  rules: Rule[];
}

export interface Issue {
  field: string;
  code: string;
  message: string;
  severity: "error" | "warning" | string;
}

export interface Version {
  id: string;
  version_no: number;
  frozen: boolean;
  title: string;
  short_description: string;
  description: string;
  learning_outcomes: string[];
  criteria_narrative: string;
  category: string;
  achievement_type: string;
  demonstration_kind: string;
  evidence_description: string | null;
  validity_days: number | null;
  skills: Skill[];
  asset_id: string | null;
  award_policy: AwardPolicy | null;
  credit_claim_approved: boolean;
  content_hash: string | null;
  published_at: string | null;
}

export interface Review {
  id: string;
  version_id: string;
  reviewer: string | null;
  decision: string;
  checklist: Record<string, boolean>;
  comment: string | null;
  created_at: string;
  without_review?: boolean;
}

export type ReviewMode = "required" | "author_decides" | "not_required";

/** How the working version would be reviewed if submitted now (set per area and per badge). */
export interface ReviewRequirement {
  mode: ReviewMode;
  area_mode: ReviewMode;
  forced_by: "assessed" | "credit" | null;
  set_by_org_unit_id: string | null;
  self_approval_allowed: boolean;
}

export interface Definition {
  id: string;
  state: "draft" | "in_review" | "approved" | "published" | "archived";
  course_id: string | null;
  issuer: { id?: string; name?: string; did?: string };
  owner_user_id: string;
  award_policy: string;
  live_version_id: string | null;
  working_version: Version;
  rules: RuleSet | null;
  readiness: Issue[];
  reviews: Review[];
  can_edit: boolean;
  can_review: boolean;
  can_award?: boolean;
  effective_award_policy: AwardPolicy | null;
  review: ReviewRequirement;
}

export interface DefinitionSummary {
  id: string;
  state: Definition["state"];
  course_id: string | null;
  title: string;
  category: string;
  version_no: number;
  live_version_id: string | null;
  award_policy: string;
  updated_at: string;
}

export interface Asset {
  id: string;
  kind: string;
  media_type: string;
  width: number | null;
  height: number | null;
  alt_text: string;
  licence: string | null;
  data_url: string | null;
  warnings: string[];
}

export interface ArtworkTemplate {
  key: string;
  name: string;
  description: string;
  licence: string;
}

export interface SyncState {
  last_run: {
    status: string;
    kind: string;
    started_at: string;
    finished_at: string | null;
    error_code: string | null;
    failed_learners: number;
  } | null;
  last_success_at: string | null;
}

export interface CanvasModule {
  id: string;
  name: string;
  published: boolean;
  has_requirements: boolean;
  requirement_type: string | null;
  usable: boolean;
}

export interface CanvasAssignment {
  id: string;
  name: string;
  points_possible: number | null;
  published: boolean;
  score_rules_allowed: boolean;
}

export interface Preview {
  preview: true;
  notice: string;
  version_no: number;
  state: string;
  artwork: { data_url: string | null; alt_text: string | null };
  achievement: {
    title: string;
    short_description: string;
    description: string;
    category: string;
    achievement_type: string;
    demonstration: string | null;
    learning_outcomes: string[];
    criteria: string;
    requirements: string[];
    skills: Skill[];
    validity_days: number | null;
  };
  issuer: { name: string | null; url: string | null; did: string | null };
  [key: string]: unknown;
}

export interface Decision {
  id: string;
  version_id: string;
  definition_id: string;
  badge_title: string;
  user_id: string;
  learner_name: string | null;
  kind: "automatic" | "confirmed" | "manual" | string;
  status: string;
  justification: string | null;
  evidence: Json[];
  rejection_reason: string | null;
  decided_at: string;
  current_eligibility: Json | null;
}

export interface Requirement {
  rule_id: string;
  type: string;
  description: string;
  outcome: "met" | "not_met" | "unknown";
  status: "complete" | "incomplete" | "pending";
  confirmed: boolean;
  label: string;
  explanation_code: string;
  message: string;
  as_of: string | null;
  children?: { rule_id: string; description: string; outcome: string; confirmed: boolean; label: string }[];
}

export interface LearnerBadge {
  definition_id: string;
  version_id: string;
  course: { id: string; title: string };
  title: string;
  short_description: string;
  category: string;
  issuer: string | null;
  image: { data_url: string | null; alt_text: string | null };
  award_policy: string;
  status: string;
  outcome: string;
  credential_id: string | null;
  progress: { completed: number; total: number; mode: "ALL" | "ANY" };
  requirements: Requirement[];
}

export interface CourseProgress {
  course: { id: string; title: string };
  badges: {
    definition_id: string;
    version_id: string;
    title: string;
    award_policy: string | null;
    rules: string[];
    source_flags: string[];
  }[];
  learners: {
    user_id: string;
    name: string | null;
    cells: {
      version_id: string;
      outcome: string | null;
      evaluated_at: string | null;
      codes: string[];
      progress: { completed: number; total: number } | null;
      decision_status: string | null;
      decision_id: string | null;
      credential_id?: string | null;
    }[];
  }[];
}

export const STATE_LABELS: Record<Definition["state"], string> = {
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  published: "Published",
  archived: "Archived",
};

export const POLICY_LABELS: Record<string, string> = {
  automatic: "Automatic when requirements are met",
  lecturer_confirmed: "Lecturer confirms each award",
  manual: "Manual award with justification",
};

export function problemText(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail || error.problem.title;
  return "Something went wrong. Please try again.";
}

/* ---- W6: collection, sharing and LinkedIn ------------------------------------------------- */

export type CredentialState = "active" | "revoked" | "suspended" | "expired";

export interface ShareState {
  shared: boolean;
  url: string | null;
  show_name: boolean;
  show_evidence: boolean;
  shared_since: string | null;
}

export interface CredentialSummary {
  id: string;
  credential_id: string;
  name: string;
  issuer_name: string;
  issued_at: string | null;
  valid_until: string | null;
  status: CredentialState;
  course: { id: string; title: string } | null;
  image: { data_url: string | null; alt_text: string };
  share: ShareState;
}

export interface VerificationCheck {
  name: string;
  status: string;
  ok: boolean;
  detail: string;
}

export interface Verification {
  result: "verified" | "revoked" | "expired" | "invalid" | "unable_to_verify";
  label: string;
  checks: VerificationCheck[];
  explanation: string;
  checked_at: string;
}

export interface LinkedInField {
  key: string;
  label: string;
  value: string | null;
}

export interface LinkedIn {
  fields: LinkedInField[];
  add_to_profile_url: string | null;
  needs_share: boolean;
  note: string;
}

export interface Evidence {
  narrative: string;
  url: string | null;
  genre: string | null;
}

export interface CredentialDetail extends CredentialSummary {
  description: string;
  criteria: string;
  achievement_type: string | null;
  learning_outcomes: string[];
  skills: { name: string | null; url: string | null }[];
  evidence: Evidence[];
  issuer: { name: string; id: string; url: string | null; institution: string };
  verification: Verification;
  linkedin: LinkedIn;
}

export interface SharePreview {
  public: {
    credential_name: string;
    recipient_name: string | null;
    evidence: Evidence[];
    [key: string]: unknown;
  };
  visible: { label: string; value: string }[];
  never_shared: string[];
  search_engines: string;
  withdrawing: string;
}

export interface ShareOut {
  share: ShareState;
  linkedin: LinkedIn;
  preview: SharePreview;
}

export const CREDENTIAL_STATE: Record<CredentialState, { label: string; color: "success" | "danger" | "warning" }> = {
  active: { label: "Valid", color: "success" },
  revoked: { label: "Revoked", color: "danger" },
  suspended: { label: "Suspended", color: "warning" },
  expired: { label: "Expired", color: "warning" },
};

export function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

/* ---- W7: institutional governance ----------------------------------------------------------- */

/**
 * Download an authenticated file (CSV, JSON) without putting the token in a URL (no cookies,
 * ADR-0015). Uses the server's Content-Disposition filename when there is one.
 */
export async function downloadFile(path: string, token: string | null, filename: string): Promise<void> {
  const headers = new Headers();
  if (token) headers.set("authorization", `Bearer ${token}`);
  const res = await fetch(path, { headers });
  if (!res.ok) {
    let problem: Problem = { status: res.status, code: "HTTP_ERROR", title: res.statusText };
    try {
      problem = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(problem);
  }
  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}


export interface OrgUnit {
  id: string;
  name: string;
  kind: "faculty" | "department" | "programme" | "other";
  parent_id: string | null;
  may_issue: boolean;
  effective_may_issue: boolean;
  status: "active" | "archived";
  manageable: boolean;
  /** This unit's own review overrides; a missing key inherits from above. */
  review_policy: AreaReviewPolicy;
  effective_review: Required<AreaReviewPolicy> & { sources: Record<keyof AreaReviewPolicy, string | null> };
}

export interface AreaReviewPolicy {
  definition_review?: ReviewMode;
  self_approval_allowed?: boolean;
  manual_awards_require_second_approval?: boolean;
}

export interface UnreviewedBadge {
  id: string;
  title: string;
  version_no: number;
  area: string | null;
  author: string | null;
  approved_at: string;
  reason: string | null;
  review_now: ReviewMode;
}

export interface AdminIssuer {
  id: string;
  name: string;
  slug: string;
  level: "university" | "faculty" | "department" | "programme";
  org_unit_id: string | null;
  org_unit_name: string | null;
  url: string | null;
  email: string | null;
  description: string | null;
  did: string | null;
  status: "draft" | "active" | "suspended";
  authority_basis: string | null;
  authorised_at: string | null;
  may_issue: boolean;
  active_key: { id: string; activated_at: string | null; is_dev: boolean } | null;
  delegations: { id: string; scope_type: "org_unit" | "course"; scope_id: string; scope_name: string | null }[];
}

export interface AdminCourse {
  id: string;
  title: string;
  course_code: string | null;
  status: string;
  org_unit_id: string | null;
  org_unit_name: string | null;
}

export interface StaffRole {
  id: string;
  user_id: string;
  user_name: string | null;
  role: string;
  scope_type: string;
  scope_id: string;
  scope_name: string | null;
  source: string;
  expires_at: string | null;
}

export interface Person {
  id: string;
  display_name: string | null;
}

export interface BadgeTemplate {
  id: string;
  name: string;
  description: string | null;
  org_unit_id: string | null;
  org_unit_name: string | null;
  status: "active" | "archived";
  defaults: Json;
}

export interface CredentialRecord {
  credential_id: string;
  definition_id: string;
  course_id: string | null;
  issued_at: string | null;
  badge_title: string;
  version_no: number;
  course_title: string | null;
  course_code: string | null;
  issuer_name: string;
  learner_name: string | null;
  award_kind: string;
  status: "active" | "revoked" | "expired";
  revoked_at: string | null;
  revocation_reason: string | null;
}

export interface ReportSummary {
  issued: number;
  revoked: number;
  active: number;
  pending_awards: { awaiting_confirmation: number; awaiting_issuance: number };
  failed_issuance: { credentials_not_issued: number; failed_jobs: number };
  by_course: { course_id: string | null; course_title: string; issued: number; revoked: number }[];
  by_badge: { definition_id: string; badge_title: string; course_title: string | null; issued: number; revoked: number }[];
  by_month: { month: string; issued: number }[];
}

export interface AuditItem {
  id: string;
  at: string;
  category: string;
  action: string;
  actor_kind: string;
  actor_user_id: string | null;
  actor_name: string | null;
  resource_type: string;
  resource_id: string | null;
  request_id: string | null;
  data: Json;
}

export interface RevocationRequestRow {
  id: string;
  credential_id: string;
  badge_title: string | null;
  course_title: string | null;
  learner_name: string | null;
  requested_by: string | null;
  reason: string;
  status: string;
  requested_at: string;
  can_decide: boolean;
}

export interface Reconciliation {
  awards_not_issued: {
    decision_id: string;
    badge_title: string;
    learner_name: string | null;
    decided_at: string;
    kind: string;
    credential_status: string | null;
    attempts: number;
    last_error: string | null;
    problem: "never_started" | "signing_failed" | "stuck_before_signing";
  }[];
  failed_jobs: { id: number; task: string; attempts: number; scheduled_at: string | null; subject_type: string | null; subject_id: string | null }[];
  status_lists_overdue: { id: string; issuer_id: string; published_at: string | null; next_publish_due: string | null }[];
}

export const REVOCATION_REASONS: Record<string, string> = {
  issued_in_error: "Issued in error",
  academic_misconduct: "Academic misconduct",
  requirements_not_met: "Requirements not actually met",
  learner_request: "The learner asked for it",
  other: "Other",
};

export const ROLE_LABELS: Record<string, string> = {
  inst_admin: "Institution administrator",
  dept_admin: "Department administrator",
  issuer_manager: "Issuer manager",
  reviewer: "Badge reviewer",
  lecturer: "Lecturer",
  course_admin: "Course administrator",
  student: "Student",
};

/** DELETE that expects 204 No Content. */
export async function apiDelete(path: string, token: string | null): Promise<void> {
  const headers = new Headers({ accept: "application/json" });
  if (token) headers.set("authorization", `Bearer ${token}`);
  const res = await fetch(path, { method: "DELETE", headers });
  if (!res.ok) {
    let problem: Problem = { status: res.status, code: "HTTP_ERROR", title: res.statusText };
    try {
      problem = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(problem);
  }
}

/** One entry of a list award: what happened (or would happen) for that student ID or email. */
export interface BulkRow {
  identifier: string;
  status:
    | "will_award"
    | "awarded"
    | "awaiting_confirmation"
    | "already_awarded"
    | "pending_confirmation"
    | "not_in_course"
    | "not_found"
    | "duplicate"
    | "failed";
  user_id: string | null;
  learner_name: string | null;
  decision_id: string | null;
  message: string | null;
}

export interface BulkAwardResult {
  committed: boolean;
  counts: Partial<Record<BulkRow["status"], number>>;
  rows: BulkRow[];
}
