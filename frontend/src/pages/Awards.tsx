// SPDX-License-Identifier: AGPL-3.0-or-later
/** Lecturer-confirmed awards waiting for a decision, and manual awards with justification. */
import {
  Alert,
  Button,
  Checkbox,
  Flex,
  Heading,
  SimpleSelect,
  Table,
  Text,
  TextArea,
  TextInput,
  View,
} from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  apiFetch,
  apiSend,
  type BulkAwardResult,
  type BulkRow,
  type CourseProgress,
  type Decision,
  type DefinitionSummary,
} from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Loading, Page } from "../components/Page";
import { TableScroll } from "../components/TableScroll";

export const EVIDENCE_KINDS: Record<string, string> = {
  lecturer_confirmation: "Staff confirmation",
  assessment_result: "Assessment result",
  completion_record: "Completion record",
  evaluation_statement: "Evaluation statement",
  artefact: "Learner's work (artefact)",
};

function DecisionRow({ d }: { d: Decision }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const act = useMutation({
    mutationFn: (kind: "confirm" | "reject") =>
      apiSend<Decision>(`/api/v1/awards/${d.id}/${kind}`, token, "POST", kind === "confirm" ? {} : { reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["awards"] }),
  });
  const who = d.learner_name ?? "Learner";
  return (
    <Table.Row>
      <Table.RowHeader>{who}</Table.RowHeader>
      <Table.Cell>{d.badge_title}</Table.Cell>
      <Table.Cell>{d.kind === "manual" ? "Manual award (needs a second approver)" : "Requirements met"}</Table.Cell>
      <Table.Cell>
        {act.isError && <ErrorAlert error={act.error} />}
        {rejecting ? (
          <View as="div" display="block">
            <TextInput renderLabel={`Reason for not awarding to ${who}`} value={reason} onChange={(_e, v) => setReason(v)} />
            <Flex gap="x-small" margin="x-small 0 0">
              <Button size="small" interaction={reason.trim().length >= 5 ? "enabled" : "disabled"} onClick={() => act.mutate("reject")}>
                Confirm not awarding
              </Button>
              <Button size="small" onClick={() => setRejecting(false)}>
                Cancel
              </Button>
            </Flex>
          </View>
        ) : (
          <Flex gap="x-small">
            <Button size="small" color="primary" interaction={act.isPending ? "disabled" : "enabled"} onClick={() => act.mutate("confirm")}>
              Award to {who}
            </Button>
            <Button size="small" onClick={() => setRejecting(true)}>
              Do not award
            </Button>
          </Flex>
        )}
      </Table.Cell>
    </Table.Row>
  );
}

