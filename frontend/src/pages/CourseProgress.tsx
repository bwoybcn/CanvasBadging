// SPDX-License-Identifier: AGPL-3.0-or-later
/** Lecturer view of a course: every learner against every live badge, plus Canvas freshness. */
import { Alert, Button, Flex, Heading, List, Modal, Table, Text, TextArea, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router";

import {
  apiFetch,
  apiSend,
  problemText,
  type CourseProgress as Progress,
  type CredentialRecord,
  type Rule,
  type SyncState,
} from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Loading, Page } from "../components/Page";
import { TableScroll } from "../components/TableScroll";
import { DownloadButton } from "./admin/AdminPage";

export const OUTCOME_LABELS: Record<string, string> = {
  met: "Requirements met",
  not_met: "Not yet met",
  unknown: "Pending",
};
const DECISION_LABELS: Record<string, string> = {
  ready: "Awarded",
  issued: "Issued",
  awaiting_confirmation: "Awaiting your confirmation",
  rejected: "Not awarded",
};

export function cellText(outcome: string | null, decision: string | null, codes: string[]): string {
  if (decision && DECISION_LABELS[decision]) return DECISION_LABELS[decision];
  if (!outcome) return "Not evaluated yet";
  if (outcome === "unknown") {
    if (codes.includes("AWAITING_APPROVAL")) return "Pending: needs your confirmation";
    if (codes.includes("AWAITING_RELEASE")) return "Pending: mark not released";
    if (codes.some((c) => c.startsWith("DATA_"))) return "Pending: Canvas data unavailable";
  }
  return OUTCOME_LABELS[outcome] ?? outcome;
}

function manualRules(rules: Rule[]): { id: string; text: string }[] {
  const out: { id: string; text: string }[] = [];
  for (const r of rules) {
    if (r.type === "manual_approval" && r.id) out.push({ id: r.id, text: r.instructions || "Lecturer confirms" });
    if (r.type === "group")
      for (const c of r.rules)
        if (c.type === "manual_approval" && c.id) out.push({ id: c.id, text: c.instructions || "Lecturer confirms" });
  }
  return out;
}

function ApprovalModal({
  open,
  onClose,
  definitionId,
  versionId,
  userId,
  learner,
}: {
  open: boolean;
  onClose: () => void;
  definitionId: string;
  versionId: string;
  userId: string;
  learner: string;
}) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const rules = useQuery({
    queryKey: ["version-rules", versionId],
    enabled: open,
    queryFn: () => apiFetch<{ rules: { rules: Rule[] } | null }>(`/api/v1/achievement-versions/${versionId}/rules`, token),
  });
  const record = useMutation({
    mutationFn: (v: { rule_id: string; decision: "approve" | "decline" }) =>
      apiSend<unknown>(`/api/v1/achievements/${definitionId}/approvals`, token, "POST", {
        user_id: userId,
        ...v,
        note: note || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["progress"] });
      onClose();
    },
  });
  const items = manualRules(rules.data?.rules?.rules ?? []);
  return (
    <Modal open={open} onDismiss={onClose} label={`Confirm requirement for ${learner}`} size="small">
      <Modal.Body>
        {rules.isPending && <Loading what="requirements" />}
        {items.length === 0 && !rules.isPending && <Text>This badge has no lecturer-confirmed requirements.</Text>}
        <TextInput renderLabel="Note (optional)" value={note} onChange={(_e, v) => setNote(v)} />
        {items.map((r) => (
          <View key={r.id} as="div" margin="small 0" display="block">
            <Text as="p">{r.text}</Text>
            <Flex gap="x-small">
              <Button size="small" color="primary" onClick={() => record.mutate({ rule_id: r.id, decision: "approve" })}>
                Confirm met
              </Button>
              <Button size="small" onClick={() => record.mutate({ rule_id: r.id, decision: "decline" })}>
                Not met
              </Button>
            </Flex>
          </View>
        ))}
        {record.isError && <ErrorAlert error={record.error} />}
      </Modal.Body>
      <Modal.Footer>
        <Button onClick={onClose}>Close</Button>
      </Modal.Footer>
    </Modal>
  );
}

