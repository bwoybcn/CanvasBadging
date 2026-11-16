// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * "Create Micro-Credential": a guided, step-by-step draft editor (spec §5.1, §13.1).
 *
 * The draft is saved as the author goes: it is created when they leave "About the badge" (the
 * first step with something worth keeping) and saved again each time they choose Next or Back,
 * and when they leave the wizard. Nothing waits for the last step, so a time-out, a closed tab
 * or a wrong click costs at most the step in hand.
 */
import {
  NumberInput,
  Alert,
  Button,
  Flex,
  Heading,
  Img,
  Link,
  List,
  RadioInput,
  RadioInputGroup,
  SimpleSelect,
  Text,
  TextInput,
  View,
} from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  apiFetch,
  apiSend,
  POLICY_LABELS,
  problemText,
  type ArtworkTemplate,
  type Asset,
  type BadgeTemplate,
  type CanvasAssignment,
  type CanvasModule,
  type Catalogue,
  type Course,
  type Definition,
  type DraftFields,
  type IssuerRef,
  type RuleSet,
  type Skill,
  ApiError,
} from "../api";
import { useAuth } from "../auth";
import { CanvasRefresh } from "../components/CanvasRefresh";
import { ChoiceSelect } from "../components/ChoiceSelect";
import { ColourField, LimitedTextArea } from "../components/Fields";
import { ErrorAlert, Loading, Page } from "../components/Page";
import {
  hasScoreRule,
  RuleBuilder,
  ruleProblems,
} from "../components/RuleBuilder";

/** Open Badges achievement types in plain words (the stored value stays the standard one). */
export const ACHIEVEMENT_TYPE_LABELS: Record<string, string> = {
  Achievement: "Achievement",
  Assessment: "Assessment",
  Award: "Award",
  Badge: "Badge",
  Certificate: "Certificate",
  Competency: "Competency",
  CoCurricular: "Co-curricular activity",
  Course: "Course",
  LearningProgram: "Learning programme",
  MicroCredential: "Short accredited course",
};

export const STEPS = [
  "Course and issuer",
  "About the badge",
  "Outcomes and criteria",
  "Artwork",
  "Requirements",
  "Awarding",
  "Check and save",
] as const;

interface FormState {
  course_id: string;
  issuer_id: string;
  template_id?: string; // unset or "" = start from scratch
  fields: Required<
    Pick<
      DraftFields,
      "title" | "short_description" | "description" | "criteria_narrative"
    >
  > & {
    category: string;
    achievement_type: string;
    demonstration_kind: string;
    evidence_description: string;
    validity_days: string;
    learning_outcomes: string[];
    skills: Skill[];
    asset_id: string | null;
    award_policy: string; // "" = institution default
  };
  rules: RuleSet;
}

const EMPTY: FormState = {
  course_id: "",
  issuer_id: "",
  template_id: "",
  fields: {
    title: "",
    short_description: "",
    description: "",
    criteria_narrative: "",
    category: "",
    achievement_type: "Badge",
    demonstration_kind: "completing",
    evidence_description: "",
    validity_days: "",
    learning_outcomes: [""],
    skills: [],
    asset_id: null,
    award_policy: "",
  },
  rules: { mode: "ALL", rules: [] },
};

function fromDefinition(d: Definition): FormState {
  const v = d.working_version;
  return {
    course_id: d.course_id ?? "",
    issuer_id: d.issuer.id ?? "",
    template_id: "",
    fields: {
      title: v.title,
      short_description: v.short_description,
      description: v.description,
      criteria_narrative: v.criteria_narrative,
      category: v.category,
      achievement_type: v.achievement_type,
      demonstration_kind: v.demonstration_kind,
      evidence_description: v.evidence_description ?? "",
      validity_days: v.validity_days ? String(v.validity_days) : "",
      learning_outcomes: v.learning_outcomes.length
        ? v.learning_outcomes
        : [""],
      skills: v.skills,
      asset_id: v.asset_id,
      award_policy: v.award_policy ?? "",
    },
    rules: d.rules ?? { mode: "ALL", rules: [] },
  };
}