function ManualAward() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [badge, setBadge] = useState("");
  const [learner, setLearner] = useState("");
  const [justification, setJustification] = useState("");
  const [kind, setKind] = useState("lecturer_confirmation");
  const [narrative, setNarrative] = useState("");
  const [pub, setPub] = useState(false);
  const badges = useQuery({
    queryKey: ["achievements", "published"],
    queryFn: () => apiFetch<{ items: DefinitionSummary[] }>("/api/v1/achievements?state=published", token),
  });
  const chosen = badges.data?.items.find((b) => b.id === badge);
  const learners = useQuery({
    queryKey: ["progress", chosen?.course_id],
    enabled: !!chosen?.course_id,
    queryFn: () => apiFetch<CourseProgress>(`/api/v1/courses/${chosen?.course_id}/progress`, token),
  });
  const award = useMutation({
    mutationFn: () =>
      apiSend<Decision>("/api/v1/awards/manual", token, "POST", {
        definition_id: badge,
        user_id: learner,
        justification,
        evidence: narrative.trim() ? [{ kind, narrative, public: pub }] : [],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["awards"] });
      setJustification("");
      setNarrative("");
    },
  });
  const ok = badge && learner && justification.trim().length >= 20;
  return (
    <View as="section" aria-labelledby="manual-h" display="block" margin="large 0 0">
      <Heading level="h2" id="manual-h">
        Award a badge manually
      </Heading>
      <Text as="p">
        Use this when a learner has met the outcomes in a way Canvas cannot show. Your justification is kept in the
        audit record; only evidence you mark as public appears on the credential.
      </Text>
      <SimpleSelect renderLabel="Badge" value={badge || undefined} placeholder="Choose a published badge" onChange={(_e, { value }) => { setBadge(String(value)); setLearner(""); }}>
        {(badges.data?.items ?? []).map((b) => (
          <SimpleSelect.Option key={b.id} id={`mb-${b.id}`} value={b.id}>
            {b.title}
          </SimpleSelect.Option>
        ))}
      </SimpleSelect>
      <SimpleSelect
        renderLabel="Learner"
        value={learner || undefined}
        placeholder={badge ? "Choose a learner" : "Choose a badge first"}
        onChange={(_e, { value }) => setLearner(String(value))}
      >
        {(learners.data?.learners ?? []).map((l) => (
          <SimpleSelect.Option key={l.user_id} id={`ml-${l.user_id}`} value={l.user_id}>
            {l.name ?? l.user_id}
          </SimpleSelect.Option>
        ))}
      </SimpleSelect>
      <TextArea
        label="Justification (at least 20 characters)"
        value={justification}
        onChange={(e) => setJustification(e.target.value)}
      />
      <SimpleSelect renderLabel="Evidence type" value={kind} onChange={(_e, { value }) => setKind(String(value))}>
        {Object.entries(EVIDENCE_KINDS).map(([k, label]) => (
          <SimpleSelect.Option key={k} id={`ek-${k}`} value={k}>
            {label}
          </SimpleSelect.Option>
        ))}
      </SimpleSelect>
      <TextArea label="Evidence description (optional)" value={narrative} onChange={(e) => setNarrative(e.target.value)} />
      <Checkbox label="Show this evidence on the public credential" checked={pub} onChange={(e) => setPub(e.target.checked)} />
      {award.isError && <ErrorAlert error={award.error} />}
      {award.isSuccess && (
        <Alert variant="success" margin="small 0">
          {award.data.status === "awaiting_confirmation"
            ? "Recorded. A second member of staff must confirm it before it is issued."
            : "Awarded. The credential will be issued shortly."}
        </Alert>
      )}
      <Button color="primary" margin="small 0" interaction={ok && !award.isPending ? "enabled" : "disabled"} onClick={() => award.mutate()}>
        Award badge
      </Button>
    </View>
  );
}

export const BULK_STATUS: Record<BulkRow["status"], string> = {
  will_award: "Will be awarded",
  awarded: "Awarded",
  awaiting_confirmation: "Recorded; a second member of staff must confirm",
  already_awarded: "Already has this badge",
  pending_confirmation: "Already waiting for confirmation",
  not_in_course: "Not a student in this badge's course",
  not_found: "No student with this ID or email",
  duplicate: "Listed more than once",
  failed: "Could not be awarded",
};

/** Award one badge to a list of student ID numbers or emails, e.g. a volunteering log or a
 * workshop register kept outside Canvas. Always previews before awarding. */
