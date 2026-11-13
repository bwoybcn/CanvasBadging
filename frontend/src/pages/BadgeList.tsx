// SPDX-License-Identifier: AGPL-3.0-or-later
import { Button, Pill, Table, Text } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { apiFetch, POLICY_LABELS, STATE_LABELS, type DefinitionSummary } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ErrorAlert, Loading, Page } from "../components/Page";
import { TableScroll } from "../components/TableScroll";

function BadgeTable({ items, caption }: { items: DefinitionSummary[]; caption: string }) {
  return (
    <TableScroll>
    <Table caption={caption} margin="0 0 medium">
      <Table.Head>
        <Table.Row>
          <Table.ColHeader id="title">Badge</Table.ColHeader>
          <Table.ColHeader id="state">Status</Table.ColHeader>
          <Table.ColHeader id="category">Category</Table.ColHeader>
          <Table.ColHeader id="policy">Awarding</Table.ColHeader>
          <Table.ColHeader id="version">Version</Table.ColHeader>
        </Table.Row>
      </Table.Head>
      <Table.Body>
        {items.map((b) => (
          <Table.Row key={b.id}>
            <Table.RowHeader>
              <AppLink to={`/badges/${b.id}`}>{b.title || "Untitled badge"}</AppLink>
            </Table.RowHeader>
            <Table.Cell>
              <Pill>{STATE_LABELS[b.state]}</Pill>
            </Table.Cell>
            <Table.Cell>{b.category || "-"}</Table.Cell>
            <Table.Cell>{POLICY_LABELS[b.award_policy] ?? "Default"}</Table.Cell>
            <Table.Cell>{b.version_no}</Table.Cell>
          </Table.Row>
        ))}
      </Table.Body>
    </Table>
    </TableScroll>
  );
}

export function BadgeList() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["achievements"],
    queryFn: () => apiFetch<{ items: DefinitionSummary[] }>("/api/v1/achievements", token),
  });
  return (
    <Page
      title="Badges"
      actions={
        <Button color="primary" onClick={() => navigate("/badges/new")}>
          Create micro-credential
        </Button>
      }
    >
      {q.isPending && <Loading what="badges" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.items.length === 0 && <Text as="p">No badges yet. Create one to get started.</Text>}
      {q.data && q.data.items.length > 0 && <BadgeTable items={q.data.items} caption="Badges in your courses" />}
    </Page>
  );
}

export function ReviewQueue() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["achievements", "review"],
    queryFn: () => apiFetch<{ items: DefinitionSummary[] }>("/api/v1/achievements?review_queue=true", token),
  });
  return (
    <Page title="Review queue">
      {q.isPending && <Loading what="review queue" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && q.data.items.length === 0 && <Text as="p">Nothing is waiting for your review.</Text>}
      {q.data && q.data.items.length > 0 && <BadgeTable items={q.data.items} caption="Badges waiting for review" />}
    </Page>
  );
}
