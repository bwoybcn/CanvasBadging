// SPDX-License-Identifier: AGPL-3.0-or-later
/** Institution awarding policy (Gary's decision: per-badge choice with an admin-set default). */
import { Alert, Button, Checkbox, RadioInput, RadioInputGroup, NumberInput, Text, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend, type ReviewMode } from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Loading } from "../components/Page";
import { AdminPage } from "./admin/AdminPage";

interface Policy {
  score_rules_default_policy: "automatic" | "lecturer_confirmed";
  score_rules_force_confirmation: boolean;
  definitions_require_approval: boolean;
  definition_review: ReviewMode;
  areas_may_relax_review: boolean;
  self_approval_allowed: boolean;
  manual_awards_require_second_approval: boolean;
  max_snapshot_age_minutes: number;
  approver_roles: string[];
  revokers: string[];
  dept_admins_may_delegate: boolean;
  course_activation_required: boolean;
}

const APPROVERS: Record<string, string> = {
  dept_admin: "Department administrators (for their departments)",
  lecturer: "Course staff (for their own courses)",
};
const REVOKERS: Record<string, string> = {
  dept_admin: "Department administrators (for their departments)",
  issuer_manager: "Issuer managers (for their issuer)",
  lecturer: "Course staff (for their own courses)",
};

function RoleChecks({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: Record<string, string>;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <View as="fieldset" margin="small 0" padding="0" borderWidth="0">
      <View as="legend" margin="0 0 x-small">
        {legend}
      </View>
      <Checkbox label="Institution administrators (always)" checked disabled />
      {Object.entries(options).map(([role, label]) => (
        <Checkbox
          key={role}
          label={label}
          checked={value.includes(role)}
          onChange={(e) =>
            onChange(e.target.checked ? [...value, role] : value.filter((r) => r !== role))
          }
        />
      ))}
    </View>
  );
}

export function AdminPolicy() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["policy"],
    queryFn: () => apiFetch<Policy>("/api/v1/institutions/current/policy", token),
  });
  return (
    <AdminPage title="Approval and awarding policy" instOnly>
      {q.isError && <ErrorAlert error={q.error} />}
      {q.isPending && <Loading what="policy" />}
      {q.data && <PolicyForm initial={q.data} />}
    </AdminPage>
  );
}

function PolicyForm({ initial }: { initial: Policy }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [p, setP] = useState<Policy>(initial);
  const save = useMutation({
    mutationFn: (body: Policy) => apiSend<Policy>("/api/v1/institutions/current/policy", token, "PATCH", body),
    onSuccess: (np) => qc.setQueryData(["policy"], np),
  });
  const set = (patch: Partial<Policy>) => setP({ ...p, ...patch });
  return (
    <>
      <View as="div" display="block" maxWidth="48rem">
        <RadioInputGroup
          name="score-default"
          description="Default for badges that use assignment scores"
          value={p.score_rules_default_policy}
          onChange={(_e, v) => set({ score_rules_default_policy: v as Policy["score_rules_default_policy"] })}
        >
          <RadioInput value="lecturer_confirmed" label="A member of staff confirms each award" />
          <RadioInput value="automatic" label="Award automatically when the released mark meets the threshold" />
        </RadioInputGroup>
        <Checkbox
          label="Always require staff confirmation for score-based badges, even if the badge author chose automatic"
          checked={p.score_rules_force_confirmation}
          onChange={(e) => set({ score_rules_force_confirmation: e.target.checked })}
        />
        <RadioInputGroup
          name="definition-review"
          description="Colleague review of new and changed badges (default for the whole institution)"
          value={p.definition_review}
          onChange={(_e, v) => {
            const mode = v as ReviewMode;
            set({ definition_review: mode, definitions_require_approval: mode !== "not_required" });
          }}
        >
          <RadioInput value="required" label="Required: a reviewer approves every badge before it can be published" />
          <RadioInput value="author_decides" label="The author decides whether to ask a colleague" />
          <RadioInput value="not_required" label="Not required: badges can be published straight away" />
        </RadioInputGroup>
        <Text as="p" size="small">
          Badges that claim assessed proficiency, or whose wording refers to credit or a qualification, always need
          review.
        </Text>
        <Checkbox
          label="Faculties, departments and services may set review less strictly for themselves"
          checked={p.areas_may_relax_review}
          onChange={(e) => set({ areas_may_relax_review: e.target.checked })}
        />
        <Checkbox
          label="Authors may approve their own badges (areas can set their own rule)"
          checked={p.self_approval_allowed}
          onChange={(e) => set({ self_approval_allowed: e.target.checked })}
        />
        <RoleChecks
          legend="Who can approve badge definitions"
          options={APPROVERS}
          value={p.approver_roles}
          onChange={(v) => set({ approver_roles: v })}
        />
        <RoleChecks
          legend="Who can revoke badges"
          options={REVOKERS}
          value={p.revokers}
          onChange={(v) => set({ revokers: v })}
        />
        <Checkbox
          label="Department administrators may grant staff roles inside their own departments"
          checked={p.dept_admins_may_delegate}
          onChange={(e) => set({ dept_admins_may_delegate: e.target.checked })}
        />
        <Checkbox
          label="Courses take part only after course staff switch badges on"
          checked={p.course_activation_required}
          onChange={(e) => set({ course_activation_required: e.target.checked })}
        />
        <Checkbox
          label="Manual awards need a second member of staff to confirm (areas can set their own rule)"
          checked={p.manual_awards_require_second_approval}
          onChange={(e) => set({ manual_awards_require_second_approval: e.target.checked })}
        />
        <NumberInput
          renderLabel="Treat Canvas data as out of date after (minutes, 15 to 1440)"
          showArrows={false}
          width="12rem"
          value={String(p.max_snapshot_age_minutes)}
          onChange={(_e, v) => set({ max_snapshot_age_minutes: Number(v) })}
        />
        {save.isError && <ErrorAlert error={save.error} />}
        {save.isSuccess && (
          <Alert variant="success" margin="small 0">
            Saved. Badges published from now on use these settings; published badges keep the method they were
            published with.
          </Alert>
        )}
        <Button color="primary" margin="small 0" onClick={() => save.mutate(p)}>
          Save policy
        </Button>
      </View>
    </>
  );
}