function BulkAward() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [badge, setBadge] = useState("");
  const [list, setList] = useState("");
  const [justification, setJustification] = useState("");
  const [preview, setPreview] = useState<BulkAwardResult | null>(null);
  const badges = useQuery({
    queryKey: ["achievements", "published"],
    queryFn: () => apiFetch<{ items: DefinitionSummary[] }>("/api/v1/achievements?state=published", token),
  });
  const run = useMutation({
    mutationFn: (confirm: boolean) =>
      apiSend<BulkAwardResult>("/api/v1/awards/bulk", token, "POST", {
        definition_id: badge,
        identifiers: [list],
        justification,
        confirm,
      }),
    onSuccess: (res) => {
      setPreview(res);
      if (res.committed) qc.invalidateQueries({ queryKey: ["awards"] });
    },
  });
  const reset = () => setPreview(null);
  const ok = badge && list.trim() && justification.trim().length >= 20;
  const toAward = preview && !preview.committed ? (preview.counts.will_award ?? 0) : 0;
  return (
    <View as="section" aria-labelledby="bulk-h" display="block" margin="large 0 0">
      <Heading level="h2" id="bulk-h">
        Award a badge to a list
      </Heading>
      <Text as="p">
        For evidence kept outside Canvas, such as a volunteering log or a workshop register. Paste student ID numbers
        or university emails, one per line or separated by commas. Only students enrolled in the badge's course can
        receive it. You will see who matches before anything is awarded.
      </Text>
      <SimpleSelect
        renderLabel="Badge to award"
        value={badge || undefined}
        placeholder="Choose a published badge"
        onChange={(_e, { value }) => {
          setBadge(String(value));
          reset();
        }}
      >
        {(badges.data?.items ?? []).map((b) => (
          <SimpleSelect.Option key={b.id} id={`bb-${b.id}`} value={b.id}>
            {b.title}
          </SimpleSelect.Option>
        ))}
      </SimpleSelect>
      <TextArea
        label="Student ID numbers or emails"
        height="8rem"
        value={list}
        onChange={(e) => {
          setList(e.target.value);
          reset();
        }}
      />
      <TextArea
        label="Justification for everyone on the list (at least 20 characters)"
        value={justification}
        onChange={(e) => {
          setJustification(e.target.value);
          reset();
        }}
      />
      {run.isError && <ErrorAlert error={run.error} />}
      <Flex gap="small" margin="small 0">
        <Button interaction={ok && !run.isPending ? "enabled" : "disabled"} onClick={() => run.mutate(false)}>
          Check the list
        </Button>
        {toAward > 0 && (
          <Button color="primary" interaction={run.isPending ? "disabled" : "enabled"} onClick={() => run.mutate(true)}>
            {`Award to ${toAward} ${toAward === 1 ? "learner" : "learners"}`}
          </Button>
        )}
      </Flex>
      {preview && (
        <>
          <Alert variant={preview.committed ? "success" : "info"} margin="small 0">
            {preview.committed
              ? `Done: ${preview.counts.awarded ?? 0} awarded, ${preview.counts.awaiting_confirmation ?? 0} waiting for a second member of staff.`
              : toAward
                ? `${toAward} of ${preview.rows.length} entries will be awarded. Check the rest below.`
                : "Nobody on this list can be awarded. Check the entries below."}
          </Alert>
          <TableScroll>
            <Table caption={preview.committed ? "List award results" : "List award preview"}>
              <Table.Head>
                <Table.Row>
                  <Table.ColHeader id="b-id">Entry</Table.ColHeader>
                  <Table.ColHeader id="b-who">Learner</Table.ColHeader>
                  <Table.ColHeader id="b-st">Result</Table.ColHeader>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {preview.rows.map((r, i) => (
                  <Table.Row key={`${r.identifier}-${i}`}>
                    <Table.RowHeader>{r.identifier}</Table.RowHeader>
                    <Table.Cell>{r.learner_name ?? ""}</Table.Cell>
                    <Table.Cell>
                      {BULK_STATUS[r.status]}
                      {r.message ? `: ${r.message}` : ""}
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </TableScroll>
        </>
      )}
    </View>
  );
}

export function Awards() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["awards"],
    queryFn: () => apiFetch<Decision[]>("/api/v1/awards?status=awaiting_confirmation", token),
  });
  return (
    <Page title="Awards to confirm">
      <Text as="p">
        These learners meet the requirements of badges that need confirmation by staff. Confirming re-checks the
        latest Canvas data first.
      </Text>
      {q.isPending && <Loading what="awards" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.length === 0 && <Text as="p">Nothing is waiting for confirmation.</Text>}
      {q.data && q.data.length > 0 && (
        <TableScroll>
        <Table caption="Awards waiting for confirmation">
          <Table.Head>
            <Table.Row>
              <Table.ColHeader id="learner">Learner</Table.ColHeader>
              <Table.ColHeader id="badge">Badge</Table.ColHeader>
              <Table.ColHeader id="why">Why</Table.ColHeader>
              <Table.ColHeader id="act">Decision</Table.ColHeader>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {q.data.map((d) => (
              <DecisionRow key={d.id} d={d} />
            ))}
          </Table.Body>
        </Table>
        </TableScroll>
      )}
      <ManualAward />
      <BulkAward />
    </Page>
  );
}