/** Fills the form from a badge template's defaults, so the author sees (and replaces) its wording. */
export function fromTemplate(t: BadgeTemplate, current: FormState): FormState {
  const d = t.defaults as Partial<DraftFields> & Record<string, unknown>;
  const str = (k: keyof FormState["fields"], v: unknown) =>
    typeof v === "string" ? { [k]: v } : {};
  return {
    ...current,
    template_id: t.id,
    fields: {
      ...EMPTY.fields,
      ...str("title", d.title),
      ...str("short_description", d.short_description),
      ...str("description", d.description),
      ...str("criteria_narrative", d.criteria_narrative),
      ...str("category", d.category),
      ...str("achievement_type", d.achievement_type),
      ...str("demonstration_kind", d.demonstration_kind),
      ...str("evidence_description", d.evidence_description),
      ...str("award_policy", d.award_policy),
      validity_days:
        typeof d.validity_days === "number" ? String(d.validity_days) : "",
      learning_outcomes:
        Array.isArray(d.learning_outcomes) && d.learning_outcomes.length
          ? d.learning_outcomes
          : [""],
      skills: Array.isArray(d.skills) ? d.skills : [],
      asset_id: current.fields.asset_id,
    },
  };
}

/** Converts the form into the API's draft fields (blank strings become "not set"). */
export function toDraftFields(f: FormState["fields"]): DraftFields {
  const s = (x: string) => (x.trim() ? x.trim() : null);
  return {
    title: s(f.title ?? ""),
    short_description: s(f.short_description ?? ""),
    description: s(f.description ?? ""),
    criteria_narrative: s(f.criteria_narrative ?? ""),
    category: s(f.category),
    achievement_type: s(f.achievement_type),
    demonstration_kind: s(f.demonstration_kind),
    evidence_description: s(f.evidence_description),
    validity_days: f.validity_days ? Number(f.validity_days) : null,
    learning_outcomes: f.learning_outcomes.map((o) => o.trim()).filter(Boolean),
    skills: f.skills.filter((k) => k.name.trim()),
    asset_id: f.asset_id,
    award_policy: (f.award_policy || null) as DraftFields["award_policy"],
  };
}

/** Template wording such as "[Scheme name]" that the author has not replaced yet. */
export const hasPlaceholder = (x: string | null | undefined) =>
  /\[[^\]]+\]/.test(x ?? "");

/**
 * A label for the artwork from the badge title: whole words of letters and digits, up to 14
 * characters. Cutting the title at 14 characters left half words, emoji and "<" on the badge.
 */
