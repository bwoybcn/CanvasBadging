// SPDX-License-Identifier: AGPL-3.0-or-later
// Written by `oc api-types` from the API description (docs/api/openapi.json). Do not edit:
// change the API model, then run, from backend/:
//   uv run oc openapi --out ../docs/api/openapi.json
//   uv run oc api-types --out ../frontend/src/api.gen.ts
// A backend test fails when this file is out of date.

export interface AchievementsRejectIn {
  comment: string;
  checklist?: Record<string, boolean> | null;
}

export interface ArtworkConvention {
  template?: string | null;
  primary_colour?: string | null;
  secondary_colour?: string | null;
  guidance?: string | null;
}

export interface AssetOut {
  id: string;
  kind: string;
  media_type: string;
  width: number | null;
  height: number | null;
  bytes: number;
  sha256: string;
  alt_text: string;
  licence: string | null;
  data_url: string | null;
  warnings: string[];
}

export interface AssetsTemplateIn {
  template: string;
  primary_colour: string;
  secondary_colour: string;
  label: string;
  alt_text: string;
}

/** Rule D: a released score at or above ``threshold_percent`` of points possible. */
export interface AssignmentScore {
  id?: string | null;
  type?: "assignment_score";
  assignment_id: string;
  operator?: ">=";
  threshold_percent: number;
}

/** Rule C: a qualifying submission exists for a Canvas assignment. */
export interface AssignmentSubmitted {
  id?: string | null;
  type?: "assignment_submitted";
  assignment_id: string;
}

export interface AuthoriseIn {
  authority_basis: string;
}

export interface AwardPolicyIn {
  score_rules_default_policy?: "automatic" | "lecturer_confirmed" | null;
  score_rules_force_confirmation?: boolean | null;
  definitions_require_approval?: boolean | null;
  definition_review?: "required" | "author_decides" | "not_required" | null;
  areas_may_relax_review?: boolean | null;
  self_approval_allowed?: boolean | null;
  manual_awards_require_second_approval?: boolean | null;
  max_snapshot_age_minutes?: number | null;
  approver_roles?: ("lecturer" | "dept_admin" | "inst_admin")[] | null;
  revokers?: ("lecturer" | "issuer_manager" | "dept_admin" | "inst_admin")[] | null;
  dept_admins_may_delegate?: boolean | null;
  course_activation_required?: boolean | null;
}

export interface AwardsRejectIn {
  reason: string;
}

export interface BadgeTeamsIn {
  enabled: boolean;
}

export interface Branding {
  primary_colour?: string | null;
  secondary_colour?: string | null;
}

export interface BulkAwardIn {
  definition_id: string;
  /** Student ID numbers (SIS user ids) or university emails. Each item may also hold several, separated by new lines, commas, semicolons or tabs. */
  identifiers: string[];
  justification: string;
  evidence?: Evidence[];
  /** false: preview only. true: make the awards. */
  confirm?: boolean;
}

export interface BulkAwardOut {
  committed: boolean;
  /** true: each award waits for a second member of staff to confirm it. */
  second_approval: boolean;
  counts: Record<string, number>;
  rows: BulkRowOut[];
}

export interface BulkRowOut {
  identifier: string;
  /** will_award, awarded, awaiting_confirmation, already_awarded, pending_confirmation, not_found (no student in the badge's course matches), duplicate or failed */
  status: string;
  user_id: string | null;
  learner_name: string | null;
  decision_id: string | null;
  message: string | null;
}

export interface CanvasAccountLinkIn {
  items: CanvasAccountLinkItem[];
}

export interface CanvasAccountLinkItem {
  id: string;
  org_unit_id?: string | null;
  kind?: "faculty" | "department" | "programme" | "service" | "other" | null;
}

export interface CheckOut {
  name: string;
  status: string;
  ok: boolean;
  detail: string;
}

export interface CompromiseIn {
  reason: string;
}

export interface CompromiseOut {
  revoked_key_id: string;
  replacement_key_id: string | null;
  credentials_revoked: number;
  status_lists_republished: number;
}

export interface ConfirmAllIn {
  decision_ids: string[];
}

export interface ConfirmAllOut {
  confirmed: number;
  left: number;
  rows: ConfirmAllRow[];
}

export interface ConfirmAllRow {
  id: string;
  learner_name: string | null;
  badge_title: string;
  confirmed: boolean;
  code: string | null;
  message: string | null;
}

export interface ConfirmIn {
  note?: string | null;
}

export interface CourseActivationOut {
  id: string;
  status: string;
  activated_at: string | null;
  sync_queued: boolean;
}

