// SPDX-License-Identifier: AGPL-3.0-or-later
/** Frame for the administration area: the standard page plus a section menu. */
import { Alert, Button, List, View } from "@instructure/ui";
import { useMutation } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { AppLink } from "../../components/AppLink";
import { ErrorAlert, Loading, NotForYou, Page, roleFlags, useMe } from "../../components/Page";

export const SECTIONS: { to: string; label: string; instOnly: boolean }[] = [
  { to: "/admin", label: "Overview", instOnly: false },
  { to: "/admin/institution", label: "Institution settings", instOnly: true },
  // Who and where: the order an institution is set up in.
  { to: "/admin/areas", label: "Faculties and departments", instOnly: false },
  { to: "/admin/courses", label: "Courses", instOnly: false },
  { to: "/admin/roles", label: "Staff roles", instOnly: false },
  { to: "/admin/issuers", label: "Issuers", instOnly: false },
  // The rules.
  { to: "/admin/policy", label: "Approval and awarding policy", instOnly: true },
  { to: "/admin/review", label: "Colleague review by area", instOnly: false },
  { to: "/admin/templates", label: "Badge templates", instOnly: false },
  { to: "/admin/credentials", label: "Issued badges and revocation", instOnly: false },
  { to: "/admin/reports", label: "Reports", instOnly: false },
  { to: "/admin/audit", label: "Audit log", instOnly: true },
  { to: "/admin/privacy", label: "Personal data and retention", instOnly: true },
  { to: "/admin/reconciliation", label: "Failed issuance", instOnly: true },
];

export function AdminPage({ title, children, instOnly = false }: { title: string; children: ReactNode; instOnly?: boolean }) {
  const me = useMe();
  const f = roleFlags(me.data);
  if (me.isPending) return <Loading what="your roles" />;
  // Someone with no administrator role at all sees no administration menu either.
  if (me.data && !f.isAdmin) return <NotForYou who="admins" />;
  const allowed = instOnly ? f.isInstAdmin : f.isAdmin;
  return (
    <Page title={title}>
      {/* Menu beside the page, not above it: on a laptop-width Canvas frame the menu used to wrap
          above the content and push the setup checklist out of sight. */}
      <div className="oc-admin-layout">
        <View as="nav" aria-label="Administration sections">
          <List isUnstyled margin="0">
            {SECTIONS.filter((s) => f.isInstAdmin || !s.instOnly).map((s) => (
              <List.Item key={s.to} margin="0 0 x-small">
                <AppLink to={s.to}>{s.label}</AppLink>
              </List.Item>
            ))}
          </List>
        </View>
        <View as="section" display="block">
          {allowed ? (
            children
          ) : (
            <Alert variant="warning">
              {instOnly ? "Only institution administrators can use this page." : "Only administrators can use this page."}
            </Alert>
          )}
        </View>
      </div>
    </Page>
  );
}

/** A button that downloads an authenticated file and reports failures inline. */
export function DownloadButton({ path, filename, children }: { path: string; filename: string; children: ReactNode }) {
  const { token } = useAuth();
  const dl = useMutation({ mutationFn: () => downloadFile(path, token, filename) });
  return (
    <>
      <Button margin="0 x-small x-small 0" onClick={() => dl.mutate()} interaction={dl.isPending ? "disabled" : "enabled"}>
        {children}
      </Button>
      {dl.isError && <ErrorAlert error={dl.error} />}
    </>
  );
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}
