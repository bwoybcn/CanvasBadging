// SPDX-License-Identifier: AGPL-3.0-or-later
/** Issuers with explicit delegated authority (spec §10.2). */
import { Alert, Button, Flex, Heading, SimpleSelect, Text, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiDelete, apiFetch, apiSend, type AdminCourse, type AdminIssuer, type OrgUnit } from "../../api";
import { useAuth } from "../../auth";
import { LimitedTextArea } from "../../components/Fields";
import { ErrorAlert, Loading, roleFlags, useMe } from "../../components/Page";
import { AdminPage, fmtDate } from "./AdminPage";


const LEVELS: Record<AdminIssuer["level"], string> = {
  university: "University",
  faculty: "Faculty",
  department: "Department",
  programme: "Programme",
};
const STATUS: Record<AdminIssuer["status"], string> = {
  draft: "Not yet authorised",
  active: "Authorised",
  suspended: "Suspended",
};

function useLookups() {
  const { token } = useAuth();
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const courses = useQuery({ queryKey: ["admin-courses"], queryFn: () => apiFetch<AdminCourse[]>("/api/v1/admin/courses", token) });
  return { units: units.data ?? [], courses: courses.data ?? [] };
}

export function Issuers() {
  const { token } = useAuth();
  const q = useQuery({ queryKey: ["admin-issuers"], queryFn: () => apiFetch<AdminIssuer[]>("/api/v1/admin/issuers", token) });
  return (
    <AdminPage title="Issuers">
      <Text as="p">
        An issuer is the body named on a credential. Creating one does not make it an awarding body: an institution
        administrator must authorise it and record the basis of its authority before anyone can award under it.
      </Text>
      {q.isError && <ErrorAlert error={q.error} />}
      {q.isPending && <Loading what="issuers" />}
      {q.data?.map((i) => <IssuerCard key={i.id} issuer={i} />)}
      <CreateIssuer />
    </AdminPage>
  );
}

