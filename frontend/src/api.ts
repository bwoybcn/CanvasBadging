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
  effective_award_policy: AwardPolicy | null;
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

/** Downloads with the in-memory bearer token (no cookies, ADR-0015), keeping the server's filename. */
export async function downloadFile(path: string, token: string | null, fallbackName: string): Promise<void> {
  const res = await fetch(path, { headers: token ? { authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError({ status: res.status, code: "DOWNLOAD_FAILED", title: "The download failed. Please try again." });
  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
