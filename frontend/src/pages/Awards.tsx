// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Award badges: one page, three ways. Awards waiting for staff to confirm (one at a time or all
 * at once), an award to one student with a justification, and an award to a pasted list.
 */
import {
  Alert,
  Button,
  Checkbox,
  Flex,
  Heading,
  List,
  SimpleSelect,
  Table,
  Tabs,
  Text,
  TextArea,
  TextInput,
  View,
} from "@instructure/ui";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import {
  apiFetch,
  apiSend,
  type BulkAwardResult,
  type BulkRow,
  type ConfirmAllResult,
  type CourseProgress,
  type Decision,
  type DefinitionSummary,
} from "../api";
import { useAuth } from "../auth";
import { ChoiceSelect } from "../components/ChoiceSelect";
import { ConfirmButton } from "../components/ConfirmButton";
import { LimitedTextArea, SearchSelect } from "../components/Fields";
import { ErrorAlert, Loading, Page } from "../components/Page";
import { TableScroll } from "../components/TableScroll";

export const EVIDENCE_KINDS: Record<string, string> = {
  lecturer_confirmation: "Staff confirmation",
  assessment_result: "Assessment result",
  completion_record: "Completion record",
  evaluation_statement: "Evaluation statement",
  artefact: "Student's work (artefact)",
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
  const who = d.learner_name ?? "this student";
  return (
    <Table.Row>
      <Table.RowHeader>{who}</Table.RowHeader>
      <Table.Cell>{d.badge_title}</Table.Cell>
      <Table.Cell>{d.kind === "manual" ? "Manual award (needs a second approver)" : "Requirements met"}</Table.Cell>
      <Table.Cell>
        {act.isError && <ErrorAlert error={act.error} />}
        {rejecting ? (
          <View as="div" display="block">
            <TextInput maxLength={2000} renderLabel={`Reason for not awarding to ${who}`} value={reason} onChange={(_e, v) => setReason(v)} />
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
  // Badges with a live version, including one whose next version is still being drafted: the
  // published version stays awardable until the new one replaces it (same list as "A list").
  const badges = useQuery({
    queryKey: ["achievements", "awardable"],
    queryFn: () => apiFetch<{ items: DefinitionSummary[] }>("/api/v1/achievements?awardable=true", token),
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
    <View as="section" aria-labelledby="manual-h" display="block">
      <Heading level="h2" id="manual-h">
        Award a badge to one student
      </Heading>
      <Text as="p">
        Use this when a student has met the outcomes in a way Canvas cannot show. Your justification is kept in the
        audit record; only evidence you mark as public appears on the badge.
      </Text>
      <ChoiceSelect
        label="Badge"
        value={badge}
        placeholder="Choose a published badge"
        options={(badges.data?.items ?? []).map((b) => ({ value: b.id, label: b.title }))}
        onChange={(value) => {
          setBadge(value);
          setLearner("");
        }}
      />
      <SearchSelect
        label="Student"
        things="students"
        placeholder={badge ? "Type a name, or choose from the list" : "Choose a badge first"}
        options={(learners.data?.learners ?? []).map((l) => ({ id: l.user_id, label: l.name ?? l.user_id }))}
        value={learner}
        onChange={setLearner}
      />
      <LimitedTextArea maxLength={4000}
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
      <LimitedTextArea maxLength={2000} label="Evidence description (optional)" value={narrative} onChange={(e) => setNarrative(e.target.value)} />
      <Checkbox label="Show this evidence on the public badge" checked={pub} onChange={(e) => setPub(e.target.checked)} />
      {award.isError && <ErrorAlert error={award.error} />}
      {award.isSuccess && (
        <Alert variant="success" margin="small 0">
          {award.data.status === "awaiting_confirmation"
            ? "Recorded. A second member of staff must confirm it before it is issued."
            : "Awarded. The badge will be issued shortly."}
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
  not_found: "No student in this badge's course has this ID or email",
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
    queryKey: ["achievements", "awardable"],
    queryFn: () => apiFetch<{ items: DefinitionSummary[] }>("/api/v1/achievements?awardable=true", token),
  });
  const chosen = badges.data?.items.find((b) => b.id === badge);
  const refresh = useMutation({
    mutationFn: () => apiSend<unknown>(`/api/v1/courses/${chosen?.course_id}/sync`, token, "POST"),
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
  const reasonLength = justification.trim().length;
  const ok = badge && list.trim() && reasonLength >= 20;
  const toAward = preview && !preview.committed ? (preview.counts.will_award ?? 0) : 0;
  const notFound = preview?.counts.not_found ?? 0;
  const learners = (n: number) => `${n} ${n === 1 ? "student" : "students"}`;
  return (
    <View as="section" aria-labelledby="bulk-h" display="block">
      <Heading level="h2" id="bulk-h">
        Award a badge to a list of students
      </Heading>
      <Text as="p">
        For evidence kept outside Canvas, such as a volunteering log or a workshop register. Paste student ID numbers
        or university emails, one per line or separated by commas. Only students enrolled in the badge's course can
        receive it. You will see who matches before anything is awarded.
      </Text>
      <ChoiceSelect
        label="Badge to award"
        value={badge}
        placeholder="Choose a badge you can award"
        options={(badges.data?.items ?? []).map((b) => ({
          value: b.id,
          label: b.course_title ? `${b.title} (${b.course_title})` : b.title,
        }))}
        onChange={(value) => {
          setBadge(value);
          reset();
        }}
      />
      <TextArea
        label="Student ID numbers or emails"
        height="8rem"
        value={list}
        onChange={(e) => {
          setList(e.target.value);
          reset();
        }}
      />
      <LimitedTextArea maxLength={4000}
        label="Justification for everyone on the list (at least 20 characters)"
        value={justification}
        onChange={(e) => {
          setJustification(e.target.value);
          reset();
        }}
      />
      {reasonLength < 20 && (
        <Text as="p" size="small">
          {`${reasonLength} of at least 20 characters.`}
        </Text>
      )}
      {chosen && (
        <Text as="p" size="small">
          {`Awarded to students of ${chosen.course_title ?? "the badge's course"}.`}
        </Text>
      )}
      {run.isError && <ErrorAlert error={run.error} />}
      <Flex gap="small" margin="small 0">
        <Button interaction={ok && !run.isPending ? "enabled" : "disabled"} onClick={() => run.mutate(false)}>
          Check the list
        </Button>
        {toAward > 0 && (
          <Button color="primary" interaction={run.isPending ? "disabled" : "enabled"} onClick={() => run.mutate(true)}>
            {preview?.second_approval ? `Record for ${learners(toAward)}` : `Award to ${learners(toAward)}`}
          </Button>
        )}
      </Flex>
      {preview && (
        <>
          <div role="status">
            <Alert variant={preview.committed ? "success" : "info"} margin="small 0">
              {preview.committed
                ? `Done: ${preview.counts.awarded ?? 0} awarded, ${preview.counts.awaiting_confirmation ?? 0} waiting for a second member of staff.`
                : toAward
                  ? `${toAward} of ${preview.rows.length} entries will be awarded.${
                      preview.second_approval
                        ? " A second member of staff must confirm each award before it is issued."
                        : ""
                    } Check the rest below.`
                  : "Nobody on this list can be awarded. Check the entries below."}
            </Alert>
          </div>
          {notFound > 0 && chosen?.course_id && (
            <View as="div" margin="small 0">
              <Text as="p">
                Students who joined the course in Canvas today may not be listed yet. Refresh the course from Canvas,
                wait a minute, then check the list again.
              </Text>
              <Button
                interaction={refresh.isPending || refresh.isSuccess ? "disabled" : "enabled"}
                onClick={() => refresh.mutate()}
              >
                Refresh the course from Canvas
              </Button>
              {refresh.isSuccess && (
                <Text as="p" role="status">
                  Refresh started. Check the list again in a minute.
                </Text>
              )}
              {refresh.isError && <ErrorAlert error={refresh.error} />}
            </View>
          )}
          <TableScroll>
            <Table caption={preview.committed ? "List award results" : "List award preview"}>
              <Table.Head>
                <Table.Row>
                  <Table.ColHeader id="b-id">Entry</Table.ColHeader>
                  <Table.ColHeader id="b-who">Student</Table.ColHeader>
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

/** Most waiting awards the page asks for, and the most one "award all" may carry. */
const MOST = 500;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Awards waiting for staff to confirm: each on its own, or everyone shown in one go. */
function Waiting({ q }: { q: UseQueryResult<Decision[]> }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [badge, setBadge] = useState("");
  const [done, setDone] = useState<ConfirmAllResult | null>(null);
  const rows = q.data ?? [];
  const badges = [...new Map(rows.map((d) => [d.definition_id, d.badge_title])).entries()];
  // A badge with nothing left waiting drops out of the filter, back to everything.
  const only = badges.some(([id]) => id === badge) ? badge : "";
  const shown = only ? rows.filter((d) => d.definition_id === only) : rows;
  // Manual awards need their justification read by a second person, so they stay one by one.
  const ready = shown.filter((d) => d.kind !== "manual");
  const manual = shown.length - ready.length;
  const all = useMutation({
    mutationFn: () =>
      apiSend<ConfirmAllResult>("/api/v1/awards/confirm-all", token, "POST", { decision_ids: ready.map((d) => d.id) }),
    onSuccess: (res) => {
      setDone(res);
      qc.invalidateQueries({ queryKey: ["awards"] });
    },
  });
  const left = done?.rows.filter((r) => !r.confirmed) ?? [];
  return (
    <>
      <Text as="p">
        These students meet the requirements of badges that staff confirm. Each award is checked against the latest
        Canvas data before it is made.
      </Text>
      {q.isPending && <Loading what="awards" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {all.isError && <ErrorAlert error={all.error} />}
      {done && (
        <div role="status">
          <Alert variant={left.length ? "warning" : "success"} margin="small 0">
            {`${plural(done.confirmed, "badge", "badges")} awarded.`}
            {left.length > 0 &&
              ` ${plural(left.length, "award was", "awards were")} not made and ${left.length === 1 ? "is" : "are"} still on the list:`}
            {left.length > 0 && (
              <List margin="x-small 0 0">
                {left.map((r) => (
                  <List.Item key={r.id}>{`${r.learner_name ?? "A student"}, ${r.badge_title}: ${r.message ?? "could not be awarded"}`}</List.Item>
                ))}
              </List>
            )}
          </Alert>
        </div>
      )}
      {q.data && rows.length === 0 && <Text as="p">Nothing is waiting for confirmation.</Text>}
      {rows.length >= MOST && (
        <Text as="p">{`Showing the first ${MOST}. The rest will appear as you work through these.`}</Text>
      )}
      {badges.length > 1 && (
        <View as="div" maxWidth="28rem" margin="0 0 small">
          <SimpleSelect renderLabel="Show" value={only || "all"} onChange={(_e, { value }) => setBadge(value === "all" ? "" : String(value))}>
            <SimpleSelect.Option id="wb-all" value="all">
              {`All badges (${rows.length})`}
            </SimpleSelect.Option>
            {badges.map(([id, title]) => (
              <SimpleSelect.Option key={id} id={`wb-${id}`} value={id}>
                {`${title} (${rows.filter((d) => d.definition_id === id).length})`}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
        </View>
      )}
      {ready.length > 1 && (
        <View as="div" margin="0 0 small">
          {all.isPending ? (
            <Text as="p" role="status">{`Awarding ${ready.length} badges. This can take a minute.`}</Text>
          ) : (
            <ConfirmButton
              color="primary"
              confirmColor="primary"
              label={`Award all ${ready.length}`}
              consequence={
                `${ready.length} badges will be awarded now${only ? `, all for ${badges.find(([id]) => id === only)?.[1]}` : ""}. ` +
                "Each student is checked against the latest Canvas data first, and anyone who no longer qualifies stays on this list." +
                (manual
                  ? ` ${plural(manual, "manual award is", "manual awards are")} not included: a second member of staff confirms those one at a time.`
                  : "")
              }
              confirmLabel={`Yes, award all ${ready.length}`}
              cancelLabel="Not yet"
              onConfirm={() => all.mutate()}
            />
          )}
        </View>
      )}
      {shown.length > 0 && (
        <TableScroll>
          <Table caption="Awards waiting for confirmation">
            <Table.Head>
              <Table.Row>
                <Table.ColHeader id="learner">Student</Table.ColHeader>
                <Table.ColHeader id="badge">Badge</Table.ColHeader>
                <Table.ColHeader id="why">Why</Table.ColHeader>
                <Table.ColHeader id="act">Decision</Table.ColHeader>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {shown.map((d) => (
                <DecisionRow key={d.id} d={d} />
              ))}
            </Table.Body>
          </Table>
        </TableScroll>
      )}
    </>
  );
}

const TABS = ["waiting", "student", "list"] as const;

export function Awards() {
  const { token } = useAuth();
  // The tab lives in the address (/awards?tab=list), so a refresh or a shared link lands on it.
  const [params, setParams] = useSearchParams();
  const tab = Math.max(0, TABS.findIndex((t) => t === params.get("tab")));
  const q = useQuery({
    queryKey: ["awards"],
    queryFn: () => apiFetch<Decision[]>(`/api/v1/awards?status=awaiting_confirmation&limit=${MOST}`, token),
  });
  const count = q.data?.length ?? 0;
  const show = (index: number) =>
    setParams(
      (before) => {
        const next = new URLSearchParams(before);
        if (index) next.set("tab", TABS[index]);
        else next.delete("tab");
        return next;
      },
      { replace: true },
    );
  // Panels stay mounted when hidden, so a half-written justification survives a look at another tab.
  return (
    <Page title="Award badges">
      <Tabs onRequestTabChange={(_e, { index }) => show(index)}>
        <Tabs.Panel
          id="awards-waiting"
          renderTitle={count ? `Waiting to confirm (${count >= MOST ? `${MOST}+` : count})` : "Waiting to confirm"}
          isSelected={tab === 0}
          unmountOnExit={false}
        >
          <Waiting q={q} />
        </Tabs.Panel>
        <Tabs.Panel id="awards-student" renderTitle="One student" isSelected={tab === 1} unmountOnExit={false}>
          <ManualAward />
        </Tabs.Panel>
        <Tabs.Panel id="awards-list" renderTitle="A list of students" isSelected={tab === 2} unmountOnExit={false}>
          <BulkAward />
        </Tabs.Panel>
      </Tabs>
    </Page>
  );
}
