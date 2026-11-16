// SPDX-License-Identifier: AGPL-3.0-or-later
// Spec §19.3 end-to-end scenarios E1–E12, driven through the browser against a running stack
// (the dev Compose stack, or the "without Docker" setup). Canvas is the demo course served by
// the in-memory adapter that `oc seed` loads; the real-Canvas pass is recorded separately in
// docs/reports/e2e.md. Scenarios run in order: E1 creates the badge that E2–E4 use.
import { type Download, type Page, expect, test } from "@playwright/test";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";

import { Api, type Achievement, type Credential, STAFF, choose, devUsers, eventually, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

const RUN = Date.now().toString(36);
const TITLE = `Seminar Skills E2E ${RUN}`;
const COURSE = "Academic Skills Passport (demo)";

interface MyAchievement {
  definition_id: string;
  title: string;
  status: string;
  credential_id: string | null;
  requirements: { description: string; outcome: string; label?: string }[];
}

const state: {
  badgeId?: string;
  courseId?: string;
  earners?: string[];
  credentialId?: string;
  downloaded?: string;
  student?: string;
} = {};

async function learners(page: Page) {
  return (await devUsers(page.request)).filter((u) => u.roles.includes("student"));
}

async function achievementsOf(page: Page, name: string): Promise<MyAchievement[]> {
  return (await Api.as(page.request, name)).get<MyAchievement[]>("/api/v1/learners/me/achievements");
}

async function download(page: Page, click: () => Promise<void>): Promise<string> {
  const [dl] = await Promise.all([page.waitForEvent("download"), click()]);
  const path = await (dl as Download).path();
  return readFileSync(path!, "utf-8");
}

async function verifyFileAnonymously(page: Page, json: string): Promise<string> {
  const ctx = await page.context().browser()!.newContext();
  const p = await ctx.newPage();
  await p.goto("/verify");
  await p.locator('input[type="file"]').setInputFiles({ name: "credential.json", mimeType: "application/json", buffer: Buffer.from(json) });
  await p.getByRole("button", { name: "Check the file" }).click();
  const out = p.getByRole("status");
  // The verdict is the result heading (for example "Verified" or "Revoked"), as on a shared page.
  const verdict = out.getByRole("heading", { level: 2 });
  await expect(verdict).toBeVisible({ timeout: 20_000 });
  const text = await verdict.innerText();
  await ctx.close();
  return text;
}

test("E1 lecturer creates a badge: draft, preview, review, publish", async ({ page }) => {
  await signIn(page, STAFF.lecturer);
  await page.goto("/app/badges/new");
  // 1 Course and issuer
  await choose(page, "Course", COURSE);
  await choose(page, "Issuer", /Academic Skills Centre/);
  await page.getByRole("button", { name: "Next" }).click();
  // 2 About the badge
  await page.getByLabel("Title").fill(TITLE);
  await page.getByLabel(/Short description/).fill("Takes part in and contributes to academic seminars.");
  await choose(page, "Category", /./);
  await page.getByRole("button", { name: "Next" }).click();
  // 3 Outcomes and criteria
  await page.getByLabel("Learning outcome 1").fill("Contribute constructively to a seminar discussion");
  await page.getByLabel(/^Criteria/).fill("Complete the Seminar Skills module in Canvas.");
  await page.getByRole("button", { name: "Next" }).click();
  // 4 Artwork (generated from a template, with alternative text)
  await page.getByLabel("Short label").fill("Seminar");
  await page.getByLabel(/Alternative text/).fill("Green shield with a speech bubble and the word Seminar");
  await page.getByRole("button", { name: /artwork/i }).first().click();
  await expect(page.getByRole("img", { name: /Seminar/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  // 5 Requirements: one Canvas module
  await page.getByRole("button", { name: "Add requirement" }).click();
  await choose(page, "Requirement 1: type", /module/i);
  await choose(page, /Module/, "Seminar Skills");
  await page.getByRole("button", { name: "Next" }).click();
  // 6 Awarding
  await page.getByRole("radio", { name: /automatic/i }).first().check();
  await page.getByRole("button", { name: "Next" }).click();
  // 7 Check and save
  await expect(page.getByText(`Title: ${TITLE}`)).toBeVisible();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page).toHaveURL(/\/app\/badges\/[0-9a-f-]{36}$/);
  state.badgeId = page.url().split("/").pop();
  await expect(page.getByText(/draft/i).first()).toBeVisible();
  await expect(page.getByText(/preview/i).first()).toBeVisible();
  await page.getByRole("button", { name: /Submit/ }).click();
  await expect(page.getByText(/submitted|in review|awaiting review/i).first()).toBeVisible();

  // a reviewer (department administrator) approves with the quality checklist
  await signIn(page, STAFF.reviewer);
  await page.goto("/app/reviews");
  await page.getByRole("link", { name: TITLE }).click();
  await expect(page.getByRole("checkbox").first()).toBeVisible();
  for (const box of await page.getByRole("checkbox").all()) await box.check({ force: true });
  await page.getByRole("button", { name: /Approve/ }).click();
  await expect(page.getByText(/approved/i).first()).toBeVisible();

  // the lecturer publishes
  await signIn(page, STAFF.lecturer);
  await page.goto(`/app/badges/${state.badgeId}`);
  await page.getByRole("button", { name: /Publish/ }).click();
  // Publish asks first; confirm it.
  await page.getByRole("group", { name: "Publish" }).getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText(/published/i).first()).toBeVisible();
  const lec = await Api.as(page.request, STAFF.lecturer);
  const b = (await lec.get<{ items: Achievement[] }>("/api/v1/achievements")).items.find((x) => x.id === state.badgeId)!;
  expect(b.state).toBe("published");
  state.courseId = b.course_id;
});

test("E2 student completes requirements: Canvas completion leads to an issued credential", async ({ page }) => {
  // The demo course reports "Seminar Skills" complete for some learners. Refresh from Canvas.
  await signIn(page, STAFF.lecturer);
  await page.goto(`/app/courses/${state.courseId}/progress`);
  await page.getByRole("button", { name: "Refresh from Canvas" }).click();
  // Either a refresh is queued, or the course was refreshed moments ago (rate limit): in both
  // cases the newly published badge is evaluated against the latest Canvas snapshot.
  await expect(page.getByText(/Refresh requested|refreshed recently/).first()).toBeVisible();

  const students = await learners(page);
  const earners = await eventually(async () => {
    const got: string[] = [];
    for (const s of students) {
      const mine = (await achievementsOf(page, s.display_name)).find((a) => a.definition_id === state.badgeId);
      if (mine?.credential_id) got.push(s.display_name);
    }
    return got.length ? got : null;
  }, "the worker to sync, evaluate and issue");
  state.earners = earners;
  state.student = earners[0];

  // The learner sees it in their collection.
  await signIn(page, state.student);
  await page.goto("/app/me/credentials");
  await expect(page.getByRole("link", { name: new RegExp(TITLE) })).toBeVisible();
  // Learners who have not completed the module do not get it.
  const others = students.filter((s) => !earners.includes(s.display_name));
  const sample = (await achievementsOf(page, others[0].display_name)).find((a) => a.definition_id === state.badgeId)!;
  expect(sample.credential_id).toBeNull();
});

test("E3 duplicate event: processing the completion again creates no second credential", async ({ page }) => {
  const stu = await Api.as(page.request, state.student!);
  const count = async () =>
    (await stu.get<Credential[]>("/api/v1/learners/me/credentials")).filter((c) => c.name === TITLE).length;
  expect(await count()).toBe(1);
  const lec = await Api.as(page.request, STAFF.lecturer);
  // The same completion processed again, three times: a manual re-evaluation of the badge for
  // everyone (spec §6.4), which runs the rules on the same Canvas facts. (A second Canvas
  // refresh straight away is rate-limited, by design.)
  for (let i = 0; i < 3; i++) await lec.post("/api/v1/evaluations", { definition_id: state.badgeId });
  await page.waitForTimeout(5_000); // let the worker run anything that was queued
  expect(await count()).toBe(1);
  await signIn(page, state.student!);
  await page.goto("/app/me/credentials");
  await expect(page.getByRole("link", { name: new RegExp(TITLE) })).toHaveCount(1);
});

test("E4 incomplete grade: a missing or unreleased mark stays pending and issues nothing", async ({ page }) => {
  // "Academic Presentations" needs at least 60% on an assignment.
  for (const s of await learners(page)) {
    const a = (await achievementsOf(page, s.display_name)).find((x) => x.title === "Academic Presentations");
    if (!a || a.credential_id) continue;
    const pending = a.requirements.find((r) => r.outcome !== "met");
    if (!pending) continue;
    await signIn(page, s.display_name);
    await page.goto("/app/me/progress");
    await expect(page.getByText("Academic Presentations").first()).toBeVisible();
    await expect(page.getByText(/not yet|waiting|pending|awaiting/i).first()).toBeVisible();
    const creds = await (await Api.as(page.request, s.display_name)).get<Credential[]>("/api/v1/learners/me/credentials");
    expect(creds.some((c) => c.name === "Academic Presentations")).toBeFalsy();
    return;
  }
  throw new Error("no learner with a pending score requirement in the demo data");
});

test("E5 manual award: lecturer awards with justification; decision recorded and issued", async ({ page }) => {
  const students = await learners(page);
  let target = "";
  for (const s of students) {
    const a = (await achievementsOf(page, s.display_name)).find((x) => x.title === "Seminar Participation");
    if (a && !a.credential_id && a.status !== "awarded") {
      target = s.display_name;
      break;
    }
  }
  expect(target, "a learner without Seminar Participation").not.toBe("");
  await signIn(page, STAFF.lecturer);
  await page.goto("/app/awards");
  // "Award badges" has three tabs; the list tab has its own badge and justification fields.
  await page.getByRole("tab", { name: "One student" }).click();
  const form = page.getByRole("region", { name: "Award a badge to one student" });
  await form.getByRole("combobox", { name: "Badge" }).click();
  await page.getByRole("option", { name: "Seminar Participation" }).first().click();
  // The student picker is searched by typing part of the name.
  await form.getByRole("combobox", { name: "Student" }).fill(target.slice(0, 4));
  await page.getByRole("option", { name: target }).first().click();
  await form.getByLabel(/Justification/).fill("Contributed to six of eight seminars, observed by the tutor.");
  await form.getByRole("button", { name: /Award/ }).last().click();
  // Scoped to the form: the hidden "Waiting to confirm" tab also mentions assignments by name.
  await expect(form.getByText(/awarded|issued|recorded/i).first()).toBeVisible();
  await eventually(async () => {
    const a = (await achievementsOf(page, target)).find((x) => x.title === "Seminar Participation");
    return a?.credential_id;
  }, "the manual award to be issued");
  const admin = await Api.as(page.request, STAFF.admin);
  const audit = await admin.get<{ items: { action: string }[] }>("/api/v1/admin/audit?limit=50");
  expect(audit.items.some((e) => e.action === "award.manual")).toBeTruthy();
});

test("E6 student export: the downloaded file is OB 3.0 with a verifiable proof", async ({ page }) => {
  await signIn(page, state.student!);
  await page.goto("/app/me/credentials");
  await page.getByRole("link", { name: new RegExp(TITLE) }).click();
  state.credentialId = page.url().split("/").pop();
  const json = await download(page, () => page.getByRole("button", { name: "Download credential file" }).click());
  state.downloaded = json;
  // The certificate is a PDF named after the badge. The badge is still private, so the page
  // says how to get a QR code on it.
  await expect(page.getByText(/turn on the public link below first/)).toBeVisible();
  const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download certificate (PDF)" }).click()]);
  expect(pdf.suggestedFilename()).toMatch(/-certificate\.pdf$/);
  expect(readFileSync((await pdf.path())!).subarray(0, 5).toString("latin1")).toBe("%PDF-");
  const vc = JSON.parse(json);
  expect(vc.type).toEqual(expect.arrayContaining(["VerifiableCredential", "OpenBadgeCredential"]));
  expect(vc["@context"]).toEqual(expect.arrayContaining(["https://www.w3.org/ns/credentials/v2"]));
  expect(vc.proof.cryptosuite ?? vc.proof[0]?.cryptosuite).toBe("eddsa-rdfc-2022");
  expect(vc.credentialSubject.achievement.name).toBe(TITLE);
  const r = await page.request.post("/api/v1/verify", { data: vc });
  const result = (await r.json()) as { result: string; checks: { name: string; ok: boolean }[] };
  expect(result.result).toBe("verified");
  expect(result.checks.every((c) => c.ok)).toBeTruthy();
});

test("E7 external verification: someone with no account checks the file", async ({ page }) => {
  const text = await verifyFileAnonymously(page, state.downloaded!);
  expect(text).toMatch(/valid|verified/i);
  expect(text).not.toMatch(/revoked|invalid|not valid/i);
});

test("E11 LinkedIn: certification details and a working public URL", async ({ page, browser }) => {
  await signIn(page, state.student!);
  await page.goto(`/app/me/credentials/${state.credentialId}`);
  await page.getByRole("button", { name: "Turn on public link" }).click();
  const panel = page.getByRole("region", { name: "Add to LinkedIn" });
  const add = panel.getByRole("link", { name: /LinkedIn's Add certification form/ });
  await expect(add).toBeVisible();
  const href = new URL((await add.getAttribute("href"))!);
  expect(href.hostname).toBe("www.linkedin.com");
  expect(href.searchParams.get("name")).toBe(TITLE);
  const certUrl = href.searchParams.get("certUrl")!;
  expect(certUrl).toMatch(/\/verify\/[A-Za-z0-9_-]{22}$/);
  // The URL works for someone with no account and does not show the learner's name.
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  const res = await p.goto(new URL(certUrl).pathname);
  expect(res!.status()).toBe(200);
  await expect(p.getByRole("heading", { level: 1 })).toContainText(TITLE);
  await expect(p.locator("body")).not.toContainText(state.student!);
  await ctx.close();
});

test("E8 revocation: an administrator revokes; the downloaded copy now verifies as revoked", async ({ page }) => {
  await signIn(page, STAFF.admin);
  await page.goto("/app/admin/credentials");
  await page.getByRole("button", { name: `Revoke ${TITLE} from ${state.student}` }).click();
  await choose(page, "Reason", /./);
  await page.getByLabel(/Explanation/).fill("Awarded in error during end-to-end testing.");
  await page.getByRole("button", { name: "Confirm revocation" }).click();
  await expect(page.getByRole("cell", { name: /^Revoked/ }).first()).toBeVisible();
  const text = await verifyFileAnonymously(page, state.downloaded!);
  expect(text).toMatch(/revoked/i);
});

test("E9 Canvas account closure: an exported credential stays verifiable without the account", async ({ page }) => {
  // Use another earner's credential (E8 revoked the first), then erase that person's account data.
  const name = state.earners!.find((n) => n !== state.student) ?? (await learners(page))[0].display_name;
  const stu = await Api.as(page.request, name);
  const creds = await stu.get<Credential[]>("/api/v1/learners/me/credentials");
  const active = creds.find((c) => c.status === "active")!;
  const exported = await (await stu.raw("GET", `/api/v1/credentials/${active.id}/export`)).text();
  // The learner's Canvas account disappears: their session no longer exists and the
  // institution erases their personal data. The file is checked by an outsider afterwards.
  const admin = await Api.as(page.request, STAFF.admin);
  const user = (await devUsers(page.request)).find((u) => u.display_name === name)!;
  const erase = await admin.raw("POST", `/api/v1/admin/people/${user.id}/erase`, { confirm: "ERASE" });
  expect([200, 202, 204]).toContain(erase.status());
  const text = await verifyFileAnonymously(page, exported);
  expect(text).toMatch(/valid|verified/i);
  expect(text).not.toMatch(/revoked|invalid/i);
});

test("E10 unauthorised access: another learner's credential is not disclosed", async ({ page }) => {
  const others = (await learners(page)).map((s) => s.display_name).filter((n) => n !== state.student);
  const intruder = others[others.length - 1];
  await signIn(page, intruder);
  await page.goto(`/app/me/credentials/${state.credentialId}`);
  await expect(page.getByText(/no such badge|not found/i).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(state.student!);
  const api = await Api.as(page.request, intruder);
  for (const path of [`/api/v1/credentials/${state.credentialId}`, `/api/v1/credentials/${state.credentialId}/export`]) {
    expect((await api.raw("GET", path)).status()).toBe(404);
  }
  expect((await api.raw("GET", "/api/v1/admin/credentials")).status()).toBe(403);
  // Institution B's records: covered against two real tenants by the backend suite
  // (test_scenario_10_unauthorized_access, test_security), as the dev stack seeds one.
});

test("E12 interrupted issuance: a signer outage, then recovery, gives exactly one credential", async ({ page }) => {
  const stop = process.env.OC_E2E_SIGNER_STOP;
  const start = process.env.OC_E2E_SIGNER_START;
  test.skip(!stop || !start, "set OC_E2E_SIGNER_STOP and OC_E2E_SIGNER_START to commands that stop/start the signer");
  const students = await learners(page);
  let target = "";
  for (const s of students) {
    const a = (await achievementsOf(page, s.display_name)).find((x) => x.title === "Seminar Participation");
    if (a && !a.credential_id) {
      target = s.display_name;
      break;
    }
  }
  const lec = await Api.as(page.request, STAFF.lecturer);
  const defs = (await lec.get<{ items: Achievement[] }>("/api/v1/achievements")).items;
  const def = defs.find((d) => d.title === "Seminar Participation")!;
  const user = students.find((s) => s.display_name === target)!;
  execSync(stop!, { stdio: "inherit" });
  try {
    await lec.post("/api/v1/awards/manual", {
      definition_id: def.id,
      user_id: user.id,
      justification: "Led two seminars; recorded during the interrupted-issuance test.",
    });
    await page.waitForTimeout(5_000); // the worker tries and fails while the signer is down
    const mine = (await achievementsOf(page, target)).find((x) => x.title === "Seminar Participation")!;
    expect(mine.credential_id).toBeNull();
  } finally {
    execSync(start!, { stdio: "inherit" });
  }
  // Recovery: the job retries (or an administrator retries it from "Failed issuance").
  const admin = await Api.as(page.request, STAFF.admin);
  await eventually(async () => {
    const jobs = await admin.get<{ items?: { id: string; status: string }[] } | { id: string; status: string }[]>(
      "/api/v1/admin/jobs",
    );
    const list = Array.isArray(jobs) ? jobs : (jobs.items ?? []);
    for (const j of list.filter((x) => x.status === "failed")) await admin.raw("POST", `/api/v1/admin/jobs/${j.id}/retry`);
    const a = (await achievementsOf(page, target)).find((x) => x.title === "Seminar Participation");
    return a?.credential_id;
  }, "issuance to recover", 90_000);
  const creds = await (await Api.as(page.request, target)).get<Credential[]>("/api/v1/learners/me/credentials");
  expect(creds.filter((c) => c.name === "Seminar Participation")).toHaveLength(1);
});
