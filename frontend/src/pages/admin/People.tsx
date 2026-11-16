// SPDX-License-Identifier: AGPL-3.0-or-later
/** Faculties and departments, which may issue, course placement, colleague review by area and
 * delegated staff roles (spec §2.3, §2.4, §10.3). One page each, so an administrator looking
 * for "who has which role" does not scroll past five other tables to find it. */
import { Alert, Button, Checkbox, Flex, Heading, SimpleSelect, Table, Text, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  apiDelete,
  apiFetch,
  apiSend,
  type AdminCourse,
  type AdminIssuer,
  type AreaReviewPolicy,
  type CanvasAccount,
  type OrgUnit,
  type Person,
  ROLE_LABELS,
  type StaffRole,
  type UnreviewedBadge,
} from "../../api";
import { useAuth } from "../../auth";
import { ConfirmButton } from "../../components/ConfirmButton";
import { ErrorAlert, Loading, roleFlags, useMe } from "../../components/Page";
import { AdminPage, fmtDate } from "./AdminPage";
import { TableScroll } from "../../components/TableScroll";

export function Areas() {
  return (
    <AdminPage title="Faculties and departments">
      <Text as="p">
        An area is a faculty, department, service or programme. Areas decide who may issue badges, which administrators look
        after which courses, and how badges are reviewed.
      </Text>
      <OrgUnits />
      <CanvasSubAccounts />
    </AdminPage>
  );
}

export function AreaReviewPage() {
  return (
    <AdminPage title="Colleague review by area">
      <AreaReview />
      <PublishedWithoutReview />
    </AdminPage>
  );
}

export function CoursePlacement() {
  return (
    <AdminPage title="Courses">
      <Courses />
    </AdminPage>
  );
}

export function StaffRoles() {
  return (
    <AdminPage title="Staff roles">
      <Roles />
    </AdminPage>
  );
}

