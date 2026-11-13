// SPDX-License-Identifier: AGPL-3.0-or-later
/** "Create Micro-Credential": a guided, step-by-step draft editor (spec §5.1, §13.1). */
import {
  NumberInput,
  Alert,
  Button,
  Flex,
  Heading,
  Img,
  List,
  RadioInput,
  RadioInputGroup,
  SimpleSelect,
  Text,
  TextArea,
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
  type CanvasAssignment,
  type CanvasModule,
  type Catalogue,
  type Course,
  type Definition,
  type DraftFields,
  type IssuerRef,
  type RuleSet,
  type Skill,
} from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Loading, Page } from "../components/Page";
import { hasScoreRule, RuleBuilder, ruleProblems } from "../components/RuleBuilder";

export const STEPS = [
  "Course and issuer",
  "About the badge",
  "Outcomes and criteria",
  "Artwork",
  "Requirements",
  "Awarding",
  "Check and save",
] as const;

const STAFF_COURSE_ROLES = new Set(["lecturer", "course_admin", "admin"]);

interface FormState {
  course_id: string;
  issuer_id: string;
  fields: Required<Pick<DraftFields, "title" | "short_description" | "description" | "criteria_narrative">> & {
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
      learning_outcomes: v.learning_outcomes.length ? v.learning_outcomes : [""],
      skills: v.skills,
      asset_id: v.asset_id,
      award_policy: v.award_policy ?? "",
    },
    rules: d.rules ?? { mode: "ALL", rules: [] },
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

/** Per-step checks so the lecturer fixes problems where they are, not at the end. */
export function stepProblems(step: number, s: FormState, catalogue?: Catalogue): string[] {
  const f = s.fields;
  const out: string[] = [];
  if (step === 0 && !s.issuer_id) out.push("Choose the issuer that will award this badge.");
  if (step === 1) {
    if (!f.title?.trim()) out.push("Give the badge a title.");
    if (!f.short_description?.trim()) out.push("Add a short description.");
    if (!f.category) out.push("Choose a category.");
    const competency = catalogue?.competency_categories.includes(f.category);
    if (competency && !["demonstrating", "assessed"].includes(f.demonstration_kind))
      out.push(
        "A competency badge must be earned by demonstrating competence or assessed proficiency, not by attending or completing.",
      );
  }
  if (step === 2) {
    if (!f.learning_outcomes.some((o) => o.trim())) out.push("Add at least one learning outcome.");
    if (!f.criteria_narrative?.trim()) out.push("Describe the criteria in words.");
  }
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
    queryFn: () => apiFetch<ArtworkTemplate[]>("/api/v1/artwork-templates", token),
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
  const [label, setLabel] = useState(defaultLabel.slice(0, 14));
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
          <Img src={shown.data_url} alt={shown.alt_text} width="8rem" height="8rem" constrain="contain" />
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
          <SimpleSelect renderLabel="Template" value={template} onChange={(_e, { value }) => setTemplate(String(value))}>
            {(templates.data ?? []).map((t) => (
              <SimpleSelect.Option key={t.key} id={`tpl-${t.key}`} value={t.key}>
                {`${t.name} (${t.licence})`}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
          <Flex gap="small" margin="small 0">
            <TextInput renderLabel="Main colour (hex)" value={primary} width="9rem" onChange={(_e, v) => setPrimary(v)} />
            <TextInput
              renderLabel="Accent colour (hex)"
              value={secondary}
              width="9rem"
              onChange={(_e, v) => setSecondary(v)}
            />
            <TextInput renderLabel="Short label" value={label} maxLength={14} onChange={(_e, v) => setLabel(v)} />
          </Flex>
        </View>
      ) : (
        <View as="div" margin="small 0" display="block">
          <label htmlFor="artwork-file">
            <Text weight="bold">Image file</Text>
          </label>
          <Text as="p" size="small">
            SVG up to 200 KB or PNG up to 1 MB, square, at least 400 by 400 pixels. Scripts, external links and
            embedded text in the file are removed.
          </Text>
          <input id="artwork-file" ref={fileRef} type="file" accept="image/svg+xml,image/png" />
        </View>
      )}
      <TextInput
        renderLabel="Alternative text (describe the artwork for people who cannot see it)"
        value={alt}
        maxLength={250}
        onChange={(_e, v) => setAlt(v)}
      />
      <Button margin="small 0" color="secondary" onClick={() => make.mutate()} interaction={make.isPending ? "disabled" : "enabled"}>
        {mode === "template" ? "Create artwork" : "Upload artwork"}
      </Button>
      {make.isError && (
        <Alert variant="error" margin="small 0">
          {make.error instanceof Error && !("problem" in make.error) ? make.error.message : problemText(make.error)}
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

  const existing = useQuery({
    queryKey: ["achievement", id],
    enabled: editing,
    queryFn: () => apiFetch<Definition>(`/api/v1/achievements/${id}`, token),
  });
  const loaded = useRef(false);
  useEffect(() => {
    if (existing.data && !loaded.current) {
      loaded.current = true;
      setS(fromDefinition(existing.data));
    }
  }, [existing.data]);

  const catalogue = useQuery({
    queryKey: ["categories"],
    queryFn: () => apiFetch<Catalogue>("/api/v1/categories", token),
  });
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetch<Course[]>("/api/v1/courses", token) });
  const staffCourses = useMemo(
    () => (courses.data ?? []).filter((c) => c.roles.some((r) => STAFF_COURSE_ROLES.has(r))),
    [courses.data],
  );
  // With exactly one choice, preselect it (derived, so nothing is stored until the user changes it).
  const courseId = s.course_id || (!editing && staffCourses.length === 1 ? staffCourses[0].id : "");
  const issuers = useQuery({
    queryKey: ["issuers", courseId],
    enabled: !!courseId,
    queryFn: () => apiFetch<IssuerRef[]>(`/api/v1/courses/${courseId}/issuers`, token),
  });
  const issuerId = s.issuer_id || (!editing && issuers.data?.length === 1 ? issuers.data[0].id : "");
  const st: FormState = { ...s, course_id: courseId, issuer_id: issuerId };
  const modules = useQuery({
    queryKey: ["modules", st.course_id],
    enabled: !!st.course_id,
    queryFn: () => apiFetch<{ items: CanvasModule[] }>(`/api/v1/courses/${st.course_id}/canvas/modules`, token),
  });
  const assignments = useQuery({
    queryKey: ["assignments", st.course_id],
    enabled: !!st.course_id,
    queryFn: () =>
      apiFetch<{ items: CanvasAssignment[] }>(`/api/v1/courses/${st.course_id}/canvas/assignments`, token),
  });

  const save = useMutation({
    mutationFn: async () => {
      const fields = toDraftFields(s.fields);
      const rules = s.rules.rules.length ? s.rules : null;
      if (editing) {
        await apiSend<Definition>(`/api/v1/achievements/${id}`, token, "PATCH", fields);
        if (rules) return apiSend<Definition>(`/api/v1/achievements/${id}/rules`, token, "PUT", rules);
        return apiFetch<Definition>(`/api/v1/achievements/${id}`, token);
      }
      return apiSend<Definition>("/api/v1/achievements", token, "POST", {
        issuer_id: st.issuer_id,
        course_id: st.course_id || null,
        fields,
        rules,
      });
    },
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["achievements"] });
      qc.setQueryData(["achievement", d.id], d);
      navigate(`/badges/${d.id}`);
    },
  });

  const go = (to: number) => {
    if (to > step) {
      const problems = stepProblems(step, st, catalogue.data);
      setShownProblems(problems);
      if (problems.length) return;
    } else setShownProblems([]);
    setStep(to);
    requestAnimationFrame(() => headingRef.current?.focus());
  };

  if (editing && existing.isPending) return <Loading what="badge" />;
  if (editing && existing.isError) return <ErrorAlert error={existing.error} />;
  if (editing && existing.data && !(existing.data.can_edit && existing.data.state === "draft"))
    return (
      <Page title="Edit badge">
        <Alert variant="info">Only drafts can be edited. Create a new version of a published badge to change it.</Alert>
      </Page>
    );

  const f = s.fields;
  const setF = (patch: Partial<FormState["fields"]>) => setS((p) => ({ ...p, fields: { ...p.fields, ...patch } }));
  const cat = catalogue.data;
  const score = hasScoreRule(s.rules);

  return (
    <Page title={editing ? "Edit micro-credential" : "Create micro-credential"}>
      <nav aria-label="Steps">
        <List isUnstyled delimiter="none" margin="0 0 medium">
          {STEPS.map((name, i) => (
            <List.Item key={name}>
              <Text weight={i === step ? "bold" : "normal"} aria-current={i === step ? "step" : undefined}>
                {i + 1}. {name}
                {i < step ? " (done)" : ""}
              </Text>
            </List.Item>
          ))}
        </List>
      </nav>
      <Heading level="h2" margin="0 0 small" elementRef={(el) => (headingRef.current = el as HTMLHeadingElement)} tabIndex={-1}>
        Step {step + 1} of {STEPS.length}: {STEPS[step]}
      </Heading>
      {shownProblems.length > 0 && (
        <Alert variant="error" margin="0 0 small">
          <Text weight="bold">Please fix the following:</Text>
          <List>
            {shownProblems.map((p) => (
              <List.Item key={p}>{p}</List.Item>
            ))}
          </List>
        </Alert>
      )}

      {step === 0 && (
        <View as="div" display="block">
          {courses.isError && <ErrorAlert error={courses.error} />}
          <SimpleSelect
            renderLabel="Course"
            value={st.course_id || undefined}
            placeholder="Choose a course"
            interaction={editing ? "readonly" : "enabled"}
            onChange={(_e, { value }) => setS((p) => ({ ...p, course_id: String(value), issuer_id: "" }))}
          >
            {staffCourses.map((c) => (
              <SimpleSelect.Option key={c.id} id={`course-${c.id}`} value={c.id}>
                {c.title}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
          <View as="div" margin="small 0" display="block">
            <SimpleSelect
              renderLabel="Issuer"
              value={st.issuer_id || undefined}
              placeholder={st.course_id ? "Choose an issuer" : "Choose a course first"}
              interaction={editing ? "readonly" : "enabled"}
              onChange={(_e, { value }) => setS((p) => ({ ...p, issuer_id: String(value) }))}
            >
              {(issuers.data ?? []).map((i) => (
                <SimpleSelect.Option key={i.id} id={`issuer-${i.id}`} value={i.id}>
                  {i.name}
                </SimpleSelect.Option>
              ))}
            </SimpleSelect>
            {st.course_id && issuers.data?.length === 0 && (
              <Alert variant="warning" margin="small 0">
                No issuer is set up to award badges in this course. Ask your department administrator.
              </Alert>
            )}
          </View>
        </View>
      )}

      {step === 1 && cat && (
        <View as="div" display="block">
          <TextInput renderLabel="Title" value={f.title ?? ""} maxLength={120} onChange={(_e, v) => setF({ title: v })} />
          <TextArea
            label="Short description (shown on the badge card, up to 280 characters)"
            maxHeight="8rem"
            value={f.short_description ?? ""}
            onChange={(e) => setF({ short_description: e.target.value })}
          />
          <TextArea
            label="Full description (optional)"
            value={f.description ?? ""}
            onChange={(e) => setF({ description: e.target.value })}
          />
          <SimpleSelect
            renderLabel="Category"
            value={f.category || undefined}
            placeholder="Choose a category"
            onChange={(_e, { value }) => setF({ category: String(value) })}
          >
            {cat.categories.map((c) => (
              <SimpleSelect.Option key={c} id={`cat-${c}`} value={c}>
                {c}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
          <Text as="p" size="small">
            Completion, participation and attendance badges record that something was done. Competency and skills
            badges claim that something can be done, so they need assessed evidence.
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
            renderLabel="Credential type"
            value={f.achievement_type}
            onChange={(_e, { value }) => setF({ achievement_type: String(value) })}
          >
            {cat.achievement_types.map((t) => (
              <SimpleSelect.Option key={t} id={`type-${t}`} value={t}>
                {t}
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
                    setF({ learning_outcomes: f.learning_outcomes.map((x, j) => (j === i ? v : x)) })
                  }
                />
              </Flex.Item>
              {f.learning_outcomes.length > 1 && (
                <Button
                  size="small"
                  onClick={() => setF({ learning_outcomes: f.learning_outcomes.filter((_, j) => j !== i) })}
                >
                  Remove outcome {i + 1}
                </Button>
              )}
            </Flex>
          ))}
          <Button
            size="small"
            interaction={f.learning_outcomes.length >= 12 ? "disabled" : "enabled"}
            onClick={() => setF({ learning_outcomes: [...f.learning_outcomes, ""] })}
          >
            Add outcome
          </Button>
          <TextArea
            label="Criteria: what a learner must do, in plain words"
            value={f.criteria_narrative ?? ""}
            onChange={(e) => setF({ criteria_narrative: e.target.value })}
          />
          <TextArea
            label="Evidence: what the credential records as evidence (optional)"
            value={f.evidence_description}
            onChange={(e) => setF({ evidence_description: e.target.value })}
          />
          <Heading level="h3" margin="small 0 0">
            Skills (optional)
          </Heading>
          {f.skills.map((k, i) => (
            <Flex key={i} gap="small" alignItems="end" margin="0 0 x-small">
              <TextInput
                renderLabel={`Skill ${i + 1}`}
                value={k.name}
                onChange={(_e, v) => setF({ skills: f.skills.map((x, j) => (j === i ? { ...x, name: v } : x)) })}
              />
              <TextInput
                renderLabel="Framework (optional)"
                value={k.framework ?? ""}
                onChange={(_e, v) =>
                  setF({ skills: f.skills.map((x, j) => (j === i ? { ...x, framework: v || null } : x)) })
                }
              />
              <Button size="small" onClick={() => setF({ skills: f.skills.filter((_, j) => j !== i) })}>
                Remove skill {i + 1}
              </Button>
            </Flex>
          ))}
          <Button size="small" onClick={() => setF({ skills: [...f.skills, { name: "" }] })}>
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
              This badge is not tied to a course, so it can only be awarded by lecturer confirmation.
            </Alert>
          ) : (
            <Text as="p">
              Requirements are checked against Canvas data. A requirement is only confirmed when Canvas says so;
              missing, excused or unreleased marks stay pending and never award a badge.
            </Text>
          )}
          {(modules.isError || assignments.isError) && <ErrorAlert error={modules.error ?? assignments.error} />}
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
          description="When a learner meets the requirements"
          value={f.award_policy}
          onChange={(_e, v) => setF({ award_policy: v })}
        >
          <RadioInput
            value=""
            label={
              score
                ? "Use the institution's default for score-based badges"
                : "Use the default (award automatically)"
            }
          />
          <RadioInput value="automatic" label={POLICY_LABELS.automatic} />
          <RadioInput value="lecturer_confirmed" label={POLICY_LABELS.lecturer_confirmed} />
          <RadioInput value="manual" label={POLICY_LABELS.manual} />
        </RadioInputGroup>
      )}

      {step === 6 && (
        <View as="div" display="block">
          <List>
            <List.Item>Title: {f.title || "(not set)"}</List.Item>
            <List.Item>Category: {f.category || "(not set)"}</List.Item>
            <List.Item>Learning outcomes: {f.learning_outcomes.filter((o) => o.trim()).length}</List.Item>
            <List.Item>Artwork: {f.asset_id ? "added" : "not added yet"}</List.Item>
            <List.Item>
              Requirements: {s.rules.rules.length} ({s.rules.mode === "ALL" ? "all required" : "any one"})
            </List.Item>
            <List.Item>
              Awarding: {f.award_policy ? POLICY_LABELS[f.award_policy] : "institution default"}
            </List.Item>
          </List>
          <Text as="p">
            Saving keeps this as a draft. You can preview it, then submit it for review from the badge page. Nothing
            is issued until it is approved and published.
          </Text>
          {save.isError && <ErrorAlert error={save.error} />}
        </View>
      )}

      <Flex gap="small" margin="medium 0 0">
        {step > 0 && <Button onClick={() => go(step - 1)}>Back</Button>}
        {step < STEPS.length - 1 ? (
          <Button color="primary" onClick={() => go(step + 1)}>
            Next
          </Button>
        ) : (
          <Button color="primary" onClick={() => save.mutate()} interaction={save.isPending ? "disabled" : "enabled"}>
            Save draft
          </Button>
        )}
      </Flex>
    </Page>
  );
}
