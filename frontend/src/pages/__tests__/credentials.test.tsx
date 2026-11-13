// SPDX-License-Identifier: AGPL-3.0-or-later
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ShareState } from "../../api";
import { renderAt, STAFF_ME, stubApi } from "../../test/util";

afterEach(() => vi.unstubAllGlobals());

const STUDENT_ME = { ...STAFF_ME, memberships: [{ role: "student", scope_type: "course", scope_id: "c-1", scope_name: "S" }] };
const PRIVATE: ShareState = { shared: false, url: null, show_name: false, show_evidence: false, shared_since: null };
const SHARED: ShareState = { shared: true, url: "https://verify.example/verify/AbCdEfGhIjKlMnOpQrStUv", show_name: false, show_evidence: false, shared_since: "2026-11-13T10:00:00Z" };

function summary(over: Record<string, unknown> = {}) {
  return {
    id: "cr-1",
    credential_id: "urn:uuid:1111",
    name: "Academic Writing Foundations",
    issuer_name: "Skills Centre",
    issued_at: "2026-11-01T09:00:00Z",
    valid_until: null,
    status: "active",
    course: { id: "c-1", title: "Study Skills 101" },
    image: { data_url: null, alt_text: "Blue shield" },
    share: PRIVATE,
    ...over,
  };
}

const LINKEDIN_FIELDS = (url: string | null) => [
  { key: "name", label: "Name", value: "Academic Writing Foundations" },
  { key: "organization", label: "Issuing organization", value: "Demo University" },
  { key: "issue_date", label: "Issue date", value: "2026-11-01" },
  { key: "expiration_date", label: "Expiration date", value: "This credential does not expire" },
  { key: "credential_id", label: "Credential ID", value: "urn:uuid:1111" },
  { key: "credential_url", label: "Credential URL", value: url },
];

function detail(share: ShareState = PRIVATE) {
  return {
    ...summary({ share }),
    description: "Learners plan and write a short academic text.",
    criteria: "Complete the writing module.",
    achievement_type: "Badge",
    learning_outcomes: ["Structure an academic argument"],
    skills: [],
    evidence: [{ narrative: "Reflective essay", url: null, genre: "artefact" }],
    issuer: { name: "Skills Centre", id: "did:key:z", url: null, institution: "Demo University" },
    verification: { result: "verified", label: "Verified", checks: [], explanation: "Verification confirms the signature.", checked_at: "" },
    linkedin: {
      fields: LINKEDIN_FIELDS(share.url),
      add_to_profile_url: share.url ? `https://www.linkedin.com/profile/add?startTask=CERTIFICATION_NAME&certUrl=${encodeURIComponent(share.url)}` : null,
      needs_share: !share.url,
      note: "LinkedIn does not import the credential file itself.",
    },
  };
}

function preview(showName: boolean) {
  return {
    public: { credential_name: "Academic Writing Foundations", recipient_name: showName ? "Sam Student" : null, evidence: [] },
    visible: [
      { label: "Badge name", value: "Academic Writing Foundations" },
      { label: "Your name", value: showName ? "Sam Student" : "Not shown" },
    ],
    never_shared: ["Your email address and Canvas login", "Your marks, grades and Canvas submissions"],
    search_engines: "The page asks search engines not to index it.",
    withdrawing: "You can stop sharing at any time.",
  };
}

describe("student collection", () => {
  it("groups earned credentials by course and shows status and privacy", async () => {
    stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/learners/me/credentials": [
        summary(),
        summary({ id: "cr-2", name: "Lab Safety", course: { id: "c-2", title: "Chemistry 1" }, status: "revoked", share: SHARED }),
      ],
    });
    renderAt("/me/credentials");
    const course = await screen.findByRole("region", { name: "Study Skills 101" });
    const card = within(course).getByRole("region", { name: "Academic Writing Foundations" });
    expect(within(card).getByText("Valid")).toBeInTheDocument();
    expect(within(card).getByText("Private")).toBeInTheDocument();
    const other = screen.getByRole("region", { name: "Lab Safety" });
    expect(within(other).getByText("Revoked")).toBeInTheDocument();
    expect(within(other).getByText("Shared publicly")).toBeInTheDocument();
    // AppLink renders InstUI Link with a click handler, which InstUI exposes as role "button".
    expect(await screen.findByRole("button", { name: "My credentials" })).toHaveAttribute("href", "/me/credentials");
  });
});

describe("credential detail", () => {
  it("previews exactly what becomes public before sharing, then shares", async () => {
    let current = detail(PRIVATE);
    const calls = stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/credentials/cr-1": () => current,
      "POST /api/v1/credentials/cr-1/share/preview": (b: unknown) => preview(Boolean((b as { show_name: boolean }).show_name)),
      "PUT /api/v1/credentials/cr-1/share": () => {
        current = detail(SHARED);
        return { share: SHARED, linkedin: current.linkedin, preview: preview(false) };
      },
    });
    const user = userEvent.setup();
    renderAt("/me/credentials/cr-1");
    expect(await screen.findByText(/This credential is private/)).toBeInTheDocument();
    expect(screen.getByText(/Verification: Verified/)).toBeInTheDocument();
    expect(await screen.findByText("Not shown")).toBeInTheDocument();
    expect(screen.getByText("Your email address and Canvas login")).toBeInTheDocument();
    // LinkedIn waits for a public link.
    expect(screen.getByText(/Turn on the public link first/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add certification form/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Show my name on the page" }));
    expect(await screen.findByText("Sam Student")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Show my name on the page" }));
    await user.click(screen.getByRole("button", { name: "Turn on public link" }));

    await waitFor(() => expect(screen.getByText(/This credential is shared/)).toBeInTheDocument());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ show_name: false, show_evidence: false });
    expect(screen.getByRole("link", { name: SHARED.url! })).toBeInTheDocument();
    expect(screen.getByText(/does not revoke your credential/)).toBeInTheDocument();
    const li = screen.getByRole("region", { name: "Add to LinkedIn" });
    expect(within(li).getByRole("link", { name: /Add certification form/ })).toHaveAttribute(
      "href",
      expect.stringContaining("startTask=CERTIFICATION_NAME"),
    );
    expect(within(li).getByText("urn:uuid:1111")).toBeInTheDocument();
    expect(within(li).getByRole("button", { name: "Copy credential url" })).toBeInTheDocument();
  });

  it("stops sharing without revoking", async () => {
    let current = detail(SHARED);
    const calls = stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/credentials/cr-1": () => current,
      "POST /api/v1/credentials/cr-1/share/preview": () => preview(false),
      "DELETE /api/v1/credentials/cr-1/share": () => {
        current = detail(PRIVATE);
        return { share: PRIVATE, linkedin: current.linkedin, preview: preview(false) };
      },
    });
    const user = userEvent.setup();
    renderAt("/me/credentials/cr-1");
    await user.click(await screen.findByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(screen.getByText(/This credential is private/)).toBeInTheDocument());
    expect(calls.some((c) => c.method === "DELETE")).toBe(true);
    expect(calls.some((c) => c.url.includes("/revoke"))).toBe(false);
  });

  it("explains how to keep credentials after leaving", async () => {
    stubApi({ "GET /api/v1/learners/me": STUDENT_ME });
    renderAt("/me/keeping");
    expect(await screen.findByRole("heading", { name: "Before you leave" })).toBeInTheDocument();
    expect(screen.getByText(/Learner Credential Wallet/)).toBeInTheDocument();
  });
});
