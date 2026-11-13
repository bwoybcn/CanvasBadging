// SPDX-License-Identifier: AGPL-3.0-or-later
/** Institution-wide issuance records, authorised revocation with a reason, and revocation
 * requests from course staff (spec §2.3, §2.4, §7.6, §10.3, §10.5). */
import { Alert, Button, Flex, Heading, SimpleSelect, Table, Text, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend, type CredentialRecord, REVOCATION_REASONS, type RevocationRequestRow } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage, DownloadButton, fmtDate } from "./AdminPage";

const STATUS_LABEL = { active: "Active", revoked: "Revoked", expired: "Expired" } as const;

export function Credentials() {
  const { token } = useAuth();
  const [status, setStatus] = useState("");
  const [learner, setLearner] = useState("");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (learner.trim().length >= 2) params.set("learner", learner.trim());
  const qs = params.toString();
  const q = useQuery({
    queryKey: ["admin-credentials", qs],
    queryFn: () => apiFetch<CredentialRecord[]>(`/api/v1/admin/credentials${qs ? `?${qs}` : ""}`, token),
  });
  return (
    <AdminPage title="Issued credentials">
      <Requests />
      <Heading level="h2" margin="medium 0 small">
        Records
      </Heading>
      <Flex gap="small" alignItems="end" wrap="wrap" margin="0 0 small">
        <SimpleSelect renderLabel="Status" value={status} onChange={(_e, { value }) => setStatus(String(value))} width="12rem">
          <SimpleSelect.Option id="st-all" value="">
            All
          </SimpleSelect.Option>
          <SimpleSelect.Option id="st-active" value="active">
            Active
          </SimpleSelect.Option>
          <SimpleSelect.Option id="st-revoked" value="revoked">
            Revoked
          </SimpleSelect.Option>
        </SimpleSelect>
        <TextInput renderLabel="Learner name contains" value={learner} onChange={(_e, v) => setLearner(v)} width="16rem" />
        <DownloadButton path={`/api/v1/admin/reports/issuance.csv${status ? `?status=${status}` : ""}`} filename="issuance-records.csv">
          Download CSV
        </DownloadButton>
      </Flex>
      {q.isPending && <Loading what="records" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.length === 0 && <Text as="p">No credentials match.</Text>}
      {q.data && q.data.length > 0 && (
        <Table caption="Issued credentials">
          <Table.Head>
            <Table.Row>
              <Table.ColHeader id="c-learner">Learner</Table.ColHeader>
              <Table.ColHeader id="c-badge">Badge</Table.ColHeader>
              <Table.ColHeader id="c-course">Course</Table.ColHeader>
              <Table.ColHeader id="c-date">Issued</Table.ColHeader>
              <Table.ColHeader id="c-status">Status</Table.ColHeader>
              <Table.ColHeader id="c-act">Action</Table.ColHeader>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {q.data.map((r) => (
              <RecordRow key={r.credential_id} r={r} />
            ))}
          </Table.Body>
        </Table>
      )}
    </AdminPage>
  );
}

function RecordRow({ r }: { r: CredentialRecord }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("issued_in_error");
  const [text, setText] = useState("");
  const who = r.learner_name ?? "Erased learner";
  const revoke = useMutation({
    mutationFn: () =>
      apiSend(`/api/v1/credentials/${r.credential_id}/revoke`, token, "POST", { reason_code: code, reason_text: text }),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["admin-credentials"] });
    },
  });
  return (
    <Table.Row>
      <Table.RowHeader>{who}</Table.RowHeader>
      <Table.Cell>
        {r.badge_title} (v{r.version_no})
      </Table.Cell>
      <Table.Cell>{r.course_title ?? ""}</Table.Cell>
      <Table.Cell>{fmtDate(r.issued_at)}</Table.Cell>
      <Table.Cell>
        {STATUS_LABEL[r.status]}
        {r.status === "revoked" && r.revocation_reason ? `: ${REVOCATION_REASONS[r.revocation_reason] ?? r.revocation_reason}` : ""}
      </Table.Cell>
      <Table.Cell>
        {r.status !== "revoked" && !open && (
          <Button size="small" onClick={() => setOpen(true)}>
            Revoke {r.badge_title} from {who}
          </Button>
        )}
        {open && (
          <View as="div">
            <SimpleSelect renderLabel="Reason" value={code} onChange={(_e, { value }) => setCode(String(value))}>
              {Object.entries(REVOCATION_REASONS).map(([k, label]) => (
                <SimpleSelect.Option key={k} id={`${r.credential_id}-${k}`} value={k}>
                  {label}
                </SimpleSelect.Option>
              ))}
            </SimpleSelect>
            <TextInput renderLabel="Explanation (kept in the record, not shown publicly)" value={text} onChange={(_e, v) => setText(v)} />
            <Alert variant="warning" margin="x-small 0">
              Verifiers will report this credential as revoked, including copies the learner has already downloaded.
            </Alert>
            <Flex gap="x-small">
              <Button size="small" color="danger" interaction={text.trim().length >= 3 ? "enabled" : "disabled"} onClick={() => revoke.mutate()}>
                Confirm revocation
              </Button>
              <Button size="small" onClick={() => setOpen(false)}>
                Cancel
              </Button>
            </Flex>
            {revoke.isError && <ErrorAlert error={revoke.error} />}
          </View>
        )}
      </Table.Cell>
    </Table.Row>
  );
}

function Requests() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["revocation-requests"],
    queryFn: () => apiFetch<RevocationRequestRow[]>("/api/v1/admin/revocation-requests", token),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      apiSend(`/api/v1/admin/revocation-requests/${id}/${approve ? "approve" : "decline"}`, token, "POST", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["revocation-requests"] });
      qc.invalidateQueries({ queryKey: ["admin-credentials"] });
    },
  });
  if (!q.data || q.data.length === 0) return null;
  return (
    <View as="section" display="block">
      <Heading level="h2" margin="0 0 small">
        Revocation requests
      </Heading>
      {q.data.map((r) => (
        <View key={r.id} as="div" borderWidth="small" borderRadius="medium" padding="small" margin="0 0 small" display="block">
          <Text as="p">
            {r.requested_by ?? "Staff"} asked to revoke <strong>{r.badge_title}</strong> from {r.learner_name ?? "a learner"}
            {r.course_title ? ` (${r.course_title})` : ""}: “{r.reason}”
          </Text>
          {r.can_decide ? (
            <Flex gap="x-small">
              <Button size="small" color="danger" onClick={() => decide.mutate({ id: r.id, approve: true })}>
                Revoke
              </Button>
              <Button size="small" onClick={() => decide.mutate({ id: r.id, approve: false })}>
                Decline request
              </Button>
            </Flex>
          ) : (
            <Text size="small">Waiting for an authorised revoker.</Text>
          )}
        </View>
      ))}
      {decide.isError && <ErrorAlert error={decide.error} />}
    </View>
  );
}
