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

import { apiFetch, apiSend, type CourseProgress, type Decision, type DefinitionSummary } from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Loading, Page } from "../components/Page";
import { TableScroll } from "../components/TableScroll";

export const EVIDENCE_KINDS: Record<string, string> = {
  lecturer_confirmation: "Lecturer confirmation",
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

export function Awards() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["awards"],
    queryFn: () => apiFetch<Decision[]>("/api/v1/awards?status=awaiting_confirmation", token),
  });
  return (
    <Page title="Awards to confirm">
      <Text as="p">
        These learners meet the requirements of badges that need a lecturer's confirmation. Confirming re-checks the
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
    </Page>
  );
}
