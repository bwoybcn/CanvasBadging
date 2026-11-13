// SPDX-License-Identifier: AGPL-3.0-or-later
/** Institution awarding policy (Gary's decision: per-badge choice with an admin-set default). */
import { Alert, Button, Checkbox, RadioInput, RadioInputGroup, NumberInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend } from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Loading, Page } from "../components/Page";

interface Policy {
  score_rules_default_policy: "automatic" | "lecturer_confirmed";
  score_rules_force_confirmation: boolean;
  definitions_require_approval: boolean;
  self_approval_allowed: boolean;
  manual_awards_require_second_approval: boolean;
  max_snapshot_age_minutes: number;
}

export function AdminPolicy() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["policy"],
    queryFn: () => apiFetch<Policy>("/api/v1/institutions/current/policy", token),
  });
  if (q.isError) return <ErrorAlert error={q.error} />;
  if (q.isPending) return <Loading what="policy" />;
  return <PolicyForm initial={q.data} />;
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
    <Page title="Awarding policy">
      <View as="div" display="block" maxWidth="48rem">
        <RadioInputGroup
          name="score-default"
          description="Default for badges that use assignment scores"
          value={p.score_rules_default_policy}
          onChange={(_e, v) => set({ score_rules_default_policy: v as Policy["score_rules_default_policy"] })}
        >
          <RadioInput value="lecturer_confirmed" label="A lecturer confirms each award" />
          <RadioInput value="automatic" label="Award automatically when the released mark meets the threshold" />
        </RadioInputGroup>
        <Checkbox
          label="Always require lecturer confirmation for score-based badges, even if the lecturer chose automatic"
          checked={p.score_rules_force_confirmation}
          onChange={(e) => set({ score_rules_force_confirmation: e.target.checked })}
        />
        <Checkbox
          label="New and changed badges must be approved before publishing"
          checked={p.definitions_require_approval}
          onChange={(e) => set({ definitions_require_approval: e.target.checked })}
        />
        <Checkbox
          label="Authors may approve their own badges"
          checked={p.self_approval_allowed}
          onChange={(e) => set({ self_approval_allowed: e.target.checked })}
        />
        <Checkbox
          label="Manual awards need a second member of staff to confirm"
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
    </Page>
  );
}