function IssuerCard({ issuer }: { issuer: AdminIssuer }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const f = roleFlags(useMe().data);
  const { units, courses } = useLookups();
  const [basis, setBasis] = useState("");
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-issuers"] });
  const act = useMutation({
    mutationFn: ({ path, body, method = "POST" }: { path: string; body?: unknown; method?: string }) =>
      apiSend<unknown>(path, token, method, body),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/admin/issuer-delegations/${id}`, token),
    onSuccess: refresh,
  });
  const options = [
    ...units.filter((u) => u.manageable).map((u) => ({ id: `org_unit:${u.id}`, label: `${u.name} (${u.kind})` })),
    ...courses.map((c) => ({ id: `course:${c.id}`, label: `Course: ${c.title}` })),
  ];
  return (
    <View as="section" borderWidth="small" borderRadius="medium" padding="small" margin="0 0 small" display="block">
      <Flex justifyItems="space-between" wrap="wrap">
        <Heading level="h2" margin="0">
          {issuer.name}
        </Heading>
        <Text weight="bold">{STATUS[issuer.status]}</Text>
      </Flex>
      <Text as="p" size="small">
        {LEVELS[issuer.level]} level{issuer.org_unit_name ? `, ${issuer.org_unit_name}` : ""} · short name {issuer.slug}
        {issuer.did ? ` · ${issuer.did}` : ""}
        {issuer.active_key?.is_dev ? " · development key" : ""}
      </Text>
      {!issuer.may_issue && (
        <Alert variant="warning" margin="x-small 0">
          This issuer's department is not allowed to issue credentials.
        </Alert>
      )}
      {issuer.authority_basis && (
        <Text as="p">
          Authority: {issuer.authority_basis} (authorised {fmtDate(issuer.authorised_at)})
        </Text>
      )}
      <Heading level="h3" margin="small 0 x-small">
        Who may award under this issuer
      </Heading>
      {issuer.delegations.length === 0 ? (
        <Text as="p">Nobody yet.</Text>
      ) : (
        <ul>
          {issuer.delegations.map((d) => (
            <li key={d.id}>
              {d.scope_type === "course" ? "Course" : "Unit"}: {d.scope_name ?? d.scope_id}{" "}
              <Button size="small" onClick={() => remove.mutate(d.id)}>
                Remove {d.scope_name ?? "delegation"}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Flex gap="small" alignItems="end" wrap="wrap">
        <SimpleSelect
          renderLabel="Delegate to"
          value={target}
          onChange={(_e, { value }) => setTarget(String(value))}
          width="20rem"
        >
          <SimpleSelect.Option id="none" value="">
            Choose a department or course
          </SimpleSelect.Option>
          {options.map((o) => (
            <SimpleSelect.Option key={o.id} id={o.id} value={o.id}>
              {o.label}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
        <Button
          interaction={target ? "enabled" : "disabled"}
          onClick={() => {
            const [scope_type, scope_id] = target.split(":");
            act.mutate({ path: `/api/v1/admin/issuers/${issuer.id}/delegations`, body: { scope_type, scope_id } });
          }}
        >
          Add delegation
        </Button>
      </Flex>
      {f.isInstAdmin && issuer.status !== "active" && (
        <View as="div" margin="small 0 0">
          <LimitedTextArea
            maxLength={2000}
            label="Basis of this issuer's authority (for example the committee decision that approved it)"
            value={basis}
            onChange={(e) => setBasis(e.target.value)}
          />
          <Button
            color="primary"
            margin="x-small 0"
            interaction={basis.trim().length >= 10 ? "enabled" : "disabled"}
            onClick={() => act.mutate({ path: `/api/v1/admin/issuers/${issuer.id}/authorise`, body: { authority_basis: basis } })}
          >
            Authorise {issuer.name}
          </Button>
        </View>
      )}
      {f.isInstAdmin && issuer.status === "active" && (
        <Flex gap="small" alignItems="end" margin="small 0 0" wrap="wrap">
          <TextInput maxLength={2000} renderLabel="Reason to suspend" value={reason} onChange={(_e, v) => setReason(v)} width="20rem" />
          <Button
            interaction={reason.trim().length >= 5 ? "enabled" : "disabled"}
            onClick={() => act.mutate({ path: `/api/v1/admin/issuers/${issuer.id}/suspend`, body: { reason } })}
          >
            Suspend new awards
          </Button>
        </Flex>
      )}
      {(act.isError || remove.isError) && <ErrorAlert error={act.error ?? remove.error} />}
    </View>
  );
}

function CreateIssuer() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const f = roleFlags(useMe().data);
  const { units } = useLookups();
  const [v, setV] = useState({ name: "", slug: "", level: f.isInstAdmin ? "university" : "department", org_unit_id: "", url: "" });
  const create = useMutation({
    mutationFn: () =>
      apiSend<AdminIssuer>("/api/v1/admin/issuers", token, "POST", {
        ...v,
        org_unit_id: v.org_unit_id || null,
        url: v.url || null,
      }),
    onSuccess: () => {
      setV({ ...v, name: "", slug: "", url: "" });
      qc.invalidateQueries({ queryKey: ["admin-issuers"] });
    },
  });
  const levels = f.isInstAdmin ? Object.keys(LEVELS) : ["department", "programme"];
  return (
    <View as="section" margin="medium 0 0" display="block" maxWidth="40rem">
      <Heading level="h2" margin="0 0 small">
        New issuer
      </Heading>
      <TextInput maxLength={200} renderLabel="Name as it appears on credentials" value={v.name} onChange={(_e, x) => setV({ ...v, name: x })} />
      <TextInput
        maxLength={63}
        renderLabel="Short name (lowercase, used in web addresses)"
        value={v.slug}
        onChange={(_e, x) => setV({ ...v, slug: x })}
      />
      <SimpleSelect renderLabel="Level" value={v.level} onChange={(_e, { value }) => setV({ ...v, level: String(value) })}>
        {levels.map((l) => (
          <SimpleSelect.Option key={l} id={`lvl-${l}`} value={l}>
            {LEVELS[l as AdminIssuer["level"]]}
          </SimpleSelect.Option>
        ))}
      </SimpleSelect>
      <SimpleSelect
        renderLabel="Faculty or department"
        value={v.org_unit_id}
        onChange={(_e, { value }) => setV({ ...v, org_unit_id: String(value) })}
      >
        <SimpleSelect.Option id="unit-none" value="">
          None (university level)
        </SimpleSelect.Option>
        {units
          .filter((u) => u.manageable)
          .map((u) => (
            <SimpleSelect.Option key={u.id} id={`unit-${u.id}`} value={u.id}>
              {u.name}
            </SimpleSelect.Option>
          ))}
      </SimpleSelect>
      <TextInput maxLength={500} renderLabel="Web address (https://, optional)" value={v.url} onChange={(_e, x) => setV({ ...v, url: x })} />
      {create.isError && <ErrorAlert error={create.error} />}
      <Button color="primary" margin="small 0" onClick={() => create.mutate()}>
        Create issuer (not yet authorised)
      </Button>
    </View>
  );
}