export interface CourseOut {
  id: string;
  title: string;
  course_code: string | null;
  status: string;
  roles: string[];
  staff: boolean;
  badge_teams: boolean;
}

export interface CourseRef {
  id: string;
  title: string;
}

export interface CourseUnitIn {
  org_unit_id: string | null;
}

export interface CreateIn {
  issuer_id: string;
  course_id?: string | null;
  fields?: DraftFields;
  rules?: RuleSet | null;
  template_id?: string | null;
}

export interface CredentialDetail {
  id: string;
  credential_id: string;
  name: string;
  issuer_name: string;
  issued_at: string | null;
  valid_until: string | null;
  status: "active" | "revoked" | "suspended" | "expired";
  course: CourseRef | null;
  image: ImageOut;
  share: ShareState;
  withdrawal: Withdrawal | null;
  description: string;
  criteria: string;
  achievement_type: string | null;
  learning_outcomes: string[];
  skills: Record<string, unknown>[];
  evidence: Record<string, unknown>[];
  issuer: Record<string, unknown>;
  verification: Record<string, unknown>;
  linkedin: Record<string, unknown>;
}

export interface CredentialSummary {
  id: string;
  credential_id: string;
  name: string;
  issuer_name: string;
  issued_at: string | null;
  valid_until: string | null;
  status: "active" | "revoked" | "suspended" | "expired";
  course: CourseRef | null;
  image: ImageOut;
  share: ShareState;
}

export interface DecideRequestIn {
  reason_code?: "issued_in_error" | "academic_misconduct" | "requirements_not_met" | "learner_request" | "other";
  note?: string | null;
}

export interface DecisionOut {
  id: string;
  version_id: string;
  definition_id: string;
  badge_title: string;
  user_id: string;
  learner_name: string | null;
  kind: string;
  status: string;
  evaluation_id: string | null;
  justification: string | null;
  evidence: Record<string, unknown>[];
  rejection_reason: string | null;
  decided_by: string | null;
  decided_at: string;
  idempotency_key: string;
  current_eligibility: Record<string, unknown> | null;
}

export interface DefinitionList {
  items: DefinitionSummary[];
  next_cursor: string | null;
}

export interface DefinitionOut {
  id: string;
  state: string;
  course_id: string | null;
  issuer: Record<string, unknown>;
  owner_user_id: string;
  award_policy: string;
  live_version_id: string | null;
  working_version: VersionOut;
  rules: Record<string, unknown> | null;
  readiness: Issue[];
  reviews: ReviewOut[];
  can_edit: boolean;
  can_review: boolean;
  can_award: boolean;
  /** Send back as If-Match when saving the draft; a save from an out-of-date form is refused with 409 DRAFT_CHANGED */
  revision: string;
  /** What publication would resolve the awarding method to right now */
  effective_award_policy: string | null;
  review: ReviewRequirement;
}

export interface DefinitionSummary {
  id: string;
  state: string;
  course_id: string | null;
  title: string;
  category: string;
  version_no: number;
  live_version_id: string | null;
  award_policy: string;
  updated_at: string;
  course_title: string | null;
  can_award: boolean;
}

export interface DelegationIn {
  scope_type: "org_unit" | "course";
  scope_id: string;
}

export interface DevLoginRequest {
  institution: string;
  user_id: string;
}

export interface DevLoginResponse {
  token: string;
  expires_at: string;
  user_id: string;
  institution_id: string;
}

export interface DevUser {
  id: string;
  display_name: string | null;
  roles: ("student" | "lecturer" | "course_admin" | "issuer_manager" | "reviewer" | "dept_admin" | "inst_admin")[];
}

/**
 * Editable fields of a draft version. Everything is optional while drafting; completeness
 * is checked when the draft is submitted (see :func:`readiness`).
 */
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
  /** automatic | lecturer_confirmed | manual | null (default) */
  award_policy?: string | null;
}

export interface EraseIn {
  confirm: string;
}

export interface EvaluateIn {
  definition_id: string;
  user_ids?: string[] | null;
}

export interface EvaluationOut {
  id: string;
  version_id: string;
  user_id: string;
  outcome: string;
  detail: Record<string, unknown>;
  inputs_hash: string;
  triggered_by: string;
  evaluated_at: string;
}

export interface Evidence {
  kind: string;
  narrative: string;
  url?: string | null;
  public?: boolean;
}

export interface GovernanceTemplateIn {
  name: string;
  description?: string | null;
  org_unit_id?: string | null;
  defaults?: TemplateDefaults;
}

export interface GrantIn {
  user_id: string;
  role: "lecturer" | "course_admin" | "issuer_manager" | "reviewer" | "dept_admin" | "inst_admin";
  scope_type: "institution" | "org_unit" | "issuer" | "course";
  scope_id?: string | null;
  expires_at?: string | null;
}

