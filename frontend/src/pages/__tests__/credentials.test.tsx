// SPDX-License-Identifier: AGPL-3.0-or-later
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ShareState } from "../../api";
import { renderAt, STUDENT_ME, stubApi } from "../../test/util";

afterEach(() => vi.unstubAllGlobals());

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
    // A navigation item is a link, never a "button" (W6 screen-reader finding), and marks the
    // page you are on.
    const nav = await screen.findByRole("link", { name: "My badges" });
    expect(nav).toHaveAttribute("href", "/me/credentials");
    expect(nav).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "My badges" })).toBeNull();
    // A certificate is offered for a valid badge, not for a revoked one.
    expect(within(card).getByRole("button", { name: "Download certificate for Academic Writing Foundations" })).toBeInTheDocument();
    expect(within(other).queryByRole("button", { name: /Download certificate/ })).toBeNull();
  });
});

describe("download and keep", () => {
  function stubDownloads() {
    const created = vi.fn(() => "blob:test");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() }));
    return created;
  }
  const file = (type: string) => () => new Response("x", { status: 200, headers: { "content-type": type } });

  it("downloads the certificate with or without the name, the image and the credential file", async () => {
    stubDownloads();
    const calls = stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/credentials/cr-1": { ...detail(PRIVATE), image: { data_url: "data:image/png;base64,AAAA", alt_text: "Blue shield" } },
      "POST /api/v1/credentials/cr-1/share/preview": () => preview(false),
      "GET /api/v1/credentials/cr-1/certificate?show_name=true": file("application/pdf"),
      "GET /api/v1/credentials/cr-1/certificate?show_name=false": file("application/pdf"),
      "GET /api/v1/credentials/cr-1/image": file("image/png"),
      "GET /api/v1/credentials/cr-1/export": file("application/ld+json"),
    });
    const user = userEvent.setup();
    renderAt("/me/credentials/cr-1");
    const keep = await screen.findByRole("region", { name: "Download and keep" });
    // Private badge: the page says how to get a QR code on the certificate.
    expect(within(keep).getByText(/turn on the public link below first/)).toBeInTheDocument();
    const name = within(keep).getByRole("checkbox", { name: "Put my name on the certificate" });
    expect(name).toBeChecked();
    await user.click(within(keep).getByRole("button", { name: "Download certificate (PDF)" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/certificate?show_name=true"))).toBe(true));
    await user.click(name);
    await user.click(within(keep).getByRole("button", { name: "Download certificate (PDF)" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/certificate?show_name=false"))).toBe(true));
    await user.click(within(keep).getByRole("button", { name: "Download badge image" }));
    await user.click(within(keep).getByRole("button", { name: "Download credential file" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/export"))).toBe(true));
    expect(calls.some((c) => c.url.endsWith("/image"))).toBe(true);
    expect(within(keep).queryByRole("alert")).toBeNull();
  });

  it("says the certificate carries a QR code once the badge is shared, and shows why a download failed", async () => {
    stubDownloads();
    stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/credentials/cr-1": detail(SHARED),
      "POST /api/v1/credentials/cr-1/share/preview": () => preview(false),
      "GET /api/v1/credentials/cr-1/certificate?show_name=true": () =>
        new Response(
          JSON.stringify({
            status: 409,
            code: "NAME_NOT_PRINTABLE",
            title: "The certificate cannot print your name",
            detail: "The certificate cannot print some of the characters in your name yet. On the badge's page, untick \"Put my name on the certificate\" and download it again.",
          }),
          { status: 409, headers: { "content-type": "application/problem+json" } },
        ),
    });
    const user = userEvent.setup();
    renderAt("/me/credentials/cr-1");
    const keep = await screen.findByRole("region", { name: "Download and keep" });
    expect(within(keep).getByText(/carries a QR code that opens your public link/)).toBeInTheDocument();
    // The public page hides the name, so the page warns that the certificate and the page differ.
    expect(within(keep).getByText(/only if you choose to show it there/)).toBeInTheDocument();
    // No artwork on this badge, so no image to download.
    expect(within(keep).queryByRole("button", { name: "Download badge image" })).toBeNull();
    await user.click(within(keep).getByRole("button", { name: "Download certificate (PDF)" }));
    expect(await within(keep).findByText(/cannot print some of the characters in your name/)).toBeInTheDocument();
  });

  it("offers no certificate for a revoked badge but keeps the credential file", async () => {
    stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/credentials/cr-1": { ...detail(PRIVATE), status: "revoked" },
      "POST /api/v1/credentials/cr-1/share/preview": () => preview(false),
    });
    renderAt("/me/credentials/cr-1");
    const keep = await screen.findByRole("region", { name: "Download and keep" });
    expect(within(keep).getByText("A certificate can be downloaded only while the badge is valid.")).toBeInTheDocument();
    expect(within(keep).queryByRole("button", { name: "Download certificate (PDF)" })).toBeNull();
    expect(within(keep).getByRole("button", { name: "Download credential file" })).toBeInTheDocument();
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
    expect(await screen.findByText(/This badge is private/)).toBeInTheDocument();
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

    await waitFor(() => expect(screen.getByText(/This badge is shared/)).toBeInTheDocument());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ show_name: false, show_evidence: false });
    expect(screen.getByRole("link", { name: SHARED.url! })).toBeInTheDocument();
    expect(screen.getByText(/does not revoke your badge/)).toBeInTheDocument();
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
    // It asks first, and says links already given out (LinkedIn, a CV) stop working for good.
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    expect(screen.getByRole("alert")).toHaveTextContent(/LinkedIn, your CV/);
    expect(screen.getByRole("alert")).toHaveTextContent(/you get a new link/);
    await user.click(screen.getByRole("button", { name: "Stop sharing" }));
    await waitFor(() => expect(screen.getByText(/This badge is private/)).toBeInTheDocument());
    expect(calls.some((c) => c.method === "DELETE")).toBe(true);
    expect(calls.some((c) => c.url.includes("/revoke"))).toBe(false);
  });

  it("says plainly when a badge was withdrawn, and stops offering to share it", async () => {
    stubApi({
      "GET /api/v1/learners/me": STUDENT_ME,
      "GET /api/v1/credentials/cr-1": {
        ...detail(PRIVATE),
        status: "revoked",
        verification: { ...detail(PRIVATE).verification, result: "revoked", label: "Revoked" },
        withdrawal: { state: "revoked", on: "2026-11-15T12:00:00Z", reason_code: "issued_in_error", issuer_name: "Skills Centre" },
      },
      "POST /api/v1/credentials/cr-1/share/preview": () => preview(false),
    });
    renderAt("/me/credentials/cr-1");
    expect(await screen.findByText(/Skills Centre withdrew \(revoked\) this badge on 15 November 2026/)).toBeInTheDocument();
    expect(screen.getByText("Reason: Issued in error.")).toBeInTheDocument();
    expect(screen.getByText(/The issuer has withdrawn this badge, so it no longer counts as valid/)).toBeInTheDocument();
    expect(screen.queryByText(/has not been revoked by the issuer/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Turn on public link" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /LinkedIn/ })).toBeNull();
  });

  it("explains how to keep credentials after leaving", async () => {
    stubApi({ "GET /api/v1/learners/me": STUDENT_ME });
    renderAt("/me/keeping");
    expect(await screen.findByRole("heading", { name: "Before you leave" })).toBeInTheDocument();
    expect(screen.getByText(/Learner Credential Wallet/)).toBeInTheDocument();
  });
});