export function shortLabel(title: string, max = 14): string {
  const words = title.match(/[\p{L}\p{N}][\p{L}\p{N}'’.&-]*/gu) ?? [];
  let out = "";
  for (const w of words) {
    const next = out ? `${out} ${w}` : w;
    if (next.length > max) break;
    out = next;
  }
  return out || (words[0] ?? "").slice(0, max);
}

/** Per-step checks so the author fixes problems where they are, not at the end. */
export function stepProblems(
  step: number,
  s: FormState,
  catalogue?: Catalogue,
): string[] {
  const f = s.fields;
  const out: string[] = [];
  if (step === 0 && !s.course_id)
    out.push("Choose the course this badge belongs to.");
  if (step === 0 && !s.issuer_id)
    out.push("Choose the issuer that will award this badge.");
  if (step === 1) {
    if (!f.title?.trim()) out.push("Give the badge a title.");
    if (!f.short_description?.trim()) out.push("Add a short description.");
    if (!f.category) out.push("Choose a category.");
    if ([f.title, f.short_description, f.description].some(hasPlaceholder))
      out.push(
        "Replace the template text in [square brackets] with your own details.",
      );
    const competency = catalogue?.competency_categories.includes(f.category);
    if (
      competency &&
      !["demonstrating", "assessed"].includes(f.demonstration_kind)
    )
      out.push(
        "A competency badge must be earned by demonstrating competence or assessed proficiency, not by attending or completing.",
      );
  }
  if (step === 2) {
    if (!f.learning_outcomes.some((o) => o.trim()))
      out.push("Add at least one learning outcome.");
    if (!f.criteria_narrative?.trim())
      out.push("Describe the criteria in words.");
    if (
      [
        f.criteria_narrative,
        f.evidence_description,
        ...f.learning_outcomes,
      ].some(hasPlaceholder)
    )
      out.push(
        "Replace the template text in [square brackets] with your own details.",
      );
  }
  if (step === 3 && !f.asset_id)
    out.push(
      "Add the badge artwork: choose a template and select Create artwork, or upload an image.",
    );
  if (step === 4) out.push(...ruleProblems(s.rules));
  return out;
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function ArtworkStep({
  assetId,
  onAsset,
  defaultLabel,
}: {
  assetId: string | null;
  onAsset: (a: Asset) => void;
  defaultLabel: string;
}) {
  const { token } = useAuth();
  const templates = useQuery({
    queryKey: ["artwork-templates"],
    queryFn: () =>
      apiFetch<ArtworkTemplate[]>("/api/v1/artwork-templates", token),
  });
  const current = useQuery({
    queryKey: ["asset", assetId],
    enabled: !!assetId,
    queryFn: () => apiFetch<Asset>(`/api/v1/assets/${assetId}`, token),
  });
  const [mode, setMode] = useState<"template" | "upload">("template");
  const [template, setTemplate] = useState("shield");
  const [primary, setPrimary] = useState("#1f4e79");
  const [secondary, setSecondary] = useState("#f2c14e");
  const [label, setLabel] = useState(shortLabel(defaultLabel));
  const [alt, setAlt] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const make = useMutation({
    mutationFn: async () => {
      if (mode === "template")
        return apiSend<Asset>("/api/v1/assets/from-template", token, "POST", {
          template,
          primary_colour: primary,
          secondary_colour: secondary,
          label,
          alt_text: alt,
        });
      const file = fileRef.current?.files?.[0];
      if (!file) throw new Error("Choose a file first.");
      const media = file.type === "image/png" ? "image/png" : "image/svg+xml";
      return apiSend<Asset>("/api/v1/assets", token, "POST", {
        media_type: media,
        data_base64: await readFileAsBase64(file),
        alt_text: alt,
      });
    },
    onSuccess: (a) => {
      setWarnings(a.warnings);
      onAsset(a);
    },
  });

  const shown = make.data ?? current.data;
  return (
    <View as="div" display="block">
      {shown?.data_url && (
        <Flex gap="medium" alignItems="center" margin="0 0 medium">
          <Img
            src={shown.data_url}
            alt={shown.alt_text}
            width="8rem"
            height="8rem"
            constrain="contain"
          />
          <Text>
            Current artwork. Alternative text: <q>{shown.alt_text}</q>
          </Text>
        </Flex>
      )}
      <RadioInputGroup
        name="artwork-mode"
        description="Artwork source"
        value={mode}
        layout="columns"
        onChange={(_e, v) => setMode(v as "template" | "upload")}
      >
        <RadioInput value="template" label="Start from a template" />
        <RadioInput value="upload" label="Upload SVG or PNG" />
      </RadioInputGroup>
      {mode === "template" ? (
        <View as="div" margin="small 0" display="block">
          <ChoiceSelect
            label="Template"
            value={template}
            placeholder="Choose a template"
            options={(templates.data ?? []).map((t) => ({
              value: t.key,
              label: t.name,
            }))}
            onChange={setTemplate}
          />
          <ColourField
            label="Main colour"
            value={primary}
            onChange={setPrimary}
          />
          <ColourField
            label="Accent colour"
            value={secondary}
            onChange={setSecondary}
          />
          <TextInput
            renderLabel="Short label (up to 14 characters)"
            value={label}
            maxLength={14}
            width="16rem"
            onChange={(_e, v) => setLabel(v)}
          />
        </View>
      ) : (
        <View as="div" margin="small 0" display="block">
          <label htmlFor="artwork-file">
            <Text weight="bold">Image file</Text>
          </label>
          <Text as="p" size="small">
            SVG up to 200 KB or PNG up to 1 MB, square, at least 400 by 400
            pixels. Scripts, external links and embedded text in the file are
            removed.
          </Text>
          <input
            id="artwork-file"
            ref={fileRef}
            type="file"
            accept="image/svg+xml,image/png"
          />
        </View>
      )}
      <TextInput
        renderLabel="Alternative text (describe the artwork for people who cannot see it)"
        value={alt}
        maxLength={250}
        onChange={(_e, v) => setAlt(v)}
      />
      <Button
        margin="small 0"
        color="secondary"
        onClick={() => make.mutate()}
        interaction={make.isPending ? "disabled" : "enabled"}
      >
        {mode === "template" ? "Create artwork" : "Upload artwork"}
      </Button>
      {make.isError && (
        <Alert variant="error" margin="small 0">
          {make.error instanceof Error && !("problem" in make.error)
            ? make.error.message
            : problemText(make.error)}
        </Alert>
      )}
      {warnings.map((w) => (
        <Alert key={w} variant="warning" margin="small 0">
          {w}
        </Alert>
      ))}
    </View>
  );
}

export function CreateBadge() {
  const { id } = useParams();
  const editing = !!id;
  const { token } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [s, setS] = useState<FormState>(EMPTY);
  const [shownProblems, setShownProblems] = useState<string[]>([]);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const problemsRef = useRef<HTMLDivElement | null>(null);
  /** The saved draft this wizard writes to: the one being edited, or the one it created. */
  const [draftId, setDraftId] = useState<string | null>(id ?? null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  /** What the server last accepted, so an unchanged step is not saved (or audited) again. */
  const saved = useRef({ fields: "", rules: "" });
  /** The draft as this form last saw it. If a colleague saves in between, our next save is
   * refused (409 DRAFT_CHANGED) instead of silently replacing their work. */
  const revision = useRef<string | null>(null);
  const ifMatch = () =>
    revision.current ? { "if-match": revision.current } : undefined;
  const adopt = (d: Definition) => {
    const form = fromDefinition(d);
    saved.current = {
      fields: JSON.stringify(toDraftFields(form.fields)),
      rules: JSON.stringify(form.rules),
    };
    revision.current = d.revision;
    setS(form);
  };

  const existing = useQuery({
    queryKey: ["achievement", id],
    enabled: editing,
    queryFn: () => apiFetch<Definition>(`/api/v1/achievements/${id}`, token),
  });
  const loaded = useRef(false);
  useEffect(() => {
    if (existing.data && !loaded.current) {
      loaded.current = true;
      adopt(existing.data);
    }
  }, [existing.data]);

  const catalogue = useQuery({
    queryKey: ["categories"],
    queryFn: () => apiFetch<Catalogue>("/api/v1/categories", token),
  });
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => apiFetch<Course[]>("/api/v1/courses", token),
  });
  const staffCourses = useMemo(
    () =>
      // The server says which courses this person works on the badges of.
      (courses.data ?? []).filter((c) => c.staff),
    [courses.data],
  );
  // With exactly one choice, preselect it (derived, so nothing is stored until the user changes it).
  const courseId =
    s.course_id ||
    (!editing && staffCourses.length === 1 ? staffCourses[0].id : "");
  const issuers = useQuery({
    queryKey: ["issuers", courseId],
    enabled: !!courseId,
    queryFn: () =>
      apiFetch<IssuerRef[]>(`/api/v1/courses/${courseId}/issuers`, token),
  });
  const issuerId =
    s.issuer_id ||
    (!editing && issuers.data?.length === 1 ? issuers.data[0].id : "");
  const st: FormState = { ...s, course_id: courseId, issuer_id: issuerId };
  // The problems shown follow the form: one that has been fixed disappears straight away, and
  // the box goes when none are left (until Next is pressed again).
  const liveProblems = shownProblems.length
    ? stepProblems(step, st, catalogue.data)
    : [];
  const badgeTemplates = useQuery({
    queryKey: ["badge-templates", courseId],
    enabled: !!courseId && !editing,
    queryFn: () =>
      apiFetch<BadgeTemplate[]>(
        `/api/v1/templates?course_id=${courseId}`,
        token,
      ),
  });
  const modules = useQuery({
    queryKey: ["modules", st.course_id],
    enabled: !!st.course_id,
    queryFn: () =>
      apiFetch<{ items: CanvasModule[] }>(
        `/api/v1/courses/${st.course_id}/canvas/modules`,
        token,
      ),
  });
  const assignments = useQuery({
    queryKey: ["assignments", st.course_id],
    enabled: !!st.course_id,
    queryFn: () =>
      apiFetch<{ items: CanvasAssignment[] }>(
        `/api/v1/courses/${st.course_id}/canvas/assignments`,
        token,
      ),
  });

  const save = useMutation({
    /** Saves what changed. `finish` (the last step) always sends everything and returns the badge. */
    mutationFn: async ({
      finish,
    }: {
      finish: boolean;
    }): Promise<Definition | null> => {
      const fields = toDraftFields(s.fields);
      const fieldsKey = JSON.stringify(fields);
      const rulesKey = JSON.stringify(s.rules);
      // Half-built requirements stay in the form until they are complete.
      const rulesReady =
        s.rules.rules.length > 0 && ruleProblems(s.rules).length === 0;
      let did = draftId;
      let d: Definition | null = null;
      if (!did) {
        d = await apiSend<Definition>("/api/v1/achievements", token, "POST", {
          issuer_id: st.issuer_id,
          course_id: st.course_id || null,
          template_id: st.template_id || null,
          fields,
          rules: null,
        });
        did = d.id;
        setDraftId(did);
        revision.current = d.revision;
        saved.current.fields = fieldsKey;
      } else if (finish || fieldsKey !== saved.current.fields) {
        d = await apiSend<Definition>(
          `/api/v1/achievements/${did}`,
          token,
          "PATCH",
          fields,
          ifMatch(),
        );
        revision.current = d.revision;
        saved.current.fields = fieldsKey;
      }
      if (rulesReady && (finish || rulesKey !== saved.current.rules)) {
        d = await apiSend<Definition>(
          `/api/v1/achievements/${did}/rules`,
          token,
          "PUT",
          s.rules,
          ifMatch(),
        );
        revision.current = d.revision;
        saved.current.rules = rulesKey;
      }
      if (!d && finish)
        d = await apiFetch<Definition>(`/api/v1/achievements/${did}`, token);
      return d;
    },
    onSuccess: (d, { finish }) => {
      setSavedAt(new Date());
      qc.invalidateQueries({ queryKey: ["achievements"] });
      if (d) qc.setQueryData(["achievement", d.id], d);
      if (finish && d) navigate(`/badges/${d.id}`);
    },
  });

  // Leaving the wizard part-way through a step (the menu, another page): keep that step too.
  const saveOnLeave = useRef<() => void>(() => undefined);
  useEffect(() => {
    saveOnLeave.current = () => {
      // No baseline means the draft has not loaded yet: there is nothing of the author's to keep,
      // and saving the empty form would wipe the draft.
      if (!draftId || !saved.current.fields) return;
      const fields = toDraftFields(s.fields);
      if (JSON.stringify(fields) === saved.current.fields) return;
      void apiSend(
        `/api/v1/achievements/${draftId}`,
        token,
        "PATCH",
        fields,
        ifMatch(),
      ).catch(() => undefined);
    };
  });
  useEffect(() => () => saveOnLeave.current(), []);

  const go = async (to: number) => {
    if (save.isPending) return;
    if (to > step) {
      const problems = stepProblems(step, st, catalogue.data);
      setShownProblems(problems);
      if (problems.length) {
        // Take the reader to the list of problems, so a screen reader reads it out and a
        // keyboard user continues from there, rather than staying on Next with no news.
        requestAnimationFrame(() => problemsRef.current?.focus());
        return;
      }
      // From "About the badge" onwards there is something worth keeping: save before moving on,
      // and stay on the step if the server refuses it, so the problem is fixed where it is.
      if (draftId || step >= 1) {
        try {
          await save.mutateAsync({ finish: false });
        } catch {
          return;
        }
      }
    } else {
      setShownProblems([]);
      if (draftId) save.mutate({ finish: false });
    }
    setStep(to);
    requestAnimationFrame(() => headingRef.current?.focus());
  };

  if (editing && existing.isPending) return <Loading what="badge" />;
  if (editing && existing.isError) return <ErrorAlert error={existing.error} />;
  if (
    editing &&
    existing.data &&
    !(existing.data.can_edit && existing.data.state === "draft")
  )
    return (
      <Page title="Edit badge">
        <Alert variant="info">
          Only drafts can be edited. Create a new version of a published badge
          to change it.
        </Alert>
      </Page>
    );

  // A saved draft can jump to any step whose earlier steps are complete, so an author editing
  // requirements does not have to page through every step (round 3, finding M4).
  const canJump = (to: number) =>
    to < step ||
    (!!draftId &&
      Array.from({ length: to }, (_, j) => j).every(
        (j) => !stepProblems(j, st, catalogue.data).length,
      ));
  const f = s.fields;
  const locked = !!draftId;
  const sessionEnded =
    save.error instanceof ApiError && save.error.problem.status === 401;
  const changedByOthers =
    save.error instanceof ApiError &&
    save.error.problem.code === "DRAFT_CHANGED";
  const loadLatest = async () => {
    if (!draftId) return;
    const d = await apiFetch<Definition>(
      `/api/v1/achievements/${draftId}`,
      token,
    );
    adopt(d);
    qc.setQueryData(["achievement", d.id], d);
    save.reset();
    setShownProblems([]);
  };
  const setF = (patch: Partial<FormState["fields"]>) =>
    setS((p) => ({ ...p, fields: { ...p.fields, ...patch } }));
  const cat = catalogue.data;
  const score = hasScoreRule(s.rules);

  return (
    <Page title={editing ? "Edit badge" : "Create a badge"}>
      <nav aria-label="Steps">
        <List isUnstyled delimiter="none" margin="0 0 medium">
          {STEPS.map((name, i) => (
            <List.Item key={name}>
              {i !== step && canJump(i) ? (
                <Link as="button" onClick={() => void go(i)}>
                  {i + 1}. {name}
                  {i < step || !stepProblems(i, st, catalogue.data).length
                    ? " (done)"
                    : ""}
                </Link>
              ) : (
                <Text
                  weight={i === step ? "bold" : "normal"}
                  aria-current={i === step ? "step" : undefined}
                >
                  {i + 1}. {name}
                </Text>
              )}
            </List.Item>
          ))}
        </List>
      </nav>
      <Heading
        level="h2"
        margin="0 0 small"
        elementRef={(el) => (headingRef.current = el as HTMLHeadingElement)}
        tabIndex={-1}
      >
        Step {step + 1} of {STEPS.length}: {STEPS[step]}
      </Heading>
      {liveProblems.length > 0 && (
        <div
          role="alert"
          tabIndex={-1}
          ref={problemsRef}
          className="oc-problems"
        >
          <Alert variant="error" margin="0 0 small">
            <Text weight="bold">Please fix the following:</Text>
            <List>
              {liveProblems.map((p) => (
                <List.Item key={p}>{p}</List.Item>
              ))}
            </List>
          </Alert>
        </div>
      )}

      {step === 0 && (
        <View as="div" display="block">
          {courses.isError && <ErrorAlert error={courses.error} />}
          <ChoiceSelect
            label="Course"
            value={st.course_id}
            placeholder="Choose a course"
            interaction={locked ? "readonly" : "enabled"}
            options={staffCourses.map((c) => ({ value: c.id, label: c.title }))}
            onChange={(value) =>
              setS((p) => ({
                ...p,
                course_id: value,
                issuer_id: "",
                template_id: "",
              }))
            }
          />
          <View as="div" margin="small 0" display="block">
            <ChoiceSelect
              label="Issuer"
              value={st.issuer_id}
              placeholder={
                st.course_id ? "Choose an issuer" : "Choose a course first"
              }
              interaction={locked ? "readonly" : "enabled"}
              options={(issuers.data ?? []).map((i) => ({
                value: i.id,
                label: i.name,
              }))}
              onChange={(value) => setS((p) => ({ ...p, issuer_id: value }))}
            />
            {st.course_id && issuers.data?.length === 0 && (
              <Alert variant="warning" margin="small 0">
                No issuer is set up to award badges in this course. Ask your
                department administrator.
              </Alert>
            )}
          </View>
          {!editing && (badgeTemplates.data?.length ?? 0) > 0 && (
            <View as="div" margin="small 0" display="block">
              <SimpleSelect
                renderLabel="Start from a badge template (optional)"
                value={st.template_id}
                interaction={locked ? "readonly" : "enabled"}
                onChange={(_e, { value }) => {
                  const t = badgeTemplates.data?.find((x) => x.id === value);
                  setS((p) =>
                    t
                      ? fromTemplate(t, p)
                      : {
                          ...p,
                          template_id: "",
                          fields: {
                            ...EMPTY.fields,
                            asset_id: p.fields.asset_id,
                          },
                        },
                  );
                }}
              >
                <SimpleSelect.Option id="tpl-none" value="">
                  No template: start from scratch
                </SimpleSelect.Option>
                {(badgeTemplates.data ?? []).map((t) => (
                  <SimpleSelect.Option
                    key={t.id}
                    id={`tpl-${t.id}`}
                    value={t.id}
                  >
                    {t.name}
                  </SimpleSelect.Option>
                ))}
              </SimpleSelect>
              {st.template_id ? (
                <Text as="p" size="small">
                  {badgeTemplates.data?.find((x) => x.id === st.template_id)
                    ?.description ?? ""}{" "}
                  The next steps are filled in from the template. Replace
                  anything in [square brackets] with your own details.
                </Text>
              ) : null}
            </View>
          )}
          {locked && !editing && (
            <Text as="p" size="small">
              The course, issuer and template are fixed now that your draft is
              saved. To change them, delete the draft from its badge page and
              start again.
            </Text>
          )}
        </View>
      )}

      {step === 1 && cat && (
        <View as="div" display="block">
          <TextInput
            renderLabel="Title"
            value={f.title ?? ""}
            maxLength={120}
            onChange={(_e, v) => setF({ title: v })}
          />
          <LimitedTextArea
            maxLength={280}
            label="Short description (shown on the badge card, up to 280 characters)"
            maxHeight="8rem"
            value={f.short_description ?? ""}
            onChange={(e) => setF({ short_description: e.target.value })}
          />
          <LimitedTextArea
            maxLength={4000}
            label="Full description (optional)"
            value={f.description ?? ""}
            onChange={(e) => setF({ description: e.target.value })}
          />
          <ChoiceSelect
            label="Category"
            value={f.category}
            placeholder="Choose a category"
            options={cat.categories.map((c) => ({ value: c, label: c }))}
            onChange={(value) => setF({ category: value })}
          />
          <Text as="p" size="small">
            Completion, participation and attendance badges record that
            something was done. Competency and skills badges claim that
            something can be done, so they need assessed evidence.
          </Text>
          <RadioInputGroup
            name="demonstration"
            description="How is the achievement demonstrated?"
            value={f.demonstration_kind}
            onChange={(_e, v) => setF({ demonstration_kind: v })}
          >
            {Object.entries(cat.demonstration_kinds).map(([k, label]) => (
              <RadioInput key={k} value={k} label={label} />
            ))}
          </RadioInputGroup>
          <SimpleSelect
            renderLabel="Badge type"
            value={f.achievement_type}
            onChange={(_e, { value }) =>
              setF({ achievement_type: String(value) })
            }
          >
            {cat.achievement_types.map((t) => (
              <SimpleSelect.Option key={t} id={`type-${t}`} value={t}>
                {ACHIEVEMENT_TYPE_LABELS[t] ?? t}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
        </View>
      )}

      {step === 2 && (
        <View as="div" display="block">
          <Heading level="h3">Learning outcomes</Heading>
          {f.learning_outcomes.map((o, i) => (
            <Flex key={i} gap="small" alignItems="end" margin="0 0 x-small">
              <Flex.Item shouldGrow>
                <TextInput
                  renderLabel={`Learning outcome ${i + 1}`}
                  value={o}
                  onChange={(_e, v) =>
                    setF({
                      learning_outcomes: f.learning_outcomes.map((x, j) =>
                        j === i ? v : x,
                      ),
                    })
                  }
                />
              </Flex.Item>
              {f.learning_outcomes.length > 1 && (
                <Button
                  size="small"
                  onClick={() =>
                    setF({
                      learning_outcomes: f.learning_outcomes.filter(
                        (_, j) => j !== i,
                      ),
                    })
                  }
                >
                  Remove outcome {i + 1}
                </Button>
              )}
            </Flex>
          ))}
          <Button
            size="small"
            interaction={
              f.learning_outcomes.length >= 12 ? "disabled" : "enabled"
            }
            onClick={() =>
              setF({ learning_outcomes: [...f.learning_outcomes, ""] })
            }
          >
            Add outcome
          </Button>
          <LimitedTextArea
            maxLength={4000}
            label="Criteria: what a student must do, in plain words"
            value={f.criteria_narrative ?? ""}
            onChange={(e) => setF({ criteria_narrative: e.target.value })}
          />
          <LimitedTextArea
            maxLength={2000}
            label="Evidence: what the badge records as evidence (optional)"
            value={f.evidence_description}
            onChange={(e) => setF({ evidence_description: e.target.value })}
          />
          <Heading level="h3" margin="small 0 0">
            Skills (optional)
          </Heading>
          {f.skills.map((k, i) => (
            <Flex key={i} gap="small" alignItems="end" margin="0 0 x-small" wrap="wrap">
              <TextInput
                maxLength={120}
                renderLabel={`Skill ${i + 1}`}
                value={k.name}
                onChange={(_e, v) =>
                  setF({
                    skills: f.skills.map((x, j) =>
                      j === i ? { ...x, name: v } : x,
                    ),
                  })
                }
              />
              <TextInput
                maxLength={120}
                renderLabel="Framework (optional)"
                value={k.framework ?? ""}
                onChange={(_e, v) =>
                  setF({
                    skills: f.skills.map((x, j) =>
                      j === i ? { ...x, framework: v || null } : x,
                    ),
                  })
                }
              />
              <TextInput
                maxLength={500}
                type="url"
                renderLabel="Link to its description (optional)"
                placeholder="https://"
                value={k.url ?? ""}
                onChange={(_e, v) =>
                  setF({
                    skills: f.skills.map((x, j) =>
                      j === i ? { ...x, url: v.trim() || null } : x,
                    ),
                  })
                }
              />
              <Button
                size="small"
                onClick={() =>
                  setF({ skills: f.skills.filter((_, j) => j !== i) })
                }
              >
                Remove skill {i + 1}
              </Button>
            </Flex>
          ))}
          <Button
            size="small"
            onClick={() => setF({ skills: [...f.skills, { name: "" }] })}
          >
            Add skill
          </Button>
          <NumberInput
            renderLabel="Valid for (days, leave empty if it does not expire)"
            showArrows={false}
            width="14rem"
            value={f.validity_days}
            onChange={(_e, v) => setF({ validity_days: v })}
          />
        </View>
      )}

      {step === 3 && (
        <ArtworkStep
          assetId={f.asset_id}
          defaultLabel={f.title ?? ""}
          onAsset={(a) => {
            setF({ asset_id: a.id });
            qc.setQueryData(["asset", a.id], a);
          }}
        />
      )}

      {step === 4 && (
        <View as="div" display="block">
          {!st.course_id ? (
            <Alert variant="info" margin="0 0 small">
              This badge is not tied to a course, so it can only be awarded by
              staff confirmation.
            </Alert>
          ) : (
            <Text as="p">
              Module, assignment and score requirements are checked against
              Canvas and count only once Canvas confirms them: missing, excused
              or unreleased marks stay pending. A &ldquo;Staff confirm&rdquo;
              requirement is met when a member of staff records it.
            </Text>
          )}
          {st.course_id && (
            <CanvasRefresh courseId={st.course_id} token={token} />
          )}
          {(modules.isError || assignments.isError) && (
            <ErrorAlert error={modules.error ?? assignments.error} />
          )}
          <RuleBuilder
            value={s.rules}
            onChange={(rules) => setS((p) => ({ ...p, rules }))}
            sources={{
              modules: modules.data?.items ?? [],
              assignments: assignments.data?.items ?? [],
              manualOnly: !st.course_id,
            }}
          />
        </View>
      )}

      {step === 5 && (
        <RadioInputGroup
          name="award-policy"
          description="When a student meets the requirements"
          value={f.award_policy}
          onChange={(_e, v) => setF({ award_policy: v })}
        >
          <RadioInput
            value=""
            label={
              score
                ? "Use the institution's default for score-based badges"
                : "Follow the institution's setting (today: award automatically)"
            }
          />
          <RadioInput value="automatic" label={POLICY_LABELS.automatic} />
          <RadioInput
            value="lecturer_confirmed"
            label={POLICY_LABELS.lecturer_confirmed}
          />
          <RadioInput value="manual" label={POLICY_LABELS.manual} />
        </RadioInputGroup>
      )}

      {step === 6 && (
        <View as="div" display="block">
          <List>
            <List.Item>Title: {f.title || "(not set)"}</List.Item>
            <List.Item>Category: {f.category || "(not set)"}</List.Item>
            <List.Item>
              Learning outcomes:{" "}
              {f.learning_outcomes.filter((o) => o.trim()).length}
            </List.Item>
            <List.Item>
              Artwork: {f.asset_id ? "added" : "not added yet"}
            </List.Item>
            <List.Item>
              Requirements: {s.rules.rules.length} (
              {s.rules.mode === "ALL" ? "all required" : "any one"})
            </List.Item>
            <List.Item>
              Awarding:{" "}
              {f.award_policy
                ? POLICY_LABELS[f.award_policy]
                : "institution default"}
            </List.Item>
          </List>
          <Text as="p">
            Save draft keeps your last changes and opens the badge page. There
            you can preview it, then submit it for review. Nothing is issued
            until it is approved and published.
          </Text>
        </View>
      )}

      {save.isError && (
        <Alert variant="error" margin="small 0">
          {problemText(save.error)}
          {sessionEnded && draftId
            ? " Everything up to the last step you finished is saved as a draft: you will find it under Badges."
            : ""}
          {changedByOthers && (
            <View as="div" margin="small 0 0">
              <Button onClick={() => void loadLatest()}>
                Load the latest version
              </Button>
            </View>
          )}
        </Alert>
      )}
      <Flex gap="small" margin="medium 0 0">
        {step > 0 && (
          <Button
            onClick={() => go(step - 1)}
            interaction={save.isPending ? "disabled" : "enabled"}
          >
            Back
          </Button>
        )}
        {step < STEPS.length - 1 ? (
          <Button
            color="primary"
            onClick={() => go(step + 1)}
            interaction={save.isPending ? "disabled" : "enabled"}
          >
            Next
          </Button>
        ) : (
          <Button
            color="primary"
            onClick={() => save.mutate({ finish: true })}
            interaction={save.isPending ? "disabled" : "enabled"}
          >
            Save draft
          </Button>
        )}
      </Flex>
      <Text as="p" size="small" role="status" data-testid="draft-status">
        {save.isPending
          ? "Saving your draft…"
          : savedAt && !save.isError
            ? `Draft saved at ${savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. You can leave and come back to it from Badges.`
            : draftId
              ? "This draft is saved each time you choose Next or Back."
              : "Your work is saved as a draft each time you choose Next, from step 2 onwards."}
      </Text>
    </Page>
  );
}
