// SPDX-License-Identifier: AGPL-3.0-or-later
/** Basic operational reporting with CSV export (spec §10.5). */
import { Flex, Heading, Table, Text, TextInput, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, type ReportSummary } from "../../api";
import { useAuth } from "../../auth";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage, DownloadButton } from "./AdminPage";
import { TableScroll } from "../../components/TableScroll";

export function Reports() {
  const { token } = useAuth();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const params = new URLSearchParams();
  if (/^\d{4}-\d{2}-\d{2}$/.test(from)) params.set("issued_from", from);
  if (/^\d{4}-\d{2}-\d{2}$/.test(to)) params.set("issued_to", to);
  const qs = params.toString() ? `?${params}` : "";
  const q = useQuery({
    queryKey: ["report-summary", from, to],
    queryFn: () => apiFetch<ReportSummary>(`/api/v1/admin/reports/summary${qs}`, token),
  });
  const s = q.data;
  return (
    <AdminPage title="Reports">
      <Flex gap="small" alignItems="end" wrap="wrap" margin="0 0 medium">
        <TextInput renderLabel="Issued from (YYYY-MM-DD)" value={from} onChange={(_e, v) => setFrom(v)} width="12rem" />
        <TextInput renderLabel="Issued to (YYYY-MM-DD)" value={to} onChange={(_e, v) => setTo(v)} width="12rem" />
        <DownloadButton path={`/api/v1/admin/reports/summary.csv${qs}`} filename="issuance-summary.csv">
          Download summary CSV
        </DownloadButton>
        <DownloadButton path={`/api/v1/admin/reports/issuance.csv${qs}`} filename="issuance-records.csv">
          Download all records CSV
        </DownloadButton>
      </Flex>
      {q.isPending && <Loading what="report" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {s && (
        <>
          <Text as="p">
            {s.issued} issued, {s.revoked} revoked, {s.active} active. {s.pending_awards.awaiting_confirmation} awards
            waiting for confirmation and {s.pending_awards.awaiting_issuance} waiting to be issued.{" "}
            {s.failed_issuance.credentials_not_issued} badges not issued and {s.failed_issuance.failed_jobs} failed
            jobs.
          </Text>
          <CountTable caption="Issuance by course" rows={s.by_course.map((c) => [c.course_title, c.issued, c.revoked])} />
          <CountTable
            caption="Issuance by badge"
            rows={s.by_badge.map((b) => [`${b.badge_title}${b.course_title ? ` (${b.course_title})` : ""}`, b.issued, b.revoked])}
          />
          <CountTable caption="Issuance by month" rows={s.by_month.map((m) => [m.month, m.issued, null])} />
        </>
      )}
    </AdminPage>
  );
}

function CountTable({ caption, rows }: { caption: string; rows: [string, number, number | null][] }) {
  return (
    <View as="section" display="block" margin="0 0 medium">
      <Heading level="h2" margin="0 0 small">
        {caption}
      </Heading>
      {rows.length === 0 ? (
        <Text as="p">Nothing issued in this period.</Text>
      ) : (
        <TableScroll>
        <Table caption={caption}>
          <Table.Head>
            <Table.Row>
              <Table.ColHeader id={`${caption}-n`}>Name</Table.ColHeader>
              <Table.ColHeader id={`${caption}-i`}>Issued</Table.ColHeader>
              {rows[0][2] !== null && <Table.ColHeader id={`${caption}-r`}>Revoked</Table.ColHeader>}
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {rows.map(([name, issued, revoked]) => (
              <Table.Row key={name}>
                <Table.RowHeader>{name}</Table.RowHeader>
                <Table.Cell>{issued}</Table.Cell>
                {revoked !== null && <Table.Cell>{revoked}</Table.Cell>}
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        </TableScroll>
      )}
    </View>
  );
}