function OrgUnits() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const f = roleFlags(useMe().data);
  const q = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const [v, setV] = useState({ name: "", kind: "department", parent_id: "" });
  const refresh = () => qc.invalidateQueries({ queryKey: ["org-units"] });
  const create = useMutation({
    mutationFn: () =>
      apiSend<OrgUnit>("/api/v1/admin/org-units", token, "POST", { ...v, parent_id: v.parent_id || null }),
    onSuccess: () => {
      setV({ ...v, name: "" });
      refresh();
    },
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<OrgUnit> }) =>
      apiSend<OrgUnit>(`/api/v1/admin/org-units/${id}`, token, "PATCH", body),
    onSuccess: refresh,
  });
  const units = q.data ?? [];
  const name = (id: string | null) => units.find((u) => u.id === id)?.name ?? "";
  return (
    <View as="section" display="block" margin="0 0 large">
      <Heading level="h2" margin="0 0 small">
        Your areas
      </Heading>
      {q.isPending && <Loading what="departments" />}
      {q.isError && <ErrorAlert error={q.error} />}
      <TableScroll>
      <Table caption="Faculties and departments">
        <Table.Head>
          <Table.Row>
            <Table.ColHeader id="u-name">Name</Table.ColHeader>
            <Table.ColHeader id="u-parent">Part of</Table.ColHeader>
            <Table.ColHeader id="u-issue">May issue badges</Table.ColHeader>
          </Table.Row>
        </Table.Head>
        <Table.Body>
          {units.map((u) => (
            <Table.Row key={u.id}>
              <Table.RowHeader>
                {u.name} ({u.kind}){u.status === "archived" ? " (archived)" : ""}
              </Table.RowHeader>
              <Table.Cell>{name(u.parent_id)}</Table.Cell>
              <Table.Cell>
                <Checkbox
                  label={`${u.name} may issue badges`}
                  checked={u.may_issue}
                  disabled={!f.isInstAdmin}
                  onChange={(e) => patch.mutate({ id: u.id, body: { may_issue: e.target.checked } })}
                />
                {u.may_issue && !u.effective_may_issue && <Text size="small">Blocked by a unit above it.</Text>}
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
      </TableScroll>
      {patch.isError && <ErrorAlert error={patch.error} />}
      <Flex gap="small" alignItems="end" wrap="wrap" margin="small 0 0">
        <TextInput maxLength={200} renderLabel="New area name" value={v.name} onChange={(_e, x) => setV({ ...v, name: x })} width="16rem" />
        <SimpleSelect renderLabel="Kind" value={v.kind} onChange={(_e, { value }) => setV({ ...v, kind: String(value) })} width="10rem">
          {["faculty", "department", "programme", "service", "other"].map((k) => (
            <SimpleSelect.Option key={k} id={`kind-${k}`} value={k}>
              {k}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
        <SimpleSelect
          renderLabel="Part of"
          value={v.parent_id}
          onChange={(_e, { value }) => setV({ ...v, parent_id: String(value) })}
          width="16rem"
        >
          <SimpleSelect.Option id="parent-none" value="">
            Top level
          </SimpleSelect.Option>
          {units
            .filter((u) => u.manageable)
            .map((u) => (
              <SimpleSelect.Option key={u.id} id={`parent-${u.id}`} value={u.id}>
                {u.name}
              </SimpleSelect.Option>
            ))}
        </SimpleSelect>
        <Button onClick={() => create.mutate()} interaction={v.name.trim().length >= 2 ? "enabled" : "disabled"}>
          Add area
        </Button>
      </Flex>
      {create.isError && <ErrorAlert error={create.error} />}
    </View>
  );
}

/** Tick Canvas sub-accounts to make them areas; their courses then join those areas. */
function CanvasSubAccounts() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const f = roleFlags(useMe().data);
  const q = useQuery({
    queryKey: ["canvas-accounts"],
    queryFn: () => apiFetch<CanvasAccount[]>("/api/v1/admin/canvas-accounts", token),
    enabled: f.isInstAdmin,
  });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const [picked, setPicked] = useState<string[]>([]);
  const [kind, setKind] = useState("");
  /** "" creates a new area per ticked sub-account; otherwise link to this existing area. */
  const [target, setTarget] = useState("");
  const [done, setDone] = useState("");
  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["canvas-accounts"] });
    qc.invalidateQueries({ queryKey: ["org-units"] });
    qc.invalidateQueries({ queryKey: ["admin-courses"] });
  };
  const read = useMutation({
    mutationFn: () => apiSend<{ accounts: number }>("/api/v1/admin/canvas-accounts/refresh", token, "POST"),
    onSuccess: (r) => {
      setDone(`Read ${r.accounts} accounts from Canvas.`);
      refreshAll();
    },
  });
  const link = useMutation({
    mutationFn: () =>
      apiSend<{ linked: number; courses_placed: number; courses_queued?: number }>("/api/v1/admin/canvas-accounts/link", token, "POST", {
        items: picked.map((id) => (target ? { id, org_unit_id: target } : { id, kind: kind || null })),
      }),
    onSuccess: (r) => {
      setPicked([]);
      const queued = r.courses_queued ?? 0;
      setDone(
        `Linked ${r.linked} sub-account${r.linked === 1 ? "" : "s"}.` +
          (r.courses_placed
            ? ` ${r.courses_placed} course${r.courses_placed === 1 ? "" : "s"} not yet in an area joined ${r.linked === 1 ? "it" : "them"}.`
            : queued
              ? ""
              : " Its courses were already in an area, so none needed moving; new courses join it when first opened.") +
          (queued
            ? ` ${queued} more course${queued === 1 ? " is" : "s are"} being checked against Canvas in the background and will join within a few minutes.`
            : ""),
      );
      refreshAll();
    },
  });
  const unlink = useMutation({
    mutationFn: (a: CanvasAccount) => apiDelete(`/api/v1/admin/canvas-accounts/${a.id}/link`, token),
    onSuccess: (_r, a) => {
      setDone(`Unlinked ${a.name}. Courses already in ${a.org_unit_name ?? "its area"} stay there.`);
      refreshAll();
    },
  });
  if (!f.isInstAdmin) return null;
  const rows = q.data ?? [];
  const toggle = (id: string, on: boolean) => setPicked(on ? [...picked, id] : picked.filter((x) => x !== id));
  // Linking to "a new area" when an area of the same name exists would make a second one.
  const existing = new Set((units.data ?? []).filter((u) => u.status === "active").map((u) => u.name.trim().toLowerCase()));
  const clashes = target
    ? []
    : rows.filter((a) => picked.includes(a.id) && existing.has(a.name.trim().toLowerCase())).map((a) => a.name);
  return (
    <View as="section" display="block" margin="0 0 large">
      <Heading level="h2" margin="0 0 small">
        Canvas sub-accounts
      </Heading>
      <Text as="p">
        Tick the Canvas sub-accounts that should be areas, such as faculties, departments or the Library. Each one
        becomes an area named after it, nested as in Canvas, and its courses join that area when they are first opened.
        Sub-accounts you leave unticked, such as sandboxes or terms, are ignored. A course you have already placed is
        never moved, and unlinking keeps the area and its courses.
      </Text>
      <Flex gap="small" alignItems="end" wrap="wrap" margin="0 0 small">
        <Button onClick={() => read.mutate()} interaction={read.isPending ? "disabled" : "enabled"}>
          Read sub-accounts from Canvas
        </Button>
      </Flex>
      {done && (
        <Text as="p" role="status">
          {done}
        </Text>
      )}
      {read.isError && <ErrorAlert error={read.error} />}
      {q.isPending && <Loading what="sub-accounts" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {rows.length > 0 && (
        <>
          <TableScroll>
            <Table caption="Canvas sub-accounts">
              <Table.Head>
                <Table.Row>
                  <Table.ColHeader id="ca-name">Sub-account</Table.ColHeader>
                  <Table.ColHeader id="ca-area">Area</Table.ColHeader>
                  <Table.ColHeader id="ca-courses">Courses opened</Table.ColHeader>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {rows.map((a) => (
                  <Table.Row key={a.id}>
                    <Table.RowHeader>
                      <div style={{ paddingInlineStart: `${a.depth * 1.5}rem` }}>
                        {a.org_unit_id ? (
                          <Text>{a.name}</Text>
                        ) : a.depth === 0 ? (
                          <Text>
                            {a.name} <Text color="secondary">(whole Canvas)</Text>
                          </Text>
                        ) : (
                          <Checkbox
                            label={a.name}
                            checked={picked.includes(a.id)}
                            onChange={(e) => toggle(a.id, e.target.checked)}
                          />
                        )}
                      </div>
                    </Table.RowHeader>
                    <Table.Cell>
                      {a.org_unit_name ? (
                        <Flex gap="small" alignItems="center" wrap="wrap">
                          <Text>{a.org_unit_name}</Text>
                          <ConfirmButton
                            size="small"
                            label={`Unlink ${a.name}`}
                            consequence={`Unlink ${a.name} from ${a.org_unit_name}? New courses in this Canvas sub-account will no longer be placed in that area. The area and the courses already in it stay as they are.`}
                            confirmLabel="Unlink it"
                            cancelLabel="Keep the link"
                            busy={unlink.isPending}
                            onConfirm={() => unlink.mutate(a)}
                          />
                        </Flex>
                      ) : (
                        <Text color="secondary">Not linked</Text>
                      )}
                    </Table.Cell>
                    <Table.Cell>{a.courses}</Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </TableScroll>
          {unlink.isError && <ErrorAlert error={unlink.error} />}
          <Flex gap="small" alignItems="end" wrap="wrap" margin="small 0 0">
            <SimpleSelect
              renderLabel="Link to"
              value={target}
              onChange={(_e, { value }) => setTarget(String(value))}
              width="20rem"
            >
              <SimpleSelect.Option id="ca-target-new" value="">
                A new area named after each sub-account
              </SimpleSelect.Option>
              {(units.data ?? [])
                .filter((u) => u.status === "active")
                .map((u) => (
                  <SimpleSelect.Option key={u.id} id={`ca-target-${u.id}`} value={u.id}>
                    {`Existing area: ${u.name}`}
                  </SimpleSelect.Option>
                ))}
            </SimpleSelect>
            <SimpleSelect
              renderLabel="Kind for new areas"
              value={kind}
              onChange={(_e, { value }) => setKind(String(value))}
              width="20rem"
              interaction={target ? "disabled" : "enabled"}
            >
              <SimpleSelect.Option id="ca-kind-auto" value="">
                Automatic: faculty at the top, department below
              </SimpleSelect.Option>
              {["faculty", "department", "programme", "service", "other"].map((k) => (
                <SimpleSelect.Option key={k} id={`ca-kind-${k}`} value={k}>
                  {k}
                </SimpleSelect.Option>
              ))}
            </SimpleSelect>
            <Button
              color="primary"
              onClick={() => link.mutate()}
              interaction={picked.length && !link.isPending ? "enabled" : "disabled"}
            >
              Link selected ({picked.length})
            </Button>
          </Flex>
          {clashes.length > 0 && (
            <Alert variant="warning" margin="small 0">
              An area called {clashes.join(", ")} already exists. To use it, choose &ldquo;Existing area:{" "}
              {clashes[0]}&rdquo; under Link to; otherwise a second area with the same name is created.
            </Alert>
          )}
          {link.isError && <ErrorAlert error={link.error} />}
          <Text as="p" size="small">
            Last read from Canvas {fmtDate(rows[0].refreshed_at)}.
          </Text>
        </>
      )}
    </View>
  );
}

const MODE_LABELS: Record<string, string> = {
  required: "Required",
  author_decides: "Author decides",
  not_required: "Not required",
};
const YES_NO: Record<string, [string, string]> = {
  self_approval_allowed: ["Allowed", "Not allowed"],
  manual_awards_require_second_approval: ["Required", "Not required"],
};

/** Colleague review set per faculty, department or service; a unit inherits until it sets its own. */
function AreaReview() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const patch = useMutation({
    mutationFn: ({ id, review_policy }: { id: string; review_policy: Record<string, unknown> }) =>
      apiSend<OrgUnit>(`/api/v1/admin/org-units/${id}`, token, "PATCH", { review_policy }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-units"] }),
  });
  const units = (q.data ?? []).filter((u) => u.manageable && u.status === "active");
  const inherited = (u: OrgUnit, key: keyof AreaReviewPolicy) => {
    const v = u.effective_review[key];
    const text = key === "definition_review" ? MODE_LABELS[String(v)] : YES_NO[key][v ? 0 : 1];
    return `Inherit (${text})`;
  };
  const valueOf = (u: OrgUnit, key: keyof AreaReviewPolicy) => {
    const v = u.review_policy[key];
    return v === undefined ? "" : String(v);
  };
  const change = (u: OrgUnit, key: keyof AreaReviewPolicy, raw: string) => {
    const value = raw === "" ? null : key === "definition_review" ? raw : raw === "true";
    patch.mutate({ id: u.id, review_policy: { [key]: value } });
  };
  if (!units.length) return null;
  return (
    <View as="section" display="block" margin="0 0 large">
      <Heading level="h2" margin="0 0 small">
        Review rules for each area
      </Heading>
      <Text as="p">
        Each faculty, department or service can set its own review rules, for example switching review off for
        volunteering badges. A unit inherits from the unit above it, then the institution, until it sets its own.
      </Text>
      {patch.isError && <ErrorAlert error={patch.error} />}
      <Text as="p" role="status" size="small">
        {patch.isPending
          ? "Saving…"
          : patch.isSuccess
            ? `Saved review settings for ${patch.data.name}. Badges already published stay published.`
            : ""}
      </Text>
      {units.map((u) => (
        <Flex key={u.id} gap="small" alignItems="end" wrap="wrap" margin="small 0">
          <Text weight="bold">{u.name}</Text>
          <SimpleSelect
            renderLabel={`Badge review in ${u.name}`}
            value={valueOf(u, "definition_review")}
            onChange={(_e, { value }) => change(u, "definition_review", String(value))}
            width="14rem"
          >
            <SimpleSelect.Option id={`${u.id}-rv-inherit`} value="">
              {inherited(u, "definition_review")}
            </SimpleSelect.Option>
            {Object.entries(MODE_LABELS).map(([k, label]) => (
              <SimpleSelect.Option key={k} id={`${u.id}-rv-${k}`} value={k}>
                {label}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
          {(["self_approval_allowed", "manual_awards_require_second_approval"] as const).map((key) => (
            <SimpleSelect
              key={key}
              renderLabel={
                key === "self_approval_allowed"
                  ? `Authors approving their own badges in ${u.name}`
                  : `Second approval of manual awards in ${u.name}`
              }
              value={valueOf(u, key)}
              onChange={(_e, { value }) => change(u, key, String(value))}
              width="14rem"
            >
              <SimpleSelect.Option id={`${u.id}-${key}-inherit`} value="">
                {inherited(u, key)}
              </SimpleSelect.Option>
              <SimpleSelect.Option id={`${u.id}-${key}-true`} value="true">
                {YES_NO[key][0]}
              </SimpleSelect.Option>
              <SimpleSelect.Option id={`${u.id}-${key}-false`} value="false">
                {YES_NO[key][1]}
              </SimpleSelect.Option>
            </SimpleSelect>
          ))}
        </Flex>
      ))}
    </View>
  );
}

/** Live badges nobody else reviewed, so admins can check them after making review stricter. */
function PublishedWithoutReview() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["published-without-review"],
    queryFn: () => apiFetch<UnreviewedBadge[]>("/api/v1/admin/review/published-without-review", token),
  });
  if (q.isError) return <ErrorAlert error={q.error} />;
  if (!q.data) return null;
  if (!q.data.length)
    return (
      <View as="section" display="block" margin="0 0 large">
        <Heading level="h2" margin="0 0 small">
          Badges published without review
        </Heading>
        <Text as="p">Every live badge in your areas was reviewed by a colleague.</Text>
      </View>
    );
  return (
    <View as="section" display="block" margin="0 0 large">
      <Heading level="h2" margin="0 0 small">
        Badges published without review
      </Heading>
      <TableScroll>
        <Table caption="Badges published without review">
          <Table.Head>
            <Table.Row>
              <Table.ColHeader id="nr-title">Badge</Table.ColHeader>
              <Table.ColHeader id="nr-area">Area</Table.ColHeader>
              <Table.ColHeader id="nr-author">Author</Table.ColHeader>
              <Table.ColHeader id="nr-when">Published</Table.ColHeader>
              <Table.ColHeader id="nr-now">Review now</Table.ColHeader>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {q.data.map((b) => (
              <Table.Row key={b.id}>
                <Table.RowHeader>
                  {b.title} (version {b.version_no})
                </Table.RowHeader>
                <Table.Cell>{b.area ?? "Institution"}</Table.Cell>
                <Table.Cell>{b.author ?? ""}</Table.Cell>
                <Table.Cell>{fmtDate(b.approved_at)}</Table.Cell>
                <Table.Cell>{MODE_LABELS[b.review_now]}</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
      </TableScroll>
    </View>
  );
}

function Courses() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const courses = useQuery({ queryKey: ["admin-courses"], queryFn: () => apiFetch<AdminCourse[]>("/api/v1/admin/courses", token) });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const move = useMutation({
    mutationFn: ({ id, org_unit_id }: { id: string; org_unit_id: string | null }) =>
      apiSend(`/api/v1/admin/courses/${id}/org-unit`, token, "PUT", { org_unit_id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-courses"] }),
  });
  const teams = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiSend(`/api/v1/courses/${id}/badge-teams`, token, "PUT", { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-courses"] }),
  });
  return (
    <View as="section" display="block" margin="0 0 large">
      <Heading level="h2" margin="0 0 small">
        Where each course belongs
      </Heading>
      {courses.isError && <ErrorAlert error={courses.error} />}
      {move.isError && <ErrorAlert error={move.error} />}
      {teams.isError && <ErrorAlert error={teams.error} />}
      <Text as="p">
        Badge teams: in a course many staff share, each badge is edited and awarded only by its owner, its team and
        administrators. Lecturers can switch them on from the course; only administrators can switch them off.
      </Text>
      {(courses.data ?? []).map((c) => (
        <Flex key={c.id} gap="small" alignItems="end" wrap="wrap" margin="small 0">
        <SimpleSelect
          renderLabel={`${c.title}${c.course_code ? ` (${c.course_code})` : ""} belongs to`}
          value={c.org_unit_id ?? ""}
          onChange={(_e, { value }) => move.mutate({ id: c.id, org_unit_id: String(value) || null })}
          width="24rem"
        >
          <SimpleSelect.Option id={`${c.id}-none`} value="">
            No department
          </SimpleSelect.Option>
          {(units.data ?? []).map((u) => (
            <SimpleSelect.Option key={u.id} id={`${c.id}-${u.id}`} value={u.id}>
              {u.name}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
        <ConfirmButton
          label={c.badge_teams ? `Switch badge teams off in ${c.title}` : `Switch badge teams on in ${c.title}`}
          consequence={
            c.badge_teams
              ? `Switch badge teams off in ${c.title}? Every member of staff in the course will be able to edit and award every badge again.`
              : `Switch badge teams on in ${c.title}? Colleagues will lose the ability to edit or award badges they do not own until the owner adds them to the badge's team.`
          }
          confirmLabel={c.badge_teams ? "Switch off" : "Switch on"}
          cancelLabel="Leave it as it is"
          busy={teams.isPending}
          onConfirm={() => teams.mutate({ id: c.id, enabled: !c.badge_teams })}
        />
        <Text size="small">Badge teams: {c.badge_teams ? "on" : "off"}</Text>
        </Flex>
      ))}
    </View>
  );
}

const SCOPE_FOR: Record<string, string> = {
  inst_admin: "institution",
  dept_admin: "org_unit",
  reviewer: "org_unit",
  issuer_manager: "issuer",
  lecturer: "course",
  course_admin: "course",
};

function Roles() {
  const { token } = useAuth();
  const qc = useQueryClient();
  const f = roleFlags(useMe().data);
  const roles = useQuery({ queryKey: ["memberships"], queryFn: () => apiFetch<StaffRole[]>("/api/v1/admin/memberships", token) });
  const units = useQuery({ queryKey: ["org-units"], queryFn: () => apiFetch<OrgUnit[]>("/api/v1/admin/org-units", token) });
  const courses = useQuery({ queryKey: ["admin-courses"], queryFn: () => apiFetch<AdminCourse[]>("/api/v1/admin/courses", token) });
  const issuers = useQuery({ queryKey: ["admin-issuers"], queryFn: () => apiFetch<AdminIssuer[]>("/api/v1/admin/issuers", token) });
  const [search, setSearch] = useState("");
  const people = useQuery({
    queryKey: ["people", search],
    queryFn: () => apiFetch<Person[]>(`/api/v1/admin/people?q=${encodeURIComponent(search)}`, token),
    enabled: search.trim().length >= 2,
  });
  const [g, setG] = useState({ user_id: "", role: "lecturer", scope_id: "" });
  const refresh = () => qc.invalidateQueries({ queryKey: ["memberships"] });
  const grant = useMutation({
    mutationFn: () =>
      apiSend<StaffRole>("/api/v1/admin/memberships", token, "POST", {
        user_id: g.user_id,
        role: g.role,
        scope_type: SCOPE_FOR[g.role],
        scope_id: SCOPE_FOR[g.role] === "institution" ? null : g.scope_id,
      }),
    onSuccess: refresh,
  });
  const revoke = useMutation({ mutationFn: (id: string) => apiDelete(`/api/v1/admin/memberships/${id}`, token), onSuccess: refresh });
  const scopeOptions =
    SCOPE_FOR[g.role] === "org_unit"
      ? (units.data ?? []).filter((u) => u.manageable).map((u) => ({ id: u.id, label: u.name }))
      : SCOPE_FOR[g.role] === "course"
        ? (courses.data ?? []).map((c) => ({ id: c.id, label: c.title }))
        : SCOPE_FOR[g.role] === "issuer"
          ? (issuers.data ?? []).map((i) => ({ id: i.id, label: i.name }))
          : [];
  const grantable = f.isInstAdmin ? Object.keys(SCOPE_FOR) : Object.keys(SCOPE_FOR).filter((r) => r !== "inst_admin");
  return (
    <View as="section" display="block">
      <Heading level="h2" margin="0 0 small">
        Who has which role
      </Heading>
      {roles.isError && <ErrorAlert error={roles.error} />}
      <TableScroll>
      <Table caption="Staff roles">
        <Table.Head>
          <Table.Row>
            <Table.ColHeader id="r-person">Person</Table.ColHeader>
            <Table.ColHeader id="r-role">Role</Table.ColHeader>
            <Table.ColHeader id="r-scope">Where</Table.ColHeader>
            <Table.ColHeader id="r-src">Source</Table.ColHeader>
            <Table.ColHeader id="r-act">Action</Table.ColHeader>
          </Table.Row>
        </Table.Head>
        <Table.Body>
          {(roles.data ?? []).map((r) => (
            <Table.Row key={r.id}>
              <Table.RowHeader>{r.user_name ?? "(no name)"}</Table.RowHeader>
              <Table.Cell>{ROLE_LABELS[r.role] ?? r.role}</Table.Cell>
              <Table.Cell>{r.scope_name}</Table.Cell>
              <Table.Cell>
                {r.source === "lti" ? "Canvas" : "Granted here"}
                {r.expires_at ? `, until ${fmtDate(r.expires_at)}` : ""}
              </Table.Cell>
              <Table.Cell>
                <ConfirmButton
                  size="small"
                  label={`Remove ${ROLE_LABELS[r.role] ?? r.role} from ${r.user_name ?? "this person"}`}
                  consequence={`Remove the ${ROLE_LABELS[r.role] ?? r.role} role from ${r.user_name ?? "this person"}${r.scope_name ? ` for ${r.scope_name}` : ""}? They lose what the role lets them do straight away.${r.source === "lti" ? " Canvas gives the role back the next time they open the tool from a course where they still hold it." : " You can grant it again below."}`}
                  confirmLabel="Remove the role"
                  cancelLabel="Keep the role"
                  busy={revoke.isPending}
                  onConfirm={() => revoke.mutate(r.id)}
                />
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
      </TableScroll>
      {revoke.isError && <ErrorAlert error={revoke.error} />}
      <Heading level="h3" margin="medium 0 small">
        Grant a role
      </Heading>
      <Flex gap="small" alignItems="end" wrap="wrap">
        <TextInput renderLabel="Find a person by name" value={search} onChange={(_e, v) => setSearch(v)} width="16rem" />
        <SimpleSelect renderLabel="Person" value={g.user_id} onChange={(_e, { value }) => setG({ ...g, user_id: String(value) })} width="16rem">
          <SimpleSelect.Option id="p-none" value="">
            {search.trim().length >= 2 ? "Choose" : "Type at least two letters"}
          </SimpleSelect.Option>
          {(people.data ?? []).map((p) => (
            <SimpleSelect.Option key={p.id} id={`p-${p.id}`} value={p.id}>
              {p.display_name ?? p.id}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
        <SimpleSelect renderLabel="Role" value={g.role} onChange={(_e, { value }) => setG({ ...g, role: String(value), scope_id: "" })} width="16rem">
          {grantable.map((r) => (
            <SimpleSelect.Option key={r} id={`role-${r}`} value={r}>
              {ROLE_LABELS[r]}
            </SimpleSelect.Option>
          ))}
        </SimpleSelect>
        {SCOPE_FOR[g.role] !== "institution" && (
          <SimpleSelect renderLabel="Where" value={g.scope_id} onChange={(_e, { value }) => setG({ ...g, scope_id: String(value) })} width="16rem">
            <SimpleSelect.Option id="s-none" value="">
              Choose
            </SimpleSelect.Option>
            {scopeOptions.map((o) => (
              <SimpleSelect.Option key={o.id} id={`s-${o.id}`} value={o.id}>
                {o.label}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
        )}
        <Button
          color="primary"
          interaction={g.user_id && (SCOPE_FOR[g.role] === "institution" || g.scope_id) ? "enabled" : "disabled"}
          onClick={() => grant.mutate()}
        >
          Grant role
        </Button>
      </Flex>
      {grant.isError && <ErrorAlert error={grant.error} />}
    </View>
  );
}
