// SPDX-License-Identifier: AGPL-3.0-or-later
/** Administration overview: what needs attention now. */
import { Flex, Heading, Text, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";

import { apiFetch, type ReportSummary } from "../../api";
import { useAuth } from "../../auth";
import { AppLink } from "../../components/AppLink";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage } from "./AdminPage";

function Stat({ label, value, to }: { label: string; value: number; to?: string }) {
  return (
    <View as="div" borderWidth="small" borderRadius="medium" padding="small" margin="0 small small 0" minWidth="11rem">
      <Text size="x-large" weight="bold" as="div">
        {value}
      </Text>
      {to ? <AppLink to={to}>{label}</AppLink> : <Text>{label}</Text>}
    </View>
  );
}

export function AdminHome() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["report-summary", "", ""],
    queryFn: () => apiFetch<ReportSummary>("/api/v1/admin/reports/summary", token),
  });
  return (
    <AdminPage title="Administration">
      {q.isError && <ErrorAlert error={q.error} />}
      {q.isPending && <Loading what="overview" />}
      {q.data && (
        <>
          <Heading level="h2" margin="0 0 small">
            Credentials
          </Heading>
          <Flex wrap="wrap">
            <Stat label="Issued" value={q.data.issued} to="/admin/credentials" />
            <Stat label="Revoked" value={q.data.revoked} to="/admin/credentials" />
            <Stat label="Awaiting confirmation" value={q.data.pending_awards.awaiting_confirmation} to="/awards" />
            <Stat label="Awaiting issuance" value={q.data.pending_awards.awaiting_issuance} to="/admin/reconciliation" />
            <Stat
              label="Failed issuance"
              value={q.data.failed_issuance.credentials_not_issued + q.data.failed_issuance.failed_jobs}
              to="/admin/reconciliation"
            />
          </Flex>
        </>
      )}
    </AdminPage>
  );
}