export interface GrantableRoleOut {
  role: "lecturer" | "course_admin" | "issuer_manager" | "reviewer" | "dept_admin" | "inst_admin";
  scope_type: "institution" | "org_unit" | "issuer" | "course";
}

/** Rule F (nested): a combination of leaf rules with its own mode. */
export interface Group {
  id?: string | null;
  type?: "group";
  mode: "ALL" | "ANY";
  rules: (ModuleCompleted | ModulesCompleted | AssignmentSubmitted | AssignmentScore | ManualApproval)[];
}

export interface HTTPValidationError {
  detail: ValidationError[];
}

/** Who to ask for help with badges here, as set by an institution administrator. */
export interface HelpOut {
  contact_name: string | null;
  email: string | null;
  url: string | null;
}

export interface ImageOut {
  data_url: string | null;
  alt_text: string;
}

export interface InstitutionIn {
  name?: string | null;
  description?: string | null;
  website_url?: string | null;
  help_contact_name?: string | null;
  help_email?: string | null;
  help_url?: string | null;
  logo_asset_id?: string | null;
  branding?: Branding | null;
  /** Operator-only. Send the current value or leave it out; a change is refused. */
  verification_host?: string | null;
  categories?: string[] | null;
  linkedin_org_id?: string | null;
  linkedin_org_name?: string | null;
}

export interface InstitutionOut {
  id: string;
  slug: string;
  name: string;
  is_demo: boolean;
}

export interface IntegrationOut {
  id: string;
  name: string;
  base_url: string;
  lti_issuer: string;
  lti_client_id: string;
  api_client_id: string | null;
  status: string;
  api_connected: boolean;
  api_token_expires_at: string | null;
  api_authorised_canvas_user_id: string | null;
  api_scopes: string[];
}

export interface Issue {
  field: string;
  code: string;
  message: string;
  severity: string;
}

export interface IssuerIn {
  name: string;
  slug: string;
  /** One of university, faculty, department, programme */
  level: string;
  org_unit_id?: string | null;
  url?: string | null;
  email?: string | null;
  description?: string | null;
}

export interface IssuerPatch {
  name?: string | null;
  url?: string | null;
  email?: string | null;
  description?: string | null;
}

export interface KeyOut {
  id: string;
  verification_method_id: string;
  public_key_multibase: string;
  state: string;
  activated_at: string | null;
  retired_at: string | null;
  revoked_at: string | null;
  destroyed_at: string | null;
  is_dev: boolean;
}

/** The Canvas course this session was launched from (LTI sessions only). */
export interface LaunchCourseOut {
  id: string;
  title: string;
  course_code: string | null;
  canvas_course_id: string;
  status: string;
  roles: string[];
  view: "lecturer" | "student";
  ended_at: string | null;
  read_until: string | null;
}

/** Rule E: an authorised lecturer or administrator confirms completion for the learner. */
export interface ManualApproval {
  id?: string | null;
  type?: "manual_approval";
  instructions?: string | null;
}

export interface ManualAwardIn {
  definition_id: string;
  user_id: string;
  justification: string;
  evidence?: Evidence[];
}

export interface MeOut {
  id: string;
  display_name: string | null;
  email: string | null;
  institution: InstitutionOut;
  memberships: MembershipOut[];
  session_method: string;
  launch_course: LaunchCourseOut | null;
  canvas_admin_without_access: boolean;
  institution_admins: string[];
  is_student: boolean;
  is_staff: boolean;
  is_admin: boolean;
  is_inst_admin: boolean;
  may_review: boolean;
  help: HelpOut;
}

export interface MembershipOut {
  role: "student" | "lecturer" | "course_admin" | "issuer_manager" | "reviewer" | "dept_admin" | "inst_admin";
  scope_type: "institution" | "org_unit" | "issuer" | "course";
  scope_id: string;
  scope_name: string | null;
}

/** Rule A: a Canvas module is reported complete for the learner. */
export interface ModuleCompleted {
  id?: string | null;
  type?: "module_completed";
  module_id: string;
}

/** Rule B: every module in a collection is reported complete. */
export interface ModulesCompleted {
  id?: string | null;
  type?: "modules_completed";
  module_ids: string[];
}

export interface OAuthStartOut {
  authorize_url: string;
}

export interface OrgUnitIn {
  name: string;
  kind: "faculty" | "department" | "programme" | "service" | "other";
  parent_id?: string | null;
}

export interface OrgUnitPatch {
  name?: string | null;
  kind?: "faculty" | "department" | "programme" | "service" | "other" | null;
  parent_id?: string | null;
  may_issue?: boolean | null;
  status?: "active" | "archived" | null;
  review_policy?: Record<string, unknown> | null;
}

