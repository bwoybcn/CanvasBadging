// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Help: who to ask at this institution, and the guide for what the reader does here. Every page
 * links to it from the menu, so nobody who gets stuck is left with nowhere to go.
 */
import { Heading, Link, List, Text } from "@instructure/ui";

import { AppLink } from "../components/AppLink";
import { Loading, Page, roleFlags, useMe } from "../components/Page";

/** Where the published guides live. They are written for people, not developers. */
export const GUIDES_BASE = "https://github.com/bwoybcn/CanvasBadging/blob/main/docs";

const GUIDES = {
  staff: { href: `${GUIDES_BASE}/lecturers/README.md`, label: "Creating and awarding badges (guide for course staff)" },
  student: { href: `${GUIDES_BASE}/students/README.md`, label: "Your badges: earning, keeping and sharing them (guide for students)" },
  admin: { href: `${GUIDES_BASE}/administration/README.md`, label: "Running Badges (guide for administrators)" },
} as const;

export function Help() {
  const me = useMe();
  const f = roleFlags(me.data);
  if (me.isPending)
    return (
      <Page title="Help">
        <Loading what="help" />
      </Page>
    );
  const help = me.data?.help;
  const hasContact = !!(help?.contact_name || help?.email || help?.url);
  const institution = me.data?.institution.name ?? "your institution";
  // Lead with the guide for what this person does here; the others follow for anyone curious.
  const order: (keyof typeof GUIDES)[] = f.isAdmin
    ? ["admin", "staff", "student"]
    : f.isStaff || f.isReviewer
      ? ["staff", "student", "admin"]
      : ["student", "staff", "admin"];
  return (
    <Page title="Help">
      <Heading level="h2" margin="0 0 small">
        Who to ask
      </Heading>
      {hasContact ? (
        <>
          <Text as="p">For help with badges at {institution}, contact:</Text>
          <List margin="0 0 small">
            {help?.contact_name && <List.Item>{help.contact_name}</List.Item>}
            {help?.email && (
              <List.Item>
                Email <Link href={`mailto:${help.email}`}>{help.email}</Link>
              </List.Item>
            )}
            {help?.url && (
              <List.Item>
                <Link href={help.url}>Help page at {institution}</Link>
              </List.Item>
            )}
          </List>
        </>
      ) : (
        <Text as="p">
          {institution} has not named a contact for badges yet. Ask the team that supports Canvas for you.
          {f.isInstAdmin && (
            <>
              {" "}
              You can name one in <AppLink to="/admin/institution">Institution settings</AppLink>, under Help for your
              users.
            </>
          )}
        </Text>
      )}

      <Heading level="h2" margin="medium 0 small">
        Guides
      </Heading>
      <List margin="0 0 small">
        {order.map((k) => (
          <List.Item key={k}>
            <Link href={GUIDES[k].href}>{GUIDES[k].label}</Link>
          </List.Item>
        ))}
      </List>

      <Heading level="h2" margin="medium 0 small">
        Quick answers
      </Heading>
      {f.isStaff || f.isReviewer || f.isAdmin ? (
        <List>
          <List.Item>
            A student has done the work but has no badge: Course progress, reached from the Home page or from the
            badge, shows the reason for each student, such as a mark not yet released in Canvas. Refresh from Canvas on
            that page asks for a new read.
          </List.Item>
          <List.Item>
            Your badge is waiting for review: a reviewer finds it in their Review queue. Some areas need no review or let
            you choose, and the badge page says which applies to you.
          </List.Item>
          <List.Item>
            A badge was issued by mistake: in Course progress, choose Request revocation on the issued badge and give a
            reason. Once an administrator approves it, anyone who checks the badge is told it was revoked.
          </List.Item>
        </List>
      ) : (
        <List>
          <List.Item>
            You finished the work but have no badge yet: Badges reads Canvas about every half hour, and marks count only
            once your lecturer releases them. <AppLink to="/me/progress">Badges in my courses</AppLink> shows what is
            still waiting.
          </List.Item>
          <List.Item>
            You want to keep a badge after you leave: download it from <AppLink to="/me/credentials">My badges</AppLink>.{" "}
            <AppLink to="/me/keeping">Keeping your badges</AppLink> explains how.
          </List.Item>
          <List.Item>
            Someone wants to check your badge is real: share its link from My badges, or send them the downloaded file
            and the address of the public <Link href="/verify">Check a credential file</Link> page.
          </List.Item>
        </List>
      )}
    </Page>
  );
}
