// SPDX-License-Identifier: AGPL-3.0-or-later
/** "My credential collection": every credential I hold, across all my courses (spec §8.1). */
import { Alert, Button, Flex, Heading, Img, Pill, ScreenReaderContent, Text, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, CREDENTIAL_STATE, type CredentialSummary, downloadFile, formatDate, problemText } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ErrorAlert, Loading, Page } from "../components/Page";

export function CredentialCard({ c }: { c: CredentialSummary }) {
  const { token } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const state = CREDENTIAL_STATE[c.status];
  const headingId = `cred-${c.id}`;
  return (
    <View as="section" aria-labelledby={headingId} padding="medium" borderWidth="small" borderRadius="medium" margin="0 0 medium" display="block">
      <Flex gap="medium" alignItems="start" wrap="wrap">
        {c.image.data_url && <Img src={c.image.data_url} alt={c.image.alt_text} width="6rem" height="6rem" constrain="contain" />}
        <Flex.Item shouldGrow shouldShrink>
          <Heading level="h3" id={headingId}>
            {c.name}
          </Heading>
          <Text as="p" size="small">
            {c.issuer_name}
            {c.issued_at ? ` · Awarded ${formatDate(c.issued_at)}` : ""}
            {c.valid_until ? ` · Expires ${formatDate(c.valid_until)}` : ""}
          </Text>
          <Flex gap="small" wrap="wrap" margin="x-small 0">
            <Pill color={state.color}>{state.label}</Pill>
            <Pill color={c.share.shared ? "info" : "primary"}>{c.share.shared ? "Shared publicly" : "Private"}</Pill>
          </Flex>
          <Flex gap="small" wrap="wrap" margin="small 0 0">
            <AppLink to={`/me/credentials/${c.id}`}>
              View, share or add to LinkedIn<ScreenReaderContent> for {c.name}</ScreenReaderContent>
            </AppLink>
            <Button
              size="small"
              onClick={() => {
                setError(null);
                downloadFile(`/api/v1/credentials/${c.id}/export`, token, "credential.json").catch((e) => setError(problemText(e)));
              }}
            >
              Download<ScreenReaderContent> {c.name}</ScreenReaderContent>
            </Button>
          </Flex>
          {error && (
            <Alert variant="error" margin="small 0 0">
              {error}
            </Alert>
          )}
        </Flex.Item>
      </Flex>
    </View>
  );
}

export function MyCredentials() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["my-credentials"],
    queryFn: () => apiFetch<CredentialSummary[]>("/api/v1/learners/me/credentials", token),
  });
  const groups = new Map<string, CredentialSummary[]>();
  for (const c of q.data ?? []) {
    const key = c.course?.title ?? "Other credentials";
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  return (
    <Page title="My credentials">
      <Text as="p">
        Every credential you have earned, from all of your courses. Credentials are private until you choose to share
        one. You can download any of them and keep it, even after you leave. <AppLink to="/me/keeping">How to keep your credentials</AppLink>
      </Text>
      {q.isPending && <Loading what="your credentials" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.length === 0 && (
        <Text as="p">
          You have not earned any credentials yet. <AppLink to="/me/progress">See the badges available in your courses</AppLink>.
        </Text>
      )}
      {[...groups.entries()].map(([course, items]) => (
        <View as="section" key={course} aria-label={course} display="block" margin="medium 0 0">
          <Heading level="h2" margin="0 0 small">
            {course}
          </Heading>
          {items.map((c) => (
            <CredentialCard key={c.id} c={c} />
          ))}
        </View>
      ))}
    </Page>
  );
}
