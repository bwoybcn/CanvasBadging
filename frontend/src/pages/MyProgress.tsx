// SPDX-License-Identifier: AGPL-3.0-or-later
/** Student view: each badge in my courses with confirmed and pending requirements (spec §8.1-8.2). */
import { Alert, Flex, Heading, Img, List, Pill, ProgressBar, Text, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";

import { apiFetch, type LearnerBadge, type Requirement } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ErrorAlert, Loading, Page } from "../components/Page";

export const BADGE_STATUS: Record<string, { label: string; color: "success" | "info" | "warning" | "primary" }> = {
  earned: { label: "Earned", color: "success" },
  awarded: { label: "Awarded: being issued", color: "success" },
  awaiting_confirmation: { label: "Awaiting confirmation by course staff", color: "info" },
  requirements_met: { label: "Requirements met", color: "info" },
  pending: { label: "Waiting for information", color: "warning" },
  in_progress: { label: "In progress", color: "primary" },
  not_awarded: { label: "Not awarded", color: "warning" },
};

function RequirementItem({ r }: { r: Requirement }) {
  const mark = r.status === "complete" ? "✓" : r.status === "pending" ? "…" : "○";
  return (
    <List.Item>
      <span aria-hidden="true">{mark} </span>
      <Text weight={r.confirmed ? "bold" : "normal"}>{r.description}</Text>
      <Text>: {r.label}</Text>
      {r.children && (
        <List margin="xx-small 0 0">
          {r.children.map((c) => (
            <List.Item key={c.rule_id}>
              {c.description}: {c.label}
            </List.Item>
          ))}
        </List>
      )}
    </List.Item>
  );
}

function BadgeCard({ b }: { b: LearnerBadge }) {
  const status = BADGE_STATUS[b.status] ?? { label: b.status, color: "primary" as const };
  const confirmed = b.requirements.filter((r) => r.status === "complete");
  const pending = b.requirements.filter((r) => r.status === "pending");
  const todo = b.requirements.filter((r) => r.status === "incomplete");
  const headingId = `badge-${b.version_id}`;
  return (
    <View as="section" aria-labelledby={headingId} padding="medium" borderWidth="small" borderRadius="medium" margin="0 0 medium" display="block">
      <Flex gap="medium" alignItems="start">
        {b.image.data_url && <Img src={b.image.data_url} alt={b.image.alt_text ?? ""} width="6rem" height="6rem" constrain="contain" />}
        <Flex.Item shouldGrow shouldShrink>
          <Heading level="h3" id={headingId}>
            {b.title}
          </Heading>
          <Text as="p" size="small">
            {b.course.title} · {b.category} · {b.issuer}
          </Text>
          <Pill color={status.color}>{status.label}</Pill>
          <Text as="p">{b.short_description}</Text>
          {b.credential_id && (
            <Text as="p">
              <AppLink to={`/me/credentials/${b.credential_id}`}>View, download or share this credential</AppLink>
            </Text>
          )}
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
              <Heading level="h4">Confirmed</Heading>
              <List isUnstyled>{confirmed.map((r) => <RequirementItem key={r.rule_id} r={r} />)}</List>
            </>
          )}
          {pending.length > 0 && (
            <>
              <Heading level="h4">Pending</Heading>
              <List isUnstyled>{pending.map((r) => <RequirementItem key={r.rule_id} r={r} />)}</List>
            </>
          )}
          {todo.length > 0 && (
            <>
              <Heading level="h4">Still to do</Heading>
              <List isUnstyled>{todo.map((r) => <RequirementItem key={r.rule_id} r={r} />)}</List>
            </>
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
    <Page title="My badges">
      <Alert variant="info" margin="0 0 medium">
        Progress comes from Canvas and may be up to an hour old. A requirement only counts as confirmed once
        Canvas confirms it; unreleased marks show as pending.
      </Alert>
      {q.isPending && <Loading what="your badges" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.length === 0 && <Text as="p">There are no badges available in your courses yet.</Text>}
      {q.data?.map((b) => <BadgeCard key={b.version_id} b={b} />)}
    </Page>
  );
}
