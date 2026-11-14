// SPDX-License-Identifier: AGPL-3.0-or-later
/** Personal-data export and erasure, and retention settings (spec §12.5). Erasure, credential
 * revocation and withdrawal of public sharing are separate operations. */
import { Alert, Button, Flex, Heading, NumberInput, SimpleSelect, Text, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend, type Person } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage, DownloadButton } from "./AdminPage";

interface Retention {
  snapshot_days_after_course_end: number;
  evaluation_days: number;
  failed_job_days: number;
  audit_event_years: number;
}

const RETENTION_LABELS: Record<keyof Retention, string> = {
  snapshot_days_after_course_end: "Keep Canvas progress snapshots after a course is archived (days)",
  evaluation_days: "Keep eligibility history not used by an award (days)",
  failed_job_days: "Keep failed background jobs (days)",
  audit_event_years: "Keep audit events (years, at least 1)",
};

export function Privacy() {
  return (
    <AdminPage title="Personal data and retention" instOnly>
      <PersonalData />
      <RetentionSettings />
    </AdminPage>
  );
}

function PersonalData() {
  const { token } = useAuth();
  const [search, setSearch] = useState("");
  const [person, setPerson] = useState("");
  const [confirm, setConfirm] = useState("");
  const people = useQuery({
    queryKey: ["people", search],
    queryFn: () => apiFetch<Person[]>(`/api/v1/admin/people?q=${encodeURIComponent(search)}`, token),
    enabled: search.trim().length >= 2,
  });
  const erase = useMutation({
    mutationFn: () => apiSend<Record<string, number>>(`/api/v1/admin/people/${person}/erase`, token, "POST", { confirm }),
  });
  return (
    <View as="section" display="block" margin="0 0 large" maxWidth="44rem">
      <Heading level="h2" margin="0 0 small">
        A person's data
      </Heading>
      <Flex gap="small" alignItems="end" wrap="wrap">
        <TextInput renderLabel="Find a person by name" value={search} onChange={(_e, v) => setSearch(v)} width="16rem" />
        <SimpleSelect renderLabel="Person" value={person} onChange={(_e, { value }) => setPerson(String(value))} width="16rem">
          <SimpleSelect.Option id="pp-none" value="">
            Choose
          </SimpleSelect.Option>
          {(people.data ?? []).map((p) => (
            <SimpleSelect.Option key={p.id} id={`pp-${p.id}`} value={p.id}>
              {p.display_name ?? p.id}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
      </Flex>
      {person && (
        <View as="div" margin="small 0 0">
          <DownloadButton path={`/api/v1/admin/people/${person}/data-export`} filename={`personal-data-${person}.json`}>
            Download everything we hold (JSON)
          </DownloadButton>
          <Alert variant="info" margin="small 0">
            Erasing removes the person's name, email, Canvas identifiers, roles, Canvas progress and eligibility history,
            cancels awards not yet issued and takes down their public share pages. It does not revoke credentials already
            issued (they contain no name and the learner may still rely on them). Do that separately if it is also
            requested.
          </Alert>
          <TextInput renderLabel="Type ERASE to confirm" value={confirm} onChange={(_e, v) => setConfirm(v)} width="12rem" />
          <Button color="danger" margin="x-small 0" interaction={confirm === "ERASE" ? "enabled" : "disabled"} onClick={() => erase.mutate()}>
            Erase this person's personal data
          </Button>
          {erase.isError && <ErrorAlert error={erase.error} />}
          {erase.data && (
            <Alert variant="success" margin="small 0">
              Erased. {erase.data.credentials_kept} issued credentials kept; {erase.data.share_links_withdrawn} public share
              links taken down; {erase.data.awards_cancelled} pending awards cancelled.
            </Alert>
          )}
        </View>
      )}
    </View>
  );
}

function RetentionSettings() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["retention"], queryFn: () => apiFetch<Retention>("/api/v1/institutions/current/retention", token) });
  const [edit, setEdit] = useState<Partial<Retention>>({});
  const save = useMutation({
    mutationFn: () => apiSend<Retention>("/api/v1/institutions/current/retention", token, "PATCH", edit),
    onSuccess: (r) => {
      qc.setQueryData(["retention"], r);
      setEdit({});
    },
  });
  const run = useMutation({ mutationFn: () => apiSend<Record<string, number>>("/api/v1/admin/retention/run", token, "POST") });
  if (q.isPending) return <Loading what="retention" />;
  if (q.isError) return <ErrorAlert error={q.error} />;
  const value = { ...q.data, ...edit };
  return (
    <View as="section" display="block" maxWidth="44rem">
      <Heading level="h2" margin="0 0 small">
        Retention
      </Heading>
      <Text as="p">
        Issued credentials, their revocation status and award records are never purged: they are needed for as long as
        anyone may verify a credential. Retention runs every night.
      </Text>
      {(Object.keys(RETENTION_LABELS) as (keyof Retention)[]).map((k) => (
        <NumberInput
          key={k}
          renderLabel={RETENTION_LABELS[k]}
          showArrows={false}
          width="10rem"
          value={String(value[k])}
          onChange={(_e, v) => setEdit({ ...edit, [k]: Number(v) })}
        />
      ))}
      {save.isError && <ErrorAlert error={save.error} />}
      <Flex gap="small" margin="small 0">
        <Button color="primary" onClick={() => save.mutate()} interaction={Object.keys(edit).length ? "enabled" : "disabled"}>
          Save retention settings
        </Button>
        <Button onClick={() => run.mutate()}>Apply retention now</Button>
      </Flex>
      {run.isError && <ErrorAlert error={run.error} />}
      {run.data && (
        <Alert variant="success" margin="small 0">
          Removed: {Object.entries(run.data).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}.
        </Alert>
      )}
    </View>
  );
}
