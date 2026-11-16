// SPDX-License-Identifier: AGPL-3.0-or-later
/** Student view: each badge in my courses with confirmed and pending requirements (spec §8.1-8.2). */
import { Alert, Flex, Heading, Img, List, Pill, ProgressBar, Text, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";

import { apiFetch, type LearnerBadge, type Requirement } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ErrorAlert, Loading, Page } from "../components/Page";

export const BADGE_STATUS: Record<string, { label: string; color: "success" | "info" | "warning" | "primary" | "danger" }> = {
  earned: { label: "Earned", color: "success" },
  revoked: { label: "Withdrawn by the issuer", color: "danger" },
  suspended: { label: "Suspended by the issuer", color: "warning" },
  awarded: { label: "Awarded: being issued", color: "success" },
  awaiting_confirmation: { label: "Awaiting confirmation by course staff", color: "info" },
  requirements_met: { label: "Requirements met", color: "info" },
  pending: { label: "Waiting for information", color: "warning" },
  in_progress: { label: "In progress", color: "primary" },
  not_awarded: { label: "Not awarded", color: "warning" },
};

/** Statuses where the student already has the badge, so requirement progress no longer applies. */
const HELD = new Set(["earned", "awarded"]);

/** The badge was issued and the issuer has since taken it back, for good or for now. */
const WITHDRAWN: Record<string, string> = {
  revoked:
    "The issuer has withdrawn this badge, so it no longer counts as valid and anyone checking it is told so. The badge's page gives the reason.",
  suspended:
    "The issuer has suspended this badge for now, so anyone checking it is told it is not currently valid. The badge's page gives the reason.",
};

/** Joins a requirement and its state without doubling punctuation ("quiz.: Awaiting" reads badly). */
export function requirementText(description: string, label: string): string {
  return `${description.replace(/[.:;\s]+$/, "")}: ${label}`;
}

function RequirementItem({ r }: { r: Requirement }) {
  const mark = r.status === "complete" ? "✓" : r.status === "pending" ? "…" : "○";
  return (
    <List.Item>
      <span aria-hidden="true">{mark} </span>
      <Text weight={r.confirmed ? "bold" : "normal"}>{requirementText(r.description, r.label)}</Text>
      {r.children && (
        <List margin="xx-small 0 0">
          {r.children.map((c) => (
            <List.Item key={c.rule_id}>{requirementText(c.description, c.label)}</List.Item>
          ))}
        </List>
      )}
    </List.Item>
  );
}

function RequirementProgress({ b }: { b: LearnerBadge }) {
  const confirmed = b.requirements.filter((r) => r.status === "complete");
  const pending = b.requirements.filter((r) => r.status === "pending");
  const todo = b.requirements.filter((r) => r.status === "incomplete");
  return (
    <>
      <ProgressBar
        screenReaderLabel={`${b.title} progress`}
        valueNow={b.progress.completed}
        valueMax={Math.max(b.progress.total, 1)}
        renderValue={() => (
          <Text size="small">
            {b.progress.completed} of {b.progress.total} confirmed
            {b.progress.mode === "ANY" ? " (any one is enough)" : ""}
          </Text>
        )}
      />
      {confirmed.length > 0 && (
        <>
          <Heading level="h3">Confirmed</Heading>
          <List isUnstyled>{confirmed.map((r) => <RequirementItem key={r.rule_id} r={r} />)}</List>
        </>
      )}
      {pending.length > 0 && (
        <>
          <Heading level="h3">Pending</Heading>
          <List isUnstyled>{pending.map((r) => <RequirementItem key={r.rule_id} r={r} />)}</List>
        </>
      )}
      {todo.length > 0 && (
        <>
          <Heading level="h3">Still to do</Heading>
          <List isUnstyled>{todo.map((r) => <RequirementItem key={r.rule_id} r={r} />)}</List>
        </>
      )}
    </>
  );
}

/** "Waiting for information" is vague when the only thing missing is a member of staff. */
function statusOf(b: LearnerBadge) {
  const waiting = b.requirements.filter((r) => r.status === "pending");
  if (b.status === "pending" && waiting.length > 0 && waiting.every((r) => r.type === "manual_approval")) {
    return { label: "Waiting for staff to confirm", color: "info" as const };
  }
  return BADGE_STATUS[b.status] ?? { label: b.status, color: "primary" as const };
}

function BadgeCard({ b }: { b: LearnerBadge }) {
  const status = statusOf(b);
  const headingId = `badge-${b.version_id}`;
  // A badge the student holds is theirs, however it was awarded. Course staff can award one by
  // hand without every requirement being recorded as met, so the requirement list would say
  // "Pending" next to "Earned". Show the award instead of the progress.
  const held = HELD.has(b.status);
  return (
    <View as="section" aria-labelledby={headingId} padding="medium" borderWidth="small" borderRadius="medium" margin="0 0 medium" display="block">
      <Flex gap="medium" alignItems="start">
        {b.image.data_url && <Img src={b.image.data_url} alt={b.image.alt_text ?? ""} width="6rem" height="6rem" constrain="contain" />}
        <Flex.Item shouldGrow shouldShrink>
          <Heading level="h2" id={headingId}>
            {b.title}
          </Heading>
          <Text as="p" size="small">
            {b.course.title} · {b.category} · {b.issuer}
          </Text>
          <Pill color={status.color}>{status.label}</Pill>
          <Text as="p">{b.short_description}</Text>
          {b.credential_id && (
            <Text as="p">
              <AppLink to={`/me/credentials/${b.credential_id}`}>
                {WITHDRAWN[b.status] ? "See this badge and why it was withdrawn" : "View, download or share this badge"}
              </AppLink>
            </Text>
          )}
          {WITHDRAWN[b.status] ? (
            <Text as="p">{WITHDRAWN[b.status]}</Text>
          ) : held ? (
            <Text as="p">You have this badge. Nothing more is needed from you.</Text>
          ) : (
            <RequirementProgress b={b} />
          )}
        </Flex.Item>
      </Flex>
    </View>
  );
}

export function MyProgress() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["my-achievements"],
    queryFn: () => apiFetch<LearnerBadge[]>("/api/v1/learners/me/achievements", token),
  });
  return (
    <Page title="Badges in my courses">
      <Alert variant="info" margin="0 0 medium">
        Progress comes from Canvas and may be up to an hour old. A requirement only counts as confirmed once
        Canvas confirms it; unreleased marks show as pending.
      </Alert>
      {q.isPending && <Loading what="the badges in your courses" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.length === 0 && <Text as="p">There are no badges available in your courses yet.</Text>}
      {q.data?.map((b) => <BadgeCard key={b.version_id} b={b} />)}
    </Page>
  );
}
