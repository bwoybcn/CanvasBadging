// SPDX-License-Identifier: AGPL-3.0-or-later
/** Institutional badge templates (spec §10.4). */
import { Button, Heading, NumberInput, SimpleSelect, Text, TextArea, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend, type BadgeTemplate, type OrgUnit } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage } from "./AdminPage";

const EMPTY = {
  name: "",
  description: "",
  org_unit_id: "",
  title: "",
  short_description: "",
  criteria_narrative: "",
  evidence_description: "",
  validity_days: "",
  skills: "",
  category: "",
  artwork_template: "shield",
  primary_colour: "",
  artwork_guidance: "",
};

export function Templates() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin-templates"],
    queryFn: () => apiFetch<BadgeTemplate[]>("/api/v1/admin/templates?include_archived=true", token),
  });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const [v, setV] = useState(EMPTY);
  const set = (k: keyof typeof EMPTY) => (_e: unknown, x: string) => setV({ ...v, [k]: x });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-templates"] });
  const create = useMutation({
    mutationFn: () =>
      apiSend<BadgeTemplate>("/api/v1/admin/templates", token, "POST", {
        name: v.name,
        description: v.description || null,
        org_unit_id: v.org_unit_id || null,
        defaults: {
          title: v.title || undefined,
          short_description: v.short_description || undefined,
          criteria_narrative: v.criteria_narrative || undefined,
          evidence_description: v.evidence_description || undefined,
          category: v.category || undefined,
          validity_days: v.validity_days ? Number(v.validity_days) : undefined,
          skills: v.skills
            ? v.skills.split("\n").map((s) => s.trim()).filter(Boolean).map((name) => ({ name }))
            : undefined,
          artwork: {
            template: v.artwork_template || undefined,
            primary_colour: v.primary_colour || undefined,
            guidance: v.artwork_guidance || undefined,
          },
        },
      }),
    onSuccess: () => {
      setV(EMPTY);
      refresh();
    },
  });
  const archive = useMutation({
    mutationFn: (t: BadgeTemplate) =>
      apiSend(`/api/v1/admin/templates/${t.id}`, token, "PATCH", { status: t.status === "active" ? "archived" : "active" }),
    onSuccess: refresh,
  });
  const starters = useMutation({
    mutationFn: () => apiSend<BadgeTemplate[]>("/api/v1/admin/templates/starters", token, "POST", {}),
    onSuccess: refresh,
  });
  return (
    <AdminPage title="Badge templates">
      <Text as="p">
        Templates give authors a consistent starting point: wording, criteria structure, evidence expectations, artwork
        conventions, skills terms and a standard validity period. Authors can change anything before review.
      </Text>
      {q.isPending && <Loading what="templates" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {(q.data ?? []).map((t) => (
        <View key={t.id} as="div" borderWidth="small" borderRadius="medium" padding="small" margin="0 0 small" display="block">
          <Heading level="h2" margin="0">
            {t.name}
            {t.status === "archived" ? " (archived)" : ""}
          </Heading>
          <Text as="p" size="small">
            {t.org_unit_name ? `For ${t.org_unit_name}` : "Institution-wide"}
            {t.description ? ` · ${t.description}` : ""}
          </Text>
          <Text as="p" size="small">
            Pre-fills: {Object.keys(t.defaults).join(", ") || "nothing yet"}
          </Text>
          <Button size="small" onClick={() => archive.mutate(t)}>
            {t.status === "active" ? `Archive ${t.name}` : `Restore ${t.name}`}
          </Button>
        </View>
      ))}
      {archive.isError && <ErrorAlert error={archive.error} />}
      <View as="section" display="block" maxWidth="40rem" margin="medium 0 0">
        <Heading level="h2" margin="0 0 small">
          Ready-made templates
        </Heading>
        <Text as="p">
          Starting points for badges outside modules: volunteering hours, workshop attendance, event participation and
          CPD activity. Templates you already have with the same name are left alone.
        </Text>
        <Button onClick={() => starters.mutate()} interaction={starters.isPending ? "disabled" : "enabled"}>
          Add ready-made templates
        </Button>
        {starters.isSuccess && (
          <Text as="p" role="status">
            {starters.data.length
              ? `Added ${starters.data.length} template${starters.data.length === 1 ? "" : "s"}.`
              : "You already have all the ready-made templates."}
          </Text>
        )}
        {starters.isError && <ErrorAlert error={starters.error} />}
      </View>
      <View as="section" display="block" maxWidth="40rem" margin="medium 0 0">
        <Heading level="h2" margin="0 0 small">
          New template
        </Heading>
        <TextInput renderLabel="Template name" value={v.name} onChange={set("name")} />
        <TextInput renderLabel="What it is for" value={v.description} onChange={set("description")} />
        <SimpleSelect renderLabel="Available to" value={v.org_unit_id} onChange={(_e, { value }) => setV({ ...v, org_unit_id: String(value) })}>
          <SimpleSelect.Option id="t-all" value="">
            The whole institution
          </SimpleSelect.Option>
          {(units.data ?? [])
            .filter((u) => u.manageable)
            .map((u) => (
              <SimpleSelect.Option key={u.id} id={`t-${u.id}`} value={u.id}>
                {u.name}
              </SimpleSelect.Option>
            ))}
        </SimpleSelect>
        <TextInput renderLabel="Title pattern" value={v.title} onChange={set("title")} />
        <TextInput renderLabel="Short description" value={v.short_description} onChange={set("short_description")} />
        <TextInput renderLabel="Category" value={v.category} onChange={set("category")} />
        <TextArea label="Criteria structure" value={v.criteria_narrative} onChange={(e) => setV({ ...v, criteria_narrative: e.target.value })} />
        <TextArea label="Evidence expectations" value={v.evidence_description} onChange={(e) => setV({ ...v, evidence_description: e.target.value })} />
        <TextArea label="Skills terms (one per line)" value={v.skills} onChange={(e) => setV({ ...v, skills: e.target.value })} />
        <NumberInput
          renderLabel="Standard validity (days, blank for no expiry)"
          showArrows={false}
          value={v.validity_days}
          onChange={(_e, x) => setV({ ...v, validity_days: x })}
          width="14rem"
        />
        <TextInput renderLabel="Artwork style (shield, circle, hexagon…)" value={v.artwork_template} onChange={set("artwork_template")} />
        <TextInput renderLabel="Artwork colour (for example #212b58)" value={v.primary_colour} onChange={set("primary_colour")} />
        <TextArea label="Artwork guidance" value={v.artwork_guidance} onChange={(e) => setV({ ...v, artwork_guidance: e.target.value })} />
        {create.isError && <ErrorAlert error={create.error} />}
        <Button color="primary" margin="small 0" onClick={() => create.mutate()} interaction={v.name.trim().length >= 3 ? "enabled" : "disabled"}>
          Save template
        </Button>
      </View>
    </AdminPage>
  );
}
