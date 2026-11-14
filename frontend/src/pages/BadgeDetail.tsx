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
  Tabs,
  Text,
  TextArea,
  View,
} from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  apiFetch,
  apiSend,
  POLICY_LABELS,
  type ReviewRequirement,
  STATE_LABELS,
  type Catalogue,
  type Definition,
  type Issue,
  type Preview,
} from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ErrorAlert, Loading, Page } from "../components/Page";

export const CHECKLIST_LABELS: Record<string, string> = {
  clarity: "Title and descriptions are clear to someone outside the course",
  level: "The level and size of the achievement are stated honestly",
  evidence: "The requirements genuinely evidence the learning outcomes",
  alignment: "Category and how it is demonstrated match what is assessed",
  accessibility: "Artwork has meaningful alternative text and readable contrast",
  consistency: "Consistent with similar badges in the institution",
  terminology: "No wording implies academic credit or a formal qualification unless approved",
};

const STATE_COLOR: Record<string, "info" | "success" | "warning" | "primary" | "danger"> = {
  draft: "primary",
  in_review: "warning",
  approved: "info",
  published: "success",
  archived: "danger",
};

function Readiness({ issues }: { issues: Issue[] }) {
  if (!issues.length) return <Alert variant="success">Ready to submit for review.</Alert>;
  const errors = issues.filter((i) => i.severity === "error");
  return (
    <Alert variant={errors.length ? "warning" : "info"}>
      <Text weight="bold">
        {errors.length ? "Before this can be submitted:" : "Things a reviewer will look at:"}
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
    queryFn: () => apiFetch<Preview>(`/api/v1/achievements/${id}/preview`, token),
  });
  if (p.isPending) return <Loading what="preview" />;
  if (p.isError) return <ErrorAlert error={p.error} />;
  const a = p.data.achievement;
  return (
    <View as="section" aria-label="Preview" display="block">
      <Alert variant="warning" margin="0 0 medium">
        <Text weight="bold">{p.data.notice}</Text>. This is how the badge would look. It is not a credential and
        cannot be verified.
      </Alert>
      <Flex gap="medium" alignItems="start">
        {p.data.artwork.data_url ? (
          <Img src={p.data.artwork.data_url} alt={p.data.artwork.alt_text ?? ""} width="10rem" height="10rem" constrain="contain" />
        ) : (
          <Text>No artwork yet</Text>
        )}
        <Flex.Item shouldShrink>
          <Heading level="h3">{a.title || "(untitled)"}</Heading>
          <Text as="p">{a.description}</Text>
          <Text as="p">
            {a.category} · {a.demonstration} · issued by {p.data.issuer.name}
          </Text>
          <Heading level="h4">Learning outcomes</Heading>
          <List>
            {a.learning_outcomes.map((o) => (
              <List.Item key={o}>{o}</List.Item>
            ))}
          </List>
          <Heading level="h4">Criteria</Heading>
          <Text as="p">{a.criteria}</Text>
          {a.requirements.length > 0 && (
            <>
              <Heading level="h4">Requirements</Heading>
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

function ReviewPanel({ d, checklistKeys }: { d: Definition; checklistKeys: string[] }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [comment, setComment] = useState("");
  const [credit, setCredit] = useState(false);
  const creditWarning = d.readiness.some((i) => i.code === "CREDIT_TERMS");
  const act = useMutation({
    mutationFn: (kind: "approve" | "reject") =>
      kind === "approve"
        ? apiSend<Definition>(`/api/v1/achievements/${d.id}/approve`, token, "POST", {
            checklist: checks,
            comment: comment || null,
            credit_claim_approved: creditWarning ? credit : null,
          })
        : apiSend<Definition>(`/api/v1/achievements/${d.id}/reject`, token, "POST", { comment, checklist: checks }),
    onSuccess: (nd) => {
      qc.setQueryData(["achievement", d.id], nd);
      qc.invalidateQueries({ queryKey: ["achievements"] });
    },
  });
  const all = checklistKeys.every((k) => checks[k]);
  return (
    <View as="section" aria-labelledby="review-h" padding="medium" borderWidth="small" borderRadius="medium" display="block" margin="medium 0">
      <Heading level="h2" id="review-h">
        Review
      </Heading>
      <Text as="p">Confirm each point before approving. To send it back, explain what needs to change.</Text>
      {checklistKeys.map((k) => (
        <Checkbox
          key={k}
          label={CHECKLIST_LABELS[k] ?? k}
          checked={!!checks[k]}
          onChange={(e) => setChecks((c) => ({ ...c, [k]: e.target.checked }))}
        />
      ))}
      {creditWarning && (
        <Checkbox
          label="I approve the wording that refers to credit or a qualification"
          checked={credit}
          onChange={(e) => setCredit(e.target.checked)}
        />
      )}
      <TextArea label="Comment to the author" value={comment} onChange={(e) => setComment(e.target.value)} />
      {act.isError && <ErrorAlert error={act.error} />}
      <Flex gap="small" margin="small 0 0">
        <Button color="primary" interaction={all && !act.isPending ? "enabled" : "disabled"} onClick={() => act.mutate("approve")}>
          Approve
        </Button>
        <Button
          color="secondary"
          interaction={comment.trim().length >= 5 && !act.isPending ? "enabled" : "disabled"}
          onClick={() => act.mutate("reject")}
        >
          Return to author
        </Button>
      </Flex>
    </View>
  );
}

const FORCED_REASON: Record<string, string> = {
  assessed: "Badges that claim assessed proficiency always need a colleague's review.",
  credit: "The wording refers to credit or a qualification, so a colleague must review it.",
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
          <RadioInput value="colleague" label="Ask a colleague to review it first (recommended)" />
          <RadioInput value="skip" label="Publish without review. Administrators can see badges published this way." />
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

export function BadgeDetail() {
  const { id = "" } = useParams();
  const { token } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [reviewChoice, setReviewChoice] = useState<"colleague" | "skip">("colleague");
  const d = useQuery({
    queryKey: ["achievement", id],
    queryFn: () => apiFetch<Definition>(`/api/v1/achievements/${id}`, token),
  });
  const cat = useQuery({ queryKey: ["categories"], queryFn: () => apiFetch<Catalogue>("/api/v1/categories", token) });

  const action = useMutation({
    mutationFn: async (kind: "submit" | "publish" | "archive" | "new-version" | "delete") => {
      if (kind === "delete") {
        await apiFetch<unknown>(`/api/v1/achievements/${id}`, token, { method: "DELETE" }).catch((e) => {
          if (e instanceof SyntaxError) return null; // 204 has no body
          throw e;
        });
        return { kind, def: null };
      }
      const body = kind === "submit" && d.data?.review.mode === "author_decides" ? { review: reviewChoice } : undefined;
      const res = await apiSend<unknown>(`/api/v1/achievements/${id}/${kind}`, token, "POST", body);
      const def = await apiFetch<Definition>(`/api/v1/achievements/${id}`, token);
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
          publish: "Published. Learners who meet the requirements will be evaluated shortly.",
          archive: "Archived. No new awards will be made; credentials already issued stay valid.",
          "new-version": "A new draft version was created. The published version stays live until you publish this one.",
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
        <Alert variant="success" margin="0 0 small" liveRegion={() => document.body} liveRegionPoliteness="polite">
          {notice}
        </Alert>
      )}
      {action.isError && <ErrorAlert error={action.error} />}

      <Flex gap="small" wrap="wrap" margin="0 0 medium">
        {def.can_edit && def.state === "draft" && (
          <>
            <Button onClick={() => navigate(`/badges/${id}/edit`)}>Edit draft</Button>
            <Button color="primary" interaction={blocking ? "disabled" : "enabled"} onClick={() => action.mutate("submit")}>
              {def.review.mode === "not_required" || (def.review.mode === "author_decides" && reviewChoice === "skip")
                ? "Mark ready to publish"
                : "Submit for review"}
            </Button>
            {v.version_no === 1 && <Button onClick={() => action.mutate("delete")}>Delete draft</Button>}
          </>
        )}
        {def.can_edit && def.state === "approved" && (
          <Button color="primary" onClick={() => action.mutate("publish")}>
            Publish
          </Button>
        )}
        {def.can_edit && def.state === "published" && (
          <>
            <Button onClick={() => action.mutate("new-version")}>Start a new version</Button>
            <Button color="danger" onClick={() => action.mutate("archive")}>
              Archive
            </Button>
          </>
        )}
        {def.course_id && def.live_version_id && (
          <AppLink to={`/courses/${def.course_id}/progress`}>Learner progress for this course</AppLink>
        )}
      </Flex>

      {def.can_edit && def.state === "draft" && (
        <ReviewChoice review={def.review} value={reviewChoice} onChange={setReviewChoice} />
      )}
      {def.can_edit && def.state === "draft" && <Readiness issues={def.readiness} />}
      {def.state === "in_review" && def.can_review && cat.data && (
        <ReviewPanel d={def} checklistKeys={cat.data.review_checklist} />
      )}

      <Tabs onRequestTabChange={(_e, { index }) => setTab(index)} margin="medium 0 0">
        <Tabs.Panel id="details" renderTitle="Details" isSelected={tab === 0}>
          <Text as="p">{v.short_description}</Text>
          <Text as="p">Category: {v.category || "(not set)"}</Text>
          <Heading level="h3">Requirements</Heading>
          {def.rules ? (
            <Text as="p">
              {def.rules.rules.length} requirement(s); learners must meet {def.rules.mode === "ALL" ? "all" : "any one"}{" "}
              of them. See the preview for the wording learners will see.
            </Text>
          ) : (
            <Text as="p">No requirements yet.</Text>
          )}
          <Heading level="h3">Review history</Heading>
          {def.reviews.length === 0 ? (
            <Text as="p">No reviews yet.</Text>
          ) : (
            <List>
              {def.reviews.map((r) => (
                <List.Item key={r.id}>
                  {r.without_review
                    ? "Published without a colleague's review"
                    : `${r.decision === "approve" ? "Approved" : "Returned"} by ${r.reviewer ?? "a reviewer"}`}{" "}
                  on{" "}
                  {new Date(r.created_at).toLocaleDateString()}
                  {r.comment ? `: ${r.comment}` : ""}
                </List.Item>
              ))}
            </List>
          )}
        </Tabs.Panel>
        <Tabs.Panel id="preview" renderTitle="Preview" isSelected={tab === 1}>
          {tab === 1 && <PreviewPanel id={id} />}
        </Tabs.Panel>
      </Tabs>
    </Page>
  );
}