/** Course staff ask an administrator to revoke a credential (spec §2.2); nothing changes until a revoker approves. */
function RevocationRequestModal({ credentialId, learner, badge, onClose }: { credentialId: string; learner: string; badge: string; onClose: () => void }) {
  const { token } = useAuth();
  const [reason, setReason] = useState("");
  const send = useMutation({
    mutationFn: () => apiSend(`/api/v1/credentials/${credentialId}/revocation-requests`, token, "POST", { reason }),
  });
  return (
    <Modal open onDismiss={onClose} label={`Request revocation of ${badge} for ${learner}`} size="medium">
      <Modal.Body>
        <Heading level="h2" margin="0 0 small">
          Request revocation: {badge}, {learner}
        </Heading>
        {send.isSuccess ? (
          <Alert variant="success">
            Request sent. An administrator will review it. The credential stays valid until they approve.
          </Alert>
        ) : (
          <>
            <Text as="p">
              Revocation cannot be undone. Verifiers will show the credential as revoked, including copies the learner has
              already downloaded. The credential itself is never deleted.
            </Text>
            <TextArea
              label="Why should it be revoked? (at least 5 characters)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            {send.isError && <ErrorAlert error={send.error} />}
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button onClick={onClose} margin="0 x-small 0 0">
          Close
        </Button>
        {!send.isSuccess && (
          <Button
            color="primary"
            interaction={reason.trim().length >= 5 && !send.isPending ? "enabled" : "disabled"}
            onClick={() => send.mutate()}
          >
            Send request
          </Button>
        )}
      </Modal.Footer>
    </Modal>
  );
}

const KIND_LABELS: Record<string, string> = { automatic: "Automatic", confirmed: "Lecturer-confirmed", manual: "Manual" };

/** Award history for course staff (spec §2.2): what was issued here, and a CSV of it. */
function IssuedInCourse({ courseId, title }: { courseId: string; title: string }) {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["course-credentials", courseId],
    queryFn: () => apiFetch<CredentialRecord[]>(`/api/v1/courses/${courseId}/credentials`, token),
  });
  return (
    <View as="section" aria-labelledby="issued-h" display="block" margin="large 0 0">
      <Flex justifyItems="space-between" alignItems="center" wrap="wrap">
        <Heading level="h2" id="issued-h">
          Credentials issued in this course
        </Heading>
        <DownloadButton path={`/api/v1/courses/${courseId}/credentials.csv`} filename="course-credentials.csv">
          Download as CSV
        </DownloadButton>
      </Flex>
      {q.isPending && <Loading what="issued credentials" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.length === 0 && <Text as="p">No credentials have been issued in this course yet.</Text>}
      {q.data && q.data.length > 0 && (
        <TableScroll>
          <Table caption={`Credentials issued in ${title}`} layout="auto">
            <Table.Head>
              <Table.Row>
                <Table.ColHeader id="i-learner">Learner</Table.ColHeader>
                <Table.ColHeader id="i-badge">Badge</Table.ColHeader>
                <Table.ColHeader id="i-kind">How awarded</Table.ColHeader>
                <Table.ColHeader id="i-date">Issued</Table.ColHeader>
                <Table.ColHeader id="i-status">Status</Table.ColHeader>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {q.data.map((r) => (
                <Table.Row key={r.credential_id}>
                  <Table.RowHeader>{r.learner_name ?? "Erased learner"}</Table.RowHeader>
                  <Table.Cell>
                    {r.badge_title} (version {r.version_no})
                  </Table.Cell>
                  <Table.Cell>{KIND_LABELS[r.award_kind] ?? r.award_kind}</Table.Cell>
                  <Table.Cell>{r.issued_at ? new Date(r.issued_at).toLocaleDateString() : ""}</Table.Cell>
                  <Table.Cell>
                    {r.status === "revoked" ? `Revoked (${r.revocation_reason ?? "no reason code"})` : r.status === "expired" ? "Expired" : "Valid"}
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </TableScroll>
      )}
    </View>
  );
}

export function CourseProgress() {
  const { id = "" } = useParams();
  const { token } = useAuth();
  const qc = useQueryClient();
  const [approval, setApproval] = useState<null | { definitionId: string; versionId: string; userId: string; learner: string }>(null);
  const [revoke, setRevoke] = useState<null | { credentialId: string; learner: string; badge: string }>(null);
  const q = useQuery({
    queryKey: ["progress", id],
    queryFn: () => apiFetch<Progress>(`/api/v1/courses/${id}/progress`, token),
  });
  const sync = useQuery({ queryKey: ["sync", id], queryFn: () => apiFetch<SyncState>(`/api/v1/courses/${id}/sync`, token) });
  const refresh = useMutation({
    mutationFn: () => apiSend<{ queued: boolean }>(`/api/v1/courses/${id}/sync`, token, "POST"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sync", id] }),
  });

  if (q.isPending) return <Loading what="course progress" />;
  if (q.isError)
    return (
      <Page title="Course progress">
        <ErrorAlert error={q.error} />
      </Page>
    );
  const p = q.data;
  const last = sync.data?.last_run;
  return (
    <Page title={`Progress: ${p.course.title}`}>
      <View as="section" aria-label="Canvas data" display="block" margin="0 0 medium">
        <Text as="p">
          Canvas data last read successfully:{" "}
          {sync.data?.last_success_at ? new Date(sync.data.last_success_at).toLocaleString() : "never"}
          {last && ` (last attempt ${new Date(last.started_at).toLocaleString()}${last.finished_at ? "" : ", still running"})`}
        </Text>
        {last && last.status === "failed" && (
          <Alert variant="warning" margin="small 0">
            The last refresh from Canvas failed. Nothing is awarded on missing data; affected requirements stay pending.
          </Alert>
        )}
        {last && last.failed_learners > 0 && (
          <Alert variant="warning" margin="small 0">
            Data for {last.failed_learners} learner(s) could not be read in the last refresh.
          </Alert>
        )}
        <Button onClick={() => refresh.mutate()} interaction={refresh.isPending ? "disabled" : "enabled"}>
          Refresh from Canvas
        </Button>
        {refresh.isSuccess && (
          <Alert variant="success" margin="small 0">
            Refresh requested. Results will update in a few minutes.
          </Alert>
        )}
        {refresh.isError && (
          <Alert variant="warning" margin="small 0">
            {problemText(refresh.error)}
            {last && ` Nothing new was read from Canvas. The figures below come from the read started at ${new Date(last.started_at).toLocaleString()}.`}
          </Alert>
        )}
      </View>
      {p.badges.length === 0 ? (
        <Text as="p">No badges are published in this course yet.</Text>
      ) : (
        <>
          {p.badges.some((b) => b.source_flags.length > 0) && (
            <Alert variant="warning" margin="0 0 small">
              Some badges refer to Canvas modules or assignments that were removed or changed. Those requirements stay
              pending until the badge is updated.
            </Alert>
          )}
          <TableScroll>
          <Table caption={`Learner progress in ${p.course.title}`} layout="auto">
            <Table.Head>
              <Table.Row>
                {[
                  <Table.ColHeader key="learner" id="learner">
                    Learner
                  </Table.ColHeader>,
                  ...p.badges.map((b) => (
                    <Table.ColHeader key={b.version_id} id={b.version_id}>
                      {b.title}
                    </Table.ColHeader>
                  )),
                ]}
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {p.learners.map((l) => (
                <Table.Row key={l.user_id}>
                  {[
                    <Table.RowHeader key="name">{l.name ?? "Learner"}</Table.RowHeader>,
                    ...l.cells.map((c, i) => (
                    <Table.Cell key={c.version_id}>
                      <Text>{cellText(c.outcome, c.decision_status, c.codes)}</Text>
                      {c.progress && (
                        <Text as="div" size="small">
                          {c.progress.completed} of {c.progress.total}
                        </Text>
                      )}
                      {c.codes.includes("AWAITING_APPROVAL") && (
                        <Button
                          size="small"
                          margin="xx-small 0 0"
                          onClick={() =>
                            setApproval({
                              definitionId: p.badges[i].definition_id,
                              versionId: c.version_id,
                              userId: l.user_id,
                              learner: l.name ?? "learner",
                            })
                          }
                        >
                          Confirm requirement for {l.name ?? "learner"}
                        </Button>
                      )}
                      {c.decision_status === "issued" && c.credential_id && (
                        <Button
                          size="small"
                          margin="xx-small 0 0"
                          onClick={() =>
                            setRevoke({ credentialId: c.credential_id!, learner: l.name ?? "learner", badge: p.badges[i].title })
                          }
                        >
                          Request revocation for {l.name ?? "learner"}
                        </Button>
                      )}
                    </Table.Cell>
                    )),
                  ]}
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
          </TableScroll>
          <Heading level="h2" margin="medium 0 small">
            Badge requirements
          </Heading>
          {p.badges.map((b) => (
            <View key={b.version_id} as="div" display="block" margin="0 0 small">
              <Text weight="bold">{b.title}</Text>
              <List>
                {b.rules.map((r) => (
                  <List.Item key={r}>{r}</List.Item>
                ))}
              </List>
            </View>
          ))}
        </>
      )}
      {approval && <ApprovalModal open onClose={() => setApproval(null)} {...approval} />}
      <IssuedInCourse courseId={p.course.id} title={p.course.title} />
      {revoke && <RevocationRequestModal onClose={() => setRevoke(null)} {...revoke} />}
    </Page>
  );
}
