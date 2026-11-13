// SPDX-License-Identifier: AGPL-3.0-or-later
/** Audit log (spec §10.6): actor, action, affected resource and time, with CSV export. */
import { Button, Flex, SimpleSelect, Table, Text, TextInput } from "@instructure/ui";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, type AuditItem } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage, DownloadButton, fmtDate } from "./AdminPage";

interface AuditPage {
  items: AuditItem[];
  next_before: string | null;
}

export function Audit() {
  const { token } = useAuth();
  const [category, setCategory] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const cats = useQuery({ queryKey: ["audit-cats"], queryFn: () => apiFetch<string[]>("/api/v1/admin/audit/categories", token) });
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (/^\d{4}-\d{2}-\d{2}$/.test(since)) params.set("since", since);
  if (/^\d{4}-\d{2}-\d{2}$/.test(until)) params.set("until", until);
  const qs = params.toString();
  const q = useInfiniteQuery({
    queryKey: ["audit", qs],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      apiFetch<AuditPage>(`/api/v1/admin/audit?${qs}${pageParam ? `&before=${pageParam}` : ""}`, token),
    getNextPageParam: (last) => last.next_before ?? undefined,
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <AdminPage title="Audit log" instOnly>
      <Text as="p">
        Every significant action is recorded with who did it and when. Learners appear only as identifiers; use the
        personal data page to answer a request about a specific person.
      </Text>
      <Flex gap="small" alignItems="end" wrap="wrap" margin="0 0 small">
        <SimpleSelect renderLabel="Kind of action" value={category} onChange={(_e, { value }) => setCategory(String(value))} width="18rem">
          <SimpleSelect.Option id="cat-all" value="">
            Everything
          </SimpleSelect.Option>
          {(cats.data ?? []).map((c) => (
            <SimpleSelect.Option key={c} id={`cat-${c}`} value={c}>
              {c}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
        <TextInput renderLabel="From (YYYY-MM-DD)" value={since} onChange={(_e, v) => setSince(v)} width="11rem" />
        <TextInput renderLabel="To (YYYY-MM-DD)" value={until} onChange={(_e, v) => setUntil(v)} width="11rem" />
        <DownloadButton path={`/api/v1/admin/audit.csv${qs ? `?${qs}` : ""}`} filename="audit-log.csv">
          Download CSV
        </DownloadButton>
      </Flex>
      {q.isPending && <Loading what="audit log" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {items.length > 0 && (
        <Table caption="Audit events, newest first">
          <Table.Head>
            <Table.Row>
              <Table.ColHeader id="a-at">When</Table.ColHeader>
              <Table.ColHeader id="a-who">Who</Table.ColHeader>
              <Table.ColHeader id="a-what">Action</Table.ColHeader>
              <Table.ColHeader id="a-res">Affected</Table.ColHeader>
              <Table.ColHeader id="a-data">Details</Table.ColHeader>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {items.map((e) => (
              <Table.Row key={e.id}>
                <Table.Cell>{fmtDate(e.at)}</Table.Cell>
                <Table.Cell>{e.actor_name ?? (e.actor_kind === "system" ? "System" : (e.actor_user_id ?? ""))}</Table.Cell>
                <Table.RowHeader>
                  {e.action}
                  <Text as="div" size="small">
                    {e.category}
                  </Text>
                </Table.RowHeader>
                <Table.Cell>
                  {e.resource_type} {e.resource_id ?? ""}
                </Table.Cell>
                <Table.Cell>
                  <Text size="small">{Object.keys(e.data).length ? JSON.stringify(e.data) : ""}</Text>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
      )}
      {q.hasNextPage && (
        <Button margin="small 0" onClick={() => q.fetchNextPage()} interaction={q.isFetchingNextPage ? "disabled" : "enabled"}>
          Show older events
        </Button>
      )}
    </AdminPage>
  );
}
