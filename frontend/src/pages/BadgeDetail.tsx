// SPDX-License-Identifier: AGPL-3.0-or-later
/** One badge: its draft or live version, lifecycle actions, review and a non-issued preview. */
import {
  Alert,
  Button,
  Checkbox,
  RadioInput,
  RadioInputGroup,
  Flex,
  Heading,
  Img,
  List,
  Pill,
  SimpleSelect,
  Tabs,
  Text,
  View,
} from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  apiFetch,
  apiSend,
  POLICY_LABELS,
  type BadgeTeam,
  type ReviewRequirement,
  STATE_LABELS,
  type Catalogue,
  type Definition,
  type Issue,
  type Preview,
} from "../api";
import { useAuth } from "../auth";
import { LimitedTextArea } from "../components/Fields";
import { AppLink } from "../components/AppLink";
import { ConfirmButton } from "../components/ConfirmButton";
import { ErrorAlert, Loading, Page } from "../components/Page";

export const CHECKLIST_LABELS: Record<string, string> = {
  clarity: "Title and descriptions are clear to someone outside the course",
  level: "The level and size of the achievement are stated honestly",
  evidence: "The requirements genuinely evidence the learning outcomes",
  alignment: "Category and how it is demonstrated match what is assessed",
  accessibility:
    "Artwork has meaningful alternative text and readable contrast",
  consistency: "Consistent with similar badges in the institution",
  terminology:
    "No wording implies academic credit or a formal qualification unless approved",
};

const STATE_COLOR: Record<
  string,
  "info" | "success" | "warning" | "primary" | "danger"
> = {
  draft: "primary",
  in_review: "warning",
  approved: "info",
  published: "success",
  archived: "danger",
};

function Readiness({ issues }: { issues: Issue[] }) {
  if (!issues.length)
    return <Alert variant="success">Ready to submit for review.</Alert>;
  const errors = issues.filter((i) => i.severity === "error");
  return (
    <Alert variant={errors.length ? "warning" : "info"}>
      <Text weight="bold">
        {errors.length
          ? "Before this can be submitted:"
          : "Things a reviewer will look at:"}
      </Text>
      <List>
        {issues.map((i) => (
          <List.Item key={`${i.field}-${i.code}`}>{i.message}</List.Item>
        ))}
      </List>
    </Alert>
  );
}

function PreviewPanel({ id }: { id: string }) {
  const { token } = useAuth();
  const p = useQuery({
    queryKey: ["preview", id],
    queryFn: () =>
      apiFetch<Preview>(`/api/v1/achievements/${id}/preview`, token),
  });
  if (p.isPending) return <Loading what="preview" />;
  if (p.isError) return <ErrorAlert error={p.error} />;
  const a = p.data.achievement;
  return (
    <View as="section" aria-label="Preview" display="block">
      <Alert variant="warning" margin="0 0 medium">
        <Text weight="bold">{p.data.notice}</Text>. This is how the badge would
        look. It is not a real badge and cannot be verified.
      </Alert>
      <Flex gap="medium" alignItems="start">
        {p.data.artwork.data_url ? (
          <Img
            src={p.data.artwork.data_url}
            alt={p.data.artwork.alt_text ?? ""}
            width="10rem"
            height="10rem"
            constrain="contain"
          />
        ) : (
          <Text>No artwork yet</Text>
        )}
        <Flex.Item shouldShrink>
          <Heading level="h2">{a.title || "(untitled)"}</Heading>
          <Text as="p">{a.description}</Text>
          <Text as="p">
            {a.category} · {a.demonstration} · issued by {p.data.issuer.name}
          </Text>
          <Heading level="h3">Learning outcomes</Heading>
          <List>
            {a.learning_outcomes.map((o) => (
              <List.Item key={o}>{o}</List.Item>
            ))}
          </List>
          <Heading level="h3">Criteria</Heading>
          <Text as="p">{a.criteria}</Text>
          {a.requirements.length > 0 && (
            <>
              <Heading level="h3">Requirements</Heading>
              <List>
                {a.requirements.map((r) => (
                  <List.Item key={r}>{r}</List.Item>
                ))}
              </List>
            </>
          )}
        </Flex.Item>
      </Flex>
    </View>
  );
}

