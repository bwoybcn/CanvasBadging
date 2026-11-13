// SPDX-License-Identifier: AGPL-3.0-or-later
/** Student guidance: keeping credentials after leaving, and using wallets (spec §9.2, §9.5). */
import { Heading, Link, List, Text } from "@instructure/ui";

import { AppLink } from "../components/AppLink";
import { Page } from "../components/Page";

export function Keeping() {
  return (
    <Page title="Keeping your credentials">
      <Heading level="h2">Before you leave</Heading>
      <Text as="p">
        Your Canvas account will close when you leave. Your credentials do not depend on it. Before you go:
      </Text>
      <List as="ol">
        <List.Item>
          Open <AppLink to="/me/credentials">My credentials</AppLink> and download each credential file. Save the files somewhere you
          will keep, such as personal cloud storage or a personal email to yourself.
        </List.Item>
        <List.Item>Optionally import them into a digital wallet (below).</List.Item>
        <List.Item>
          If you added a credential to LinkedIn or a CV, keep its public link turned on. Public links keep working after your Canvas
          account closes unless you or the university turn them off.
        </List.Item>
      </List>
      <Heading level="h2">Why the file keeps working</Heading>
      <Text as="p">
        Each file is a signed Open Badges 3.0 credential. Anyone can check it with an Open Badges verifier, or by uploading it to
        this service's public <Link href="/verify">Check a credential</Link> page, without a Canvas account. The check needs the
        university's public verification information (its signing keys and revocation list) to stay online. The university is
        responsible for keeping that available.
      </Text>
      <Heading level="h2">Digital wallets</Heading>
      <Text as="p">
        A wallet is an app that stores credentials for you. Wallets that support Open Badges 3.0 or W3C Verifiable Credentials 2.0
        can usually import the file you download:
      </Text>
      <List>
        <List.Item>
          Learner Credential Wallet (free, open source, from the Digital Credentials Consortium): Add credential, then Import from
          file, and choose the downloaded file. It can also add from a link: use your public link followed by /credential.json.
        </List.Item>
        <List.Item>Other wallets: look for "import", "add from file" or "add from URL" and use the same file or link.</List.Item>
      </List>
      <Text as="p">
        Some wallets and badge platforms only accept credentials through their own sign-up or a different format. If a wallet
        refuses the file, the credential is still valid: keep the file and use the public link instead.
      </Text>
    </Page>
  );
}