export interface OwnerIn {
  user_id: string;
}

export interface ReasonIn {
  reason: string;
}

export interface RetentionIn {
  snapshot_days_after_course_end?: number | null;
  sync_days_after_course_end?: number | null;
  evaluation_days?: number | null;
  failed_job_days?: number | null;
  audit_event_years?: number | null;
}

export interface ReviewIn {
  checklist?: Record<string, boolean>;
  comment?: string | null;
  credit_claim_approved?: boolean | null;
}

export interface ReviewOut {
  id: string;
  version_id: string;
  reviewer: string | null;
  decision: string;
  checklist: Record<string, unknown>;
  comment: string | null;
  created_at: string;
  without_review: boolean;
}

/** How the working version would be reviewed if submitted now. */
export interface ReviewRequirement {
  mode: "required" | "author_decides" | "not_required";
  area_mode: "required" | "author_decides" | "not_required";
  /** The safeguard that makes review required, if any */
  forced_by: "assessed" | "credit" | null;
  /** The area whose setting applies (null: the institution) */
  set_by_org_unit_id: string | null;
  self_approval_allowed: boolean;
}

export interface RevocationRequestIn {
  reason: string;
}

export interface RevokeIn {
  reason_code: "issued_in_error" | "academic_misconduct" | "requirements_not_met" | "learner_request" | "other";
  reason_text: string;
}

export interface RevokeOut {
  credential_id: string;
  state: string;
  changed: boolean;
  status_list_published: boolean;
}

export interface RuleApprovalIn {
  user_id: string;
  rule_id: string;
  decision: string;
  note?: string | null;
}

/** Rule F (top level): ALL or ANY of up to :data:`MAX_RULES` rules. */
export interface RuleSet {
  mode: "ALL" | "ANY";
  rules: (ModuleCompleted | ModulesCompleted | AssignmentSubmitted | AssignmentScore | ManualApproval | Group)[];
}

export interface SessionOut {
  token: string;
  expires_at: string;
  renewable_until: string;
}

export interface ShareIn {
  show_name?: boolean;
  show_evidence?: boolean;
}

export interface ShareOut {
  share: ShareState;
  linkedin: Record<string, unknown>;
  preview: SharePreview;
}

export interface SharePreview {
  public: Record<string, unknown>;
  visible: Record<string, string>[];
  never_shared: string[];
  search_engines: string;
  withdrawing: string;
}

export interface ShareState {
  shared: boolean;
  url: string | null;
  show_name: boolean;
  show_evidence: boolean;
  shared_since: string | null;
}

export interface Skill {
  name: string;
  framework?: string | null;
  code?: string | null;
  url?: string | null;
}

export interface StarterTemplatesIn {
  org_unit_id?: string | null;
}

export interface SubmitIn {
  /** Where the area lets the author decide: ask a colleague (default) or skip */
  review?: "colleague" | "skip" | null;
}

export interface SubmitOut {
  state: string;
  warnings: Issue[];
}

export interface TeamMemberIn {
  role: "editor" | "awarder";
}

/** Draft fields a template pre-fills, plus artwork conventions (not a draft field). */
export interface TemplateDefaults {
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
  /** automatic | lecturer_confirmed | manual | null (default) */
  award_policy?: string | null;
  artwork?: ArtworkConvention | null;
}

export interface TemplatePatch {
  name?: string | null;
  description?: string | null;
  defaults?: TemplateDefaults | null;
  status?: "active" | "archived" | null;
}

export interface UploadIn {
  media_type: "image/svg+xml" | "image/png";
  data_base64: string;
  alt_text: string;
  licence?: string | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input: unknown;
  ctx: Record<string, unknown>;
}

export interface VerifyOut {
  result: string;
  label: string;
  checks: CheckOut[];
  issuer: Record<string, unknown> | null;
  achievement: Record<string, unknown> | null;
  credential_id: string | null;
  valid_from: string | null;
  valid_until: string | null;
  issuer_trust: Record<string, unknown>;
  explanation: string;
  checked_at: string;
}

export interface VersionOut {
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
  skills: Record<string, unknown>[];
  asset_id: string | null;
  award_policy: string | null;
  credit_claim_approved: boolean;
  content_hash: string | null;
  published_at: string | null;
}

/**
 * Why and when the holder's badge stopped counting (revoked or suspended).
 *
 * The reason category only: the explanation staff write stays in the record (spec §8.5).
 */
export interface Withdrawal {
  state: "revoked" | "suspended";
  on: string | null;
  reason_code: string | null;
  issuer_name: string;
}