function ReviewPanel({
  d,
  checklistKeys,
}: {
  d: Definition;
  checklistKeys: string[];
}) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [comment, setComment] = useState("");
  const [credit, setCredit] = useState(false);
  const creditWarning = d.readiness.some((i) => i.code === "CREDIT_TERMS");
  const act = useMutation({
    mutationFn: (kind: "approve" | "reject") =>
      kind === "approve"
        ? apiSend<Definition>(
            `/api/v1/achievements/${d.id}/approve`,
            token,
            "POST",
            {
              checklist: checks,
              comment: comment || null,
              credit_claim_approved: creditWarning ? credit : null,
            },
          )
        : apiSend<Definition>(
            `/api/v1/achievements/${d.id}/reject`,
            token,
            "POST",
            { comment, checklist: checks },
          ),
    onSuccess: (nd) => {
      qc.setQueryData(["achievement", d.id], nd);
      qc.invalidateQueries({ queryKey: ["achievements"] });
    },
  });
  // An approved badge that is not yet published can still be sent back (the server allows it);
  // there is nothing left to approve, so only the return half of the panel is shown.
  const approved = d.state === "approved";
  const all = checklistKeys.every((k) => checks[k]);
  return (
    <View
      as="section"
      aria-labelledby="review-h"
      padding="medium"
      borderWidth="small"
      borderRadius="medium"
      display="block"
      margin="medium 0"
    >
      <Heading level="h2" id="review-h">
        Review
      </Heading>
      <Text as="p">
        {approved
          ? "This badge is approved but not published yet. To send it back to the author, explain what needs to change."
          : "Confirm each point before approving. To send it back, explain what needs to change."}
      </Text>
      {!approved && checklistKeys.map((k) => (
        <Checkbox
          key={k}
          label={CHECKLIST_LABELS[k] ?? k}
          checked={!!checks[k]}
          onChange={(e) => setChecks((c) => ({ ...c, [k]: e.target.checked }))}
        />
      ))}
      {!approved && creditWarning && (
        <Checkbox
          label="I approve the wording that refers to credit or a qualification"
          checked={credit}
          onChange={(e) => setCredit(e.target.checked)}
        />
      )}
      <LimitedTextArea
        maxLength={4000}
        label="Comment to the author"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {act.isError && <ErrorAlert error={act.error} />}
      <Flex gap="small" margin="small 0 0">
        {!approved && (
          <Button
            color="primary"
            interaction={all && !act.isPending ? "enabled" : "disabled"}
            onClick={() => act.mutate("approve")}
          >
            Approve
          </Button>
        )}
        <Button
          color="secondary"
          interaction={
            comment.trim().length >= 5 && !act.isPending
              ? "enabled"
              : "disabled"
          }
          onClick={() => act.mutate("reject")}
        >
          Return to author
        </Button>
      </Flex>
      {((!approved && !all) || comment.trim().length < 5) && (
        <Text as="p" size="small">
          {!approved && !all ? "Tick every point above to approve. " : ""}
          {comment.trim().length < 5
            ? "Write a comment to the author to return it."
            : ""}
        </Text>
      )}
    </View>
  );
}

const FORCED_REASON: Record<string, string> = {
  assessed:
    "Badges that claim assessed proficiency always need a colleague's review.",
  credit:
    "The wording refers to credit or a qualification, so a colleague must review it.",
};

/** How this badge will be reviewed, and the author's choice where their area lets them decide. */
function ReviewChoice({
  review,
  value,
  onChange,
}: {
  review: ReviewRequirement;
  value: "colleague" | "skip";
  onChange: (v: "colleague" | "skip") => void;
}) {
  if (review.mode === "author_decides")
    return (
      <View as="div" margin="0 0 medium" maxWidth="40rem">
        <RadioInputGroup
          name="review-choice"
          description="Colleague review"
          value={value}
          onChange={(_e, v) => onChange(v as "colleague" | "skip")}
        >
          <RadioInput
            value="colleague"
            label="Ask a colleague to review it first (recommended)"
          />
          <RadioInput
            value="skip"
            label="Publish without review. Administrators can see badges published this way."
          />
        </RadioInputGroup>
      </View>
    );
  const text =
    review.mode === "not_required"
      ? "Your area does not require a colleague's review for this badge."
      : review.forced_by
        ? FORCED_REASON[review.forced_by]
        : "Your area requires a colleague to review this badge before it can be published.";
  return (
    <Text as="p" size="small">
      {text}
    </Text>
  );
}

