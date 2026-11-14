// SPDX-License-Identifier: AGPL-3.0-or-later
/** Institution configuration (spec §10.1). */
import { Alert, Button, Heading, TextArea, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage } from "./AdminPage";

interface Config {
  name: string;
  description: string | null;
  website_url: string | null;
  branding: { primary_colour?: string; secondary_colour?: string };
  verification_host: string | null;
  categories: string[];
  linkedin_org_id: string | null;
  linkedin_org_name: string | null;
}

export function InstitutionSettings() {
  const { token } = useAuth();
  const q = useQuery({ queryKey: ["institution"], queryFn: () => apiFetch<Config>("/api/v1/institutions/current", token) });
  return (
    <AdminPage title="Institution settings" instOnly>
      {q.isError && <ErrorAlert error={q.error} />}
      {q.isPending && <Loading what="settings" />}
      {q.data && <ConfigForm initial={q.data} />}
    </AdminPage>
  );
}

function ConfigForm({ initial }: { initial: Config }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [c, setC] = useState({
    name: initial.name,
    description: initial.description ?? "",
    website_url: initial.website_url ?? "",
    primary_colour: initial.branding.primary_colour ?? "",
    secondary_colour: initial.branding.secondary_colour ?? "",
    categories: initial.categories.join("\n"),
    linkedin_org_id: initial.linkedin_org_id ?? "",
    linkedin_org_name: initial.linkedin_org_name ?? "",
  });
  const set = (k: keyof typeof c) => (_e: unknown, v: string) => setC({ ...c, [k]: v });
  const save = useMutation({
    mutationFn: () =>
      apiSend<Config>("/api/v1/institutions/current", token, "PATCH", {
        name: c.name,
        description: c.description || null,
        website_url: c.website_url || null,
        branding: { primary_colour: c.primary_colour || null, secondary_colour: c.secondary_colour || null },
        categories: c.categories.split("\n").map((s) => s.trim()).filter(Boolean),
        linkedin_org_id: c.linkedin_org_id || null,
        linkedin_org_name: c.linkedin_org_name || null,
      }),
    onSuccess: (d) => qc.setQueryData(["institution"], d),
  });
  return (
    <View as="div" maxWidth="40rem">
      <Heading level="h2" margin="0 0 small">
        Identity
      </Heading>
      <TextInput renderLabel="Institution name" value={c.name} onChange={set("name")} />
      <TextArea label="Description" value={c.description} onChange={(e) => setC({ ...c, description: e.target.value })} />
      <TextInput renderLabel="Official website (https://)" value={c.website_url} onChange={set("website_url")} />
      <TextInput renderLabel="Brand colour (for example #212b58)" value={c.primary_colour} onChange={set("primary_colour")} />
      <TextInput renderLabel="Second brand colour" value={c.secondary_colour} onChange={set("secondary_colour")} />
      <Heading level="h2" margin="medium 0 small">
        Verification
      </Heading>
      <TextInput
        renderLabel="Public verification domain"
        interaction="readonly"
        messages={[
          {
            type: "hint",
            text: "Set by the service operator once they have checked your institution controls the domain. Issuers get did:web identifiers on this host; it cannot change once they sign.",
          },
        ]}
        value={initial.verification_host ?? "Not set yet: ask the service operator"}
      />
      <Heading level="h2" margin="medium 0 small">
        Achievement categories
      </Heading>
      <TextArea
        label="One category per line"
        value={c.categories}
        onChange={(e) => setC({ ...c, categories: e.target.value })}
      />
      <Heading level="h2" margin="medium 0 small">
        LinkedIn
      </Heading>
      <TextInput renderLabel="LinkedIn organisation id" value={c.linkedin_org_id} onChange={set("linkedin_org_id")} />
      <TextInput renderLabel="LinkedIn organisation name" value={c.linkedin_org_name} onChange={set("linkedin_org_name")} />
      {save.isError && <ErrorAlert error={save.error} />}
      {save.isSuccess && (
        <Alert variant="success" margin="small 0">
          Saved.
        </Alert>
      )}
      <Button color="primary" margin="small 0" onClick={() => save.mutate()}>
        Save settings
      </Button>
    </View>
  );
}
