// SPDX-License-Identifier: AGPL-3.0-or-later
/** Administration overview: what is left to set up, and what needs attention now. */
import { Alert, Flex, Heading, List, Pill, Text, ToggleDetails, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";

import { apiFetch, type ReportSummary, type SetupChecklist, type SetupStep } from "../../api";
import { useAuth } from "../../auth";
import { AppLink } from "../../components/AppLink";
import { ErrorAlert, Loading, roleFlags, useMe } from "../../components/Page";
import { AdminPage, SECTIONS } from "./AdminPage";

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

function Step({ step, isNext }: { step: SetupStep; isNext: boolean }) {
  const page = SECTIONS.find((s) => s.to === step.to)?.label;
  return (
    <List.Item margin="0 0 small">
      <View
        as="div"
        display="block"
        padding="small"
        borderWidth="small"
        borderRadius="medium"
        background={isNext ? "secondary" : "primary"}
        aria-current={isNext ? "step" : undefined}
      >
        <Flex gap="small" alignItems="center" wrap="wrap">
          {/* The state is written out, never shown by colour alone. */}
          <Pill color={step.done ? "success" : isNext ? "info" : "primary"}>{step.done ? "Done" : isNext ? "Do this next" : "To do"}</Pill>
          <Text weight="bold">{step.title}</Text>
        </Flex>
        <Text as="p">{step.detail}</Text>
        {!step.done && step.to && page && <AppLink to={step.to}>Open {page}</AppLink>}
      </View>
    </List.Item>
  );
}

/** What has to be true before a lecturer can create a badge that the public can check. */
function Setup() {
  const { token } = useAuth();
  const q = useQuery({ queryKey: ["admin-setup"], queryFn: () => apiFetch<SetupChecklist>("/api/v1/admin/setup", token) });
  if (q.isError) return <ErrorAlert error={q.error} />;
  if (!q.data) return <Loading what="the setup checklist" />;
  const steps = (
    <List as="ol" isUnstyled margin="small 0 0">
      {q.data.steps.map((s) => (
        <Step key={s.key} step={s} isNext={s.key === q.data.next} />
      ))}
    </List>
  );
  return (
    <View as="section" aria-labelledby="setup-h" display="block" margin="0 0 large">
      <Heading level="h2" id="setup-h" margin="0 0 small">
        Getting set up
      </Heading>
      {q.data.complete ? (
        <>
          <Alert variant="success" margin="0 0 small">
            Setup is complete. Staff can create badges in the departments and courses an issuer is delegated to.
          </Alert>
          <ToggleDetails summary={`Show the setup checklist (all ${q.data.total} done)`}>{steps}</ToggleDetails>
        </>
      ) : (
        <>
          <Text as="p">
            {q.data.done} of {q.data.total} done. Until every step is done, lecturers cannot create badges that the public can check.
          </Text>
          {steps}
        </>
      )}
    </View>
  );
}

export function AdminHome() {
  const { token } = useAuth();
  const f = roleFlags(useMe().data);
  const q = useQuery({
    queryKey: ["report-summary", "", ""],
    queryFn: () => apiFetch<ReportSummary>("/api/v1/admin/reports/summary", token),
  });
  return (
    <AdminPage title="Administration">
      {f.isInstAdmin && <Setup />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.isPending && <Loading what="overview" />}
      {q.data && (
        <>
          <Heading level="h2" margin="0 0 small">
            Badges
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