const TEAM_ROLE: Record<string, string> = {
  owner: "Owner",
  editor: "Can edit and award",
  awarder: "Can award",
};

/** Who works on this badge when its course has badge teams switched on. */
const NO_NAME = "A colleague without a name in Canvas";

function TeamPanel({ id }: { id: string }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [who, setWho] = useState("");
  const [role, setRole] = useState<"editor" | "awarder">("awarder");
  const [removing, setRemoving] = useState<string | null>(null);
  const [newOwner, setNewOwner] = useState("");
  const [done, setDone] = useState("");
  const team = useQuery({
    queryKey: ["team", id],
    queryFn: () =>
      apiFetch<BadgeTeam>(`/api/v1/achievements/${id}/team`, token),
  });
  const change = useMutation({
    mutationFn: ({
      user,
      r,
    }: {
      user: string;
      r: "editor" | "awarder" | null;
      name: string;
    }) =>
      r
        ? apiSend<BadgeTeam>(
            `/api/v1/achievements/${id}/team/${user}`,
            token,
            "PUT",
            { role: r },
          )
        : apiSend<BadgeTeam>(
            `/api/v1/achievements/${id}/team/${user}`,
            token,
            "DELETE",
          ),
    onSuccess: (t, v) => {
      qc.setQueryData(["team", id], t);
      setWho("");
      setRemoving(null);
      setDone(
        v.r
          ? `Added ${v.name} to the team.`
          : `Removed ${v.name} from the team.`,
      );
    },
  });
  const transfer = useMutation({
    mutationFn: ({ user }: { user: string; name: string }) =>
      apiSend<BadgeTeam>(`/api/v1/achievements/${id}/owner`, token, "PUT", {
        user_id: user,
      }),
    onSuccess: (t, v) => {
      qc.setQueryData(["team", id], t);
      qc.invalidateQueries({ queryKey: ["achievement", id] });
      setNewOwner("");
      setDone(`${v.name} now owns this badge.`);
    },
  });
  if (team.isPending) return <Loading what="team" />;
  if (team.isError) return <ErrorAlert error={team.error} />;
  const t = team.data;
  const nameOf = (n: string | null) => n ?? NO_NAME;
  // Anyone on staff who is not the owner can take the badge over.
  const others = [
    ...t.members.filter((mb) => mb.role !== "owner"),
    ...t.candidates,
  ];
  return (
    <View as="div" display="block" margin="small 0">
      <Text as="p">
        {t.enabled
          ? "Badge teams are on for this course: only these people (and administrators) can edit or award this badge."
          : "Badge teams are off for this course, so all course staff can edit and award this badge. You can still name a team now; it applies if badge teams are switched on."}
      </Text>
      <List>
        {t.members.map((mb) => (
          <List.Item key={mb.user_id}>
            {nameOf(mb.name)}: {TEAM_ROLE[mb.role]}
            {t.can_manage && mb.role !== "owner" && removing !== mb.user_id && (
              <Button
                size="small"
                margin="0 0 0 small"
                onClick={() => setRemoving(mb.user_id)}
              >
                Remove {mb.name ?? "this colleague"} from the team
              </Button>
            )}
            {removing === mb.user_id && (
              <>
                <Text>
                  {" "}
                  Remove them? They will no longer be able to work on this
                  badge.
                </Text>
                <Button
                  size="small"
                  color="danger"
                  margin="0 0 0 small"
                  interaction={change.isPending ? "disabled" : "enabled"}
                  onClick={() =>
                    change.mutate({
                      user: mb.user_id,
                      r: null,
                      name: nameOf(mb.name),
                    })
                  }
                >
                  Remove
                </Button>
                <Button
                  size="small"
                  margin="0 0 0 x-small"
                  onClick={() => setRemoving(null)}
                >
                  Keep
                </Button>
              </>
            )}
          </List.Item>
        ))}
      </List>
      <Text as="p" role="status" size="small">
        {done}
      </Text>
      {t.can_manage && t.candidates.length > 0 && (
        <Flex gap="small" alignItems="end" wrap="wrap" margin="small 0">
          <SimpleSelect
            renderLabel="Add a colleague from this course"
            value={who}
            onChange={(_e, { value }) => setWho(String(value))}
            width="16rem"
          >
            <SimpleSelect.Option id="tm-none" value="">
              Choose
            </SimpleSelect.Option>
            {t.candidates.map((c) => (
              <SimpleSelect.Option
                key={c.user_id}
                id={`tm-${c.user_id}`}
                value={c.user_id}
              >
                {nameOf(c.name)}
              </SimpleSelect.Option>
            ))}
          </SimpleSelect>
          <SimpleSelect
            renderLabel="They can"
            value={role}
            onChange={(_e, { value }) => setRole(value as "editor" | "awarder")}
            width="14rem"
          >
            <SimpleSelect.Option id="tr-awarder" value="awarder">
              Award only
            </SimpleSelect.Option>
            <SimpleSelect.Option id="tr-editor" value="editor">
              Edit and award
            </SimpleSelect.Option>
          </SimpleSelect>
          <Button
            interaction={who && !change.isPending ? "enabled" : "disabled"}
            onClick={() =>
              change.mutate({
                user: who,
                r: role,
                name: nameOf(
                  t.candidates.find((c) => c.user_id === who)?.name ?? null,
                ),
              })
            }
          >
            Add to team
          </Button>
        </Flex>
      )}
      {change.isError && <ErrorAlert error={change.error} />}
      {t.can_transfer && others.length > 0 && (
        <View as="div" margin="medium 0 0">
          <Heading level="h2" margin="0 0 x-small">
            Hand this badge to a colleague
          </Heading>
          <Text as="p" size="small">
            For example when you are leaving or handing over a service. The new
            owner manages the team; you stay on it as an editor while you are
            staff in this course.
          </Text>
          <Flex gap="small" alignItems="end" wrap="wrap" margin="small 0">
            <SimpleSelect
              renderLabel="New owner"
              value={newOwner}
              onChange={(_e, { value }) => setNewOwner(String(value))}
              width="16rem"
            >
              <SimpleSelect.Option id="ow-none" value="">
                Choose
              </SimpleSelect.Option>
              {others.map((c) => (
                <SimpleSelect.Option
                  key={c.user_id}
                  id={`ow-${c.user_id}`}
                  value={c.user_id}
                >
                  {nameOf(c.name)}
                </SimpleSelect.Option>
              ))}
            </SimpleSelect>
            <Button
              interaction={
                newOwner && !transfer.isPending ? "enabled" : "disabled"
              }
              onClick={() =>
                transfer.mutate({
                  user: newOwner,
                  name: nameOf(
                    others.find((c) => c.user_id === newOwner)?.name ?? null,
                  ),
                })
              }
            >
              Hand over
            </Button>
          </Flex>
          {transfer.isError && <ErrorAlert error={transfer.error} />}
        </View>
      )}
    </View>
  );
}

