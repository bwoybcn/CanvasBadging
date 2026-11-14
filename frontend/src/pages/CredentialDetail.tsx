// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * One credential for its holder (spec §8.3, §8.4, §9.3): details, verification, download,
 * student-controlled public sharing with a preview of exactly what becomes public, and the
 * LinkedIn "Add license or certification" values.
 */
import { Alert, Button, Checkbox, Flex, Heading, Img, Link, List, Pill, Text, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { useParams } from "react-router";

import {
  apiFetch,
  apiSend,
  CREDENTIAL_STATE,
  type CredentialDetail as Detail,
  downloadFile,
  formatDate,
  type LinkedIn,
  problemText,
  type ShareOut,
  type SharePreview,
} from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ErrorAlert, Loading, Page } from "../components/Page";

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="oc-facts">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "flex", gap: "1rem", flexWrap: "wrap", margin: "0 0 0.35rem" }}>
          <dt style={{ fontWeight: 600, minWidth: "10rem" }}>{k}</dt>
          <dd style={{ margin: 0, overflowWrap: "anywhere" }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="small"
      onClick={() => {
        navigator.clipboard?.writeText(value).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
    >
      {copied ? `Copied ${label.toLowerCase()}` : `Copy ${label.toLowerCase()}`}
    </Button>
  );
}

function VerificationPanel({ d }: { d: Detail }) {
  const v = d.verification;
  const variant = v.result === "verified" ? "success" : v.result === "unable_to_verify" ? "info" : "error";
  return (
    <Alert variant={variant} margin="0 0 medium">
      <Text weight="bold">Verification: {v.label}.</Text> {v.explanation}
    </Alert>
  );
}

function SharePanel({ d }: { d: Detail }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  // Unsaved choices; ``null`` means "as currently saved".
  const [nameChoice, setShowName] = useState<boolean | null>(null);
  const [evidenceChoice, setShowEvidence] = useState<boolean | null>(null);
  const showName = nameChoice ?? d.share.show_name;
  const showEvidence = evidenceChoice ?? d.share.show_evidence;
  const options = { show_name: showName, show_evidence: showEvidence };
  const preview = useQuery({
    queryKey: ["share-preview", d.id, showName, showEvidence],
    queryFn: () => apiSend<SharePreview>(`/api/v1/credentials/${d.id}/share/preview`, token, "POST", options),
  });
  const refresh = () => {
    setShowName(null);
    setShowEvidence(null);
    return qc.invalidateQueries({ queryKey: ["credential", d.id] });
  };
  const share = useMutation({
    mutationFn: () => apiSend<ShareOut>(`/api/v1/credentials/${d.id}/share`, token, "PUT", options),
    onSuccess: refresh,
  });
  const unshare = useMutation({
    mutationFn: () => apiSend<ShareOut>(`/api/v1/credentials/${d.id}/share`, token, "DELETE"),
    onSuccess: refresh,
  });
  const changed = d.share.shared && (showName !== d.share.show_name || showEvidence !== d.share.show_evidence);
  return (
    <View as="section" aria-labelledby="share-h" padding="medium" borderWidth="small" borderRadius="medium" display="block" margin="0 0 medium">
      <Heading level="h2" id="share-h">
        Public link
      </Heading>
      {d.share.shared && d.share.url ? (
        <>
          <Text as="p">
            This badge is shared. Anyone with the link can see the page below and check that the badge is genuine.
          </Text>
          <Flex gap="small" wrap="wrap" alignItems="center" margin="0 0 small">
            <Link href={d.share.url} target="_blank">
              {d.share.url}
            </Link>
            <CopyValue label="Link" value={d.share.url} />
          </Flex>
        </>
      ) : (
        <Text as="p">
          This badge is private. Nobody else can see it until you turn on a public link. Search engines are asked not to index
          shared pages.
        </Text>
      )}
      <fieldset style={{ border: 0, padding: 0, margin: "0 0 0.75rem" }}>
        <legend style={{ fontWeight: 600 }}>What the public page shows</legend>
        <Checkbox label="Show my name on the page" checked={showName} onChange={() => setShowName(!showName)} />
        {d.evidence.length > 0 && (
          <Checkbox label="Show the evidence in this badge" checked={showEvidence} onChange={() => setShowEvidence(!showEvidence)} />
        )}
      </fieldset>
      <View as="div" background="secondary" padding="small" borderRadius="medium" display="block" margin="0 0 small">
        <Heading level="h3">Preview: what becomes visible</Heading>
        {preview.isPending && <Loading what="the preview" />}
        {preview.isError && <ErrorAlert error={preview.error} />}
        {preview.data && (
          <>
            <Facts rows={preview.data.visible.map((r) => [r.label, r.value])} />
            <Text as="p" weight="bold">
              Never shown
            </Text>
            <List>
              {preview.data.never_shared.map((s) => (
                <List.Item key={s}>{s}</List.Item>
              ))}
            </List>
            <Text as="p" size="small">
              {preview.data.search_engines} {preview.data.withdrawing}
            </Text>
          </>
        )}
      </View>
      {(share.error || unshare.error) && <ErrorAlert error={share.error || unshare.error} />}
      <Flex gap="small" wrap="wrap">
        {!d.share.shared && (
          <Button color="primary" onClick={() => share.mutate()} interaction={share.isPending ? "disabled" : "enabled"}>
            Turn on public link
          </Button>
        )}
        {changed && (
          <Button color="primary" onClick={() => share.mutate()} interaction={share.isPending ? "disabled" : "enabled"}>
            Save changes to the public page
          </Button>
        )}
        {d.share.shared && (
          <Button onClick={() => unshare.mutate()} interaction={unshare.isPending ? "disabled" : "enabled"}>
            Stop sharing
          </Button>
        )}
      </Flex>
      {d.share.shared && (
        <Text as="p" size="small">
          Stopping sharing only turns the link off. It does not revoke your badge, and copies of the credential file you have downloaded stay valid.
        </Text>
      )}
    </View>
  );
}

function LinkedInPanel({ li }: { li: LinkedIn }) {
  return (
    <View as="section" aria-labelledby="li-h" padding="medium" borderWidth="small" borderRadius="medium" display="block" margin="0 0 medium">
      <Heading level="h2" id="li-h">
        Add to LinkedIn
      </Heading>
      {li.needs_share ? (
        <Alert variant="info" margin="small 0">
          Turn on the public link first. LinkedIn shows your Credential URL so people can check your badge.
        </Alert>
      ) : (
        <Text as="p">{li.note}</Text>
      )}
      <dl>
        {li.fields.map((f) => (
          <div key={f.key} style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center", margin: "0 0 0.5rem" }}>
            <dt style={{ fontWeight: 600, minWidth: "10rem" }}>{f.label}</dt>
            <dd style={{ margin: 0, overflowWrap: "anywhere", flex: "1 1 12rem", display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
              <span>{f.value ?? "Available once you turn on the public link"}</span>
              {f.value && <CopyValue label={f.label} value={f.value} />}
            </dd>
          </div>
        ))}
      </dl>
      {li.add_to_profile_url && (
        <Button color="primary" href={li.add_to_profile_url} target="_blank" margin="small 0 0">
          Open LinkedIn's Add certification form
        </Button>
      )}
      <Text as="p" size="small">
        LinkedIn opens in a new tab. You sign in to LinkedIn yourself; this service never sees your LinkedIn account.
      </Text>
    </View>
  );
}

export function CredentialDetail() {
  const { id = "" } = useParams();
  const { token } = useAuth();
  const [dlError, setDlError] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["credential", id],
    queryFn: () => apiFetch<Detail>(`/api/v1/credentials/${id}`, token),
  });
  const d = q.data;
  return (
    <Page title={d?.name ?? "Badge"}>
      <AppLink to="/me/credentials">Back to my badges</AppLink>
      {q.isPending && <Loading what="the badge" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {d && (
        <>
          <View as="section" aria-labelledby="about-h" padding="medium 0" display="block">
            <Flex gap="medium" alignItems="start" wrap="wrap">
              {d.image.data_url && <Img src={d.image.data_url} alt={d.image.alt_text} width="8rem" height="8rem" constrain="contain" />}
              <Flex.Item shouldGrow shouldShrink>
                <Heading level="h2" id="about-h">
                  About this badge
                </Heading>
                <Pill color={CREDENTIAL_STATE[d.status].color}>{CREDENTIAL_STATE[d.status].label}</Pill>
                <Text as="p">{d.description}</Text>
              </Flex.Item>
            </Flex>
            <VerificationPanel d={d} />
            <Facts
              rows={[
                ["Issuer", `${d.issuer.name}, ${d.issuer.institution}`],
                ["Course", d.course?.title ?? ""],
                ["Issued on", formatDate(d.issued_at)],
                ["Expires on", d.valid_until ? formatDate(d.valid_until) : "Does not expire"],
                ["Criteria", d.criteria],
                ["Credential ID", d.credential_id],
              ]}
            />
            {d.learning_outcomes.length > 0 && (
              <>
                <Heading level="h3">Learning outcomes</Heading>
                <List>
                  {d.learning_outcomes.map((o) => (
                    <List.Item key={o}>{o}</List.Item>
                  ))}
                </List>
              </>
            )}
            {d.skills.length > 0 && (
              <>
                <Heading level="h3">Related skills</Heading>
                <List>
                  {d.skills.map((s) => (
                    <List.Item key={`${s.name}-${s.url}`}>{s.url ? <Link href={s.url}>{s.name ?? s.url}</Link> : s.name}</List.Item>
                  ))}
                </List>
              </>
            )}
            {d.evidence.length > 0 && (
              <>
                <Heading level="h3">Evidence in this badge</Heading>
                <List>
                  {d.evidence.map((e) => (
                    <List.Item key={e.narrative}>{e.narrative}</List.Item>
                  ))}
                </List>
              </>
            )}
          </View>
          <View as="section" aria-labelledby="keep-h" padding="medium" borderWidth="small" borderRadius="medium" display="block" margin="0 0 medium">
            <Heading level="h2" id="keep-h">
              Download and keep
            </Heading>
            <Text as="p">
              The credential file is your badge in signed Open Badges 3.0 form. Anyone can check it without Canvas, and it keeps working after you
              leave. You can also import it into a digital wallet. <AppLink to="/me/keeping">How to keep and use your badges</AppLink>
            </Text>
            <Button
              color="primary"
              onClick={() => {
                setDlError(null);
                downloadFile(`/api/v1/credentials/${d.id}/export`, token, "credential.json").catch((e) => setDlError(problemText(e)));
              }}
            >
              Download credential file
            </Button>
            {dlError && (
              <Alert variant="error" margin="small 0 0">
                {dlError}
              </Alert>
            )}
          </View>
          <SharePanel d={d} />
          <LinkedInPanel li={d.linkedin} />
        </>
      )}
    </Page>
  );
}
