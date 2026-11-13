// SPDX-License-Identifier: AGPL-3.0-or-later
/** Failed or stuck issuance and the safe actions for each (spec §10.5, §17.2). */
import { Button, Flex, Heading, Table, Text, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend, type Reconciliation as Recon } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage, fmtDate } from "./AdminPage";
import { TableScroll } from "../../components/TableScroll";

const PROBLEM: Record<Recon["awards_not_issued"][number]["problem"], string> = {
  never_started: "Issuance never started",
  stuck_before_signing: "Stuck before signing",
  signing_failed: "Signing failed",
};

export function Reconciliation() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["reconciliation"], queryFn: () => apiFetch<Recon>("/api/v1/admin/reconciliation", token) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["reconciliation"] });
  const retryJob = useMutation({
    mutationFn: (id: number) => apiSend(`/api/v1/admin/jobs/${id}/retry`, token, "POST"),
    onSuccess: refresh,
  });
  return (
    <AdminPage title="Failed issuance" instOnly>
      {q.isPending && <Loading what="issuance problems" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && (
        <>
          <Heading level="h2" margin="0 0 small">
            Awards not yet issued
          </Heading>
          {q.data.awards_not_issued.length === 0 ? (
            <Text as="p">Nothing is stuck. Every award older than ten minutes has its credential.</Text>
          ) : (
            <TableScroll>
            <Table caption="Awards not yet issued">
              <Table.Head>
                <Table.Row>
                  <Table.ColHeader id="r-who">Learner</Table.ColHeader>
                  <Table.ColHeader id="r-badge">Badge</Table.ColHeader>
                  <Table.ColHeader id="r-when">Awarded</Table.ColHeader>
                  <Table.ColHeader id="r-prob">Problem</Table.ColHeader>
                  <Table.ColHeader id="r-act">Action</Table.ColHeader>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {q.data.awards_not_issued.map((a) => (
                  <AwardRow key={a.decision_id} a={a} onDone={refresh} />
                ))}
              </Table.Body>
            </Table>
            </TableScroll>
          )}
          <Heading level="h2" margin="medium 0 small">
            Failed jobs
          </Heading>
          {q.data.failed_jobs.length === 0 ? (
            <Text as="p">No failed issuance or status-list jobs.</Text>
          ) : (
            <ul>
              {q.data.failed_jobs.map((j) => (
                <li key={j.id}>
                  {j.task} for {j.subject_type} {j.subject_id} after {j.attempts} attempts{" "}
                  <Button size="small" onClick={() => retryJob.mutate(j.id)}>
                    Retry job {j.id}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {retryJob.isError && <ErrorAlert error={retryJob.error} />}
          <Heading level="h2" margin="medium 0 small">
            Revocation lists overdue
          </Heading>
          {q.data.status_lists_overdue.length === 0 ? (
            <Text as="p">All revocation lists are published and current.</Text>
          ) : (
            <ul>
              {q.data.status_lists_overdue.map((s) => (
                <li key={s.id}>
                  List {s.id}: last published {fmtDate(s.published_at) || "never"}. It is republished automatically every
                  hour; if this persists, check that the signer is running.
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </AdminPage>
  );
}

function AwardRow({ a, onDone }: { a: Recon["awards_not_issued"][number]; onDone: () => void }) {
  const { token } = useAuth();
  const [reason, setReason] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const who = a.learner_name ?? "Learner";
  const act = useMutation({
    mutationFn: (kind: "requeue" | "cancel") =>
      apiSend(`/api/v1/admin/reconciliation/awards/${a.decision_id}/${kind}`, token, "POST", kind === "cancel" ? { reason } : undefined),
    onSuccess: onDone,
  });
  return (
    <Table.Row>
      <Table.RowHeader>{who}</Table.RowHeader>
      <Table.Cell>{a.badge_title}</Table.Cell>
      <Table.Cell>{fmtDate(a.decided_at)}</Table.Cell>
      <Table.Cell>
        {PROBLEM[a.problem]}
        {a.last_error ? `: ${a.last_error}` : ""}
      </Table.Cell>
      <Table.Cell>
        {cancelling ? (
          <View as="div">
            <TextInput renderLabel={`Why ${who} should not get this badge`} value={reason} onChange={(_e, v) => setReason(v)} />
            <Flex gap="x-small" margin="x-small 0 0">
              <Button size="small" color="danger" interaction={reason.trim().length >= 5 ? "enabled" : "disabled"} onClick={() => act.mutate("cancel")}>
                Cancel award
              </Button>
              <Button size="small" onClick={() => setCancelling(false)}>
                Keep award
              </Button>
            </Flex>
          </View>
        ) : (
          <Flex gap="x-small">
            <Button size="small" color="primary" onClick={() => act.mutate("requeue")}>
              Try issuing to {who} again
            </Button>
            <Button size="small" onClick={() => setCancelling(true)}>
              Cancel award
            </Button>
          </Flex>
        )}
        {act.isError && <ErrorAlert error={act.error} />}
      </Table.Cell>
    </Table.Row>
  );
}