export function BadgeDetail() {
  const { id = "" } = useParams();
  const { token } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [reviewChoice, setReviewChoice] = useState<"colleague" | "skip">(
    "colleague",
  );
  const d = useQuery({
    queryKey: ["achievement", id],
    queryFn: () => apiFetch<Definition>(`/api/v1/achievements/${id}`, token),
  });
  const cat = useQuery({
    queryKey: ["categories"],
    queryFn: () => apiFetch<Catalogue>("/api/v1/categories", token),
  });

  const action = useMutation({
    mutationFn: async (
      kind:
        | "submit"
        | "publish"
        | "archive"
        | "restore"
        | "new-version"
        | "discard-version"
        | "delete",
    ) => {
      if (kind === "delete") {
        await apiFetch<unknown>(`/api/v1/achievements/${id}`, token, {
          method: "DELETE",
        }).catch((e) => {
          if (e instanceof SyntaxError) return null; // 204 has no body
          throw e;
        });
        return { kind, def: null };
      }
      const body =
        kind === "submit" && d.data?.review.mode === "author_decides"
          ? { review: reviewChoice }
          : undefined;
      const res = await apiSend<unknown>(
        `/api/v1/achievements/${id}/${kind}`,
        token,
        "POST",
        body,
      );
      const def = await apiFetch<Definition>(
        `/api/v1/achievements/${id}`,
        token,
      );
      return { kind, def, res };
    },
    onSuccess: ({ kind, def }) => {
      qc.invalidateQueries({ queryKey: ["achievements"] });
      qc.invalidateQueries({ queryKey: ["preview", id] });
      if (kind === "delete") return navigate("/badges");
      qc.setQueryData(["achievement", id], def);
      setNotice(
        {
          submit:
            def?.state === "approved"
              ? "Ready to publish: this badge does not need a colleague's review. You can publish it."
              : "Submitted for review.",
          publish:
            def?.effective_award_policy === "manual"
              ? "Published. Award it from Award badges, to one student or to a list of student ID numbers or emails."
              : "Published. Students who meet the requirements will be checked shortly.",
          archive:
            "Archived. No new awards will be made; badges already issued stay valid. You can restore the badge from this page.",
          restore:
            def?.state === "published"
              ? "Restored. The badge is live again, and students who meet the requirements will be checked shortly."
              : "Restored. The published version is live again, and the newer version you were working on is back as a draft.",
          "new-version":
            "A new draft version was created. The published version stays live until you publish this one.",
          "discard-version":
            "The new version was discarded. The published version is unchanged and still live.",
        }[kind as "submit"] ?? null,
      );
    },
  });

  if (d.isPending) return <Loading what="badge" />;
  if (d.isError)
    return (
      <Page title="Badge">
        <ErrorAlert error={d.error} />
      </Page>
    );
  const def = d.data;
  const v = def.working_version;
  const blocking = def.readiness.some((i) => i.severity === "error");
  const policy = v.award_policy ?? def.effective_award_policy;

  return (
    <Page title={v.title || "Untitled badge"}>
      <Flex gap="small" alignItems="center" wrap="wrap" margin="0 0 small">
        <Pill color={STATE_COLOR[def.state]}>{STATE_LABELS[def.state]}</Pill>
        <Text>Version {v.version_no}</Text>
        <Text>Issuer: {def.issuer.name}</Text>
        {policy && <Text>Awarding: {POLICY_LABELS[policy] ?? policy}</Text>}
        {def.live_version_id && def.live_version_id !== v.id && (
          <Text>An earlier version is live while this one is in progress.</Text>
        )}
      </Flex>
      {notice && (
        <Alert
          variant="success"
          margin="0 0 small"
          liveRegion={() => document.body}
          liveRegionPoliteness="polite"
        >
          {notice}
        </Alert>
      )}
      {action.isError && <ErrorAlert error={action.error} />}
      {def.state === "archived" && !notice && (
        <Alert variant="info" margin="0 0 small">
          This badge is archived: no new awards are made, and badges already
          issued stay valid.
          {def.can_edit || def.can_review
            ? " Restore it to start awarding again."
            : ""}
        </Alert>
      )}

      <Flex gap="small" wrap="wrap" margin="0 0 medium">
        {def.can_edit && def.state === "draft" && (
          <>
            <Button onClick={() => navigate(`/badges/${id}/edit`)}>
              Edit draft
            </Button>
            <Button
              color="primary"
              interaction={blocking ? "disabled" : "enabled"}
              onClick={() => action.mutate("submit")}
            >
              {def.review.mode === "not_required" ||
              (def.review.mode === "author_decides" && reviewChoice === "skip")
                ? "Mark ready to publish"
                : "Submit for review"}
            </Button>
            {v.version_no === 1 && (
              <ConfirmButton
                label="Delete draft"
                consequence="Delete this draft? Everything entered for it is removed and cannot be brought back."
                confirmLabel="Delete this draft"
                cancelLabel="Keep the draft"
                busy={action.isPending}
                onConfirm={() => action.mutate("delete")}
              />
            )}
          </>
        )}
        {/* The server lets the badge's reviewers publish and archive as well as its editors. */}
        {(def.can_edit || def.can_review) && def.state === "approved" && (
          <ConfirmButton
            label="Publish"
            color="primary"
            consequence={
              def.live_version_id
                ? "Publish this version? It replaces the version students see now. Badges already issued keep the version they were issued under."
                : (def.effective_award_policy ?? def.award_policy) ===
                    "automatic"
                  ? "Publish this badge? Students who meet the requirements are then awarded it automatically."
                  : "Publish this badge? Students can then earn it, and staff award it from Award badges."
            }
            confirmLabel="Publish"
            cancelLabel="Not yet"
            busy={action.isPending}
            onConfirm={() => action.mutate("publish")}
          />
        )}
        {def.can_edit &&
          def.live_version_id &&
          def.live_version_id !== v.id &&
          ["draft", "in_review", "approved"].includes(def.state) && (
            <ConfirmButton
              label="Discard this version"
              consequence={`Discard version ${v.version_no}? Its changes are removed and cannot be brought back. The published version stays live, unchanged.`}
              confirmLabel="Discard this version"
              cancelLabel="Keep working on it"
              busy={action.isPending}
              onConfirm={() => action.mutate("discard-version")}
            />
          )}
        {def.can_edit && def.state === "published" && (
          <Button onClick={() => action.mutate("new-version")}>
            Start a new version
          </Button>
        )}
        {(def.can_edit || def.can_review) && def.state === "published" && (
          <ConfirmButton
            label="Archive"
            color="danger"
            consequence="Archive this badge? No new awards will be made and students stop seeing it as something to earn. Badges already issued stay valid. You can restore it later from this page."
            confirmLabel="Archive this badge"
            cancelLabel="Keep it live"
            busy={action.isPending}
            onConfirm={() => action.mutate("archive")}
          />
        )}
        {(def.can_edit || def.can_review) && def.state === "archived" && (
          <Button
            color="primary"
            interaction={action.isPending ? "disabled" : "enabled"}
            onClick={() => action.mutate("restore")}
          >
            Restore this badge
          </Button>
        )}
        {def.course_id && def.live_version_id && (
          <AppLink to={`/courses/${def.course_id}/progress`}>
            Student progress for this course
          </AppLink>
        )}
      </Flex>

      {def.can_edit && def.state === "draft" && (
        <ReviewChoice
          review={def.review}
          value={reviewChoice}
          onChange={setReviewChoice}
        />
      )}
      {def.can_edit && def.state === "draft" && (
        <Readiness issues={def.readiness} />
      )}
      {(def.state === "in_review" || def.state === "approved") &&
        def.can_review &&
        cat.data && (
        <ReviewPanel d={def} checklistKeys={cat.data.review_checklist} />
      )}

      <Tabs
        onRequestTabChange={(_e, { index }) => setTab(index)}
        margin="medium 0 0"
      >
        <Tabs.Panel id="details" renderTitle="Details" isSelected={tab === 0}>
          <Text as="p">{v.short_description}</Text>
          <Text as="p">Category: {v.category || "(not set)"}</Text>
          {(v.graduate_attributes ?? []).length > 0 && (
            <Text as="p">
              Graduate attributes: {v.graduate_attributes.map((a) => a.name).join(", ")}
            </Text>
          )}
          <Heading level="h2">Requirements</Heading>
          {def.rules ? (
            <Text as="p">
              {def.rules.rules.length === 1
                ? "1 requirement, which students must meet."
                : `${def.rules.rules.length} requirements; students must meet ${def.rules.mode === "ALL" ? "all" : "any one"} of them.`}{" "}
              See the preview for the wording students will see.
            </Text>
          ) : (
            <Text as="p">No requirements yet.</Text>
          )}
          <Heading level="h2">Review history</Heading>
          {def.reviews.length === 0 ? (
            <Text as="p">No reviews yet.</Text>
          ) : (
            <List>
              {def.reviews.map((r) => (
                <List.Item key={r.id}>
                  {r.without_review
                    ? "Published without a colleague's review"
                    : `${r.decision === "approve" ? "Approved" : "Returned"} by ${r.reviewer ?? "a reviewer"}`}{" "}
                  on {new Date(r.created_at).toLocaleDateString()}
                  {r.comment ? `: ${r.comment}` : ""}
                </List.Item>
              ))}
            </List>
          )}
        </Tabs.Panel>
        <Tabs.Panel id="preview" renderTitle="Preview" isSelected={tab === 1}>
          {tab === 1 && <PreviewPanel id={id} />}
        </Tabs.Panel>
        {def.course_id && (
          <Tabs.Panel id="team" renderTitle="Team" isSelected={tab === 2}>
            {tab === 2 && <TeamPanel id={id} />}
          </Tabs.Panel>
        )}
      </Tabs>
    </Page>
  );
}
