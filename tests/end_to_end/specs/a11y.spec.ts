// SPDX-License-Identifier: AGPL-3.0-or-later
// Accessibility checks for spec §14.2 / §19.5 (RTM A-AXE-01, A-KBD-01, A-ZOOM-01, A-MOTION-01,
// A-MOBILE-01). axe-core runs with the WCAG 2.0/2.1/2.2 A and AA rule sets on every screen of
// every role, at desktop size and (project "mobile") on a phone viewport. Results are written to
// results/a11y-<project>.json, which docs/reports/accessibility.md summarises.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

import { Api, type Credential, STAFF, devUsers, signIn } from "./helpers";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

interface Screen {
  who: string;
  path: string;
  ready: string; // text that proves the screen finished loading
}

const findings: Record<string, unknown[]> = {};

async function audit(page: Page, label: string) {
  // let InstUI's fade-in transitions finish: axe would otherwise measure half-faded text
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  findings[label] = result.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.map((n) => n.target.join(" ")).slice(0, 5),
  }));
  return result.violations;
}



let screens: Screen[] = [];

test.beforeAll(async ({ request }) => {
  const users = await devUsers(request);
  const lec = await Api.as(request, STAFF.lecturer);
  const badges = (await lec.get<{ items: { id: string; course_id: string }[] }>("/api/v1/achievements")).items;
  const course = badges[0].course_id;
  // Seeded students share a family name, so list order is arbitrary: take one who holds a
  // credential, since the credential detail screen is part of the pass.
  let student = "";
  let creds: Credential[] = [];
  for (const u of users.filter((x) => x.roles.includes("student"))) {
    const held = await (await Api.as(request, u.display_name)).get<Credential[]>("/api/v1/learners/me/credentials");
    if (held.length) {
      student = u.display_name;
      creds = held;
      break;
    }
  }
  expect(student, "a student holding a credential").not.toBe("");
  screens = [
    { who: student, path: "/app/", ready: "Welcome" },
    { who: student, path: "/app/me/progress", ready: "" },
    { who: student, path: "/app/me/credentials", ready: "badge" },
    { who: student, path: `/app/me/credentials/${creds[0].id}`, ready: creds[0].name },
    { who: student, path: "/app/me/keeping", ready: "" },
    { who: student, path: "/app/help", ready: "Who to ask" },
    { who: STAFF.lecturer, path: "/app/", ready: "Welcome" },
    { who: STAFF.lecturer, path: "/app/badges", ready: "Academic Writing Foundations" },
    { who: STAFF.lecturer, path: "/app/badges/new", ready: "" },
    { who: STAFF.lecturer, path: `/app/badges/${badges[0].id}`, ready: "" },
    { who: STAFF.lecturer, path: "/app/awards", ready: "" },
    { who: STAFF.lecturer, path: "/app/awards?tab=student", ready: "Award a badge to one student" },
    { who: STAFF.lecturer, path: "/app/awards?tab=list", ready: "Award a badge to a list of students" },
    { who: STAFF.lecturer, path: `/app/courses/${course}/progress`, ready: "" },
    { who: STAFF.reviewer, path: "/app/reviews", ready: "" },
    { who: STAFF.lecturer, path: "/app/help", ready: "Who to ask" },
    ...[
      "",
      "/institution",
      "/policy",
      "/issuers",
      "/areas",
      "/courses",
      "/roles",
      "/review",
      "/templates",
      "/credentials",
      "/reports",
      "/audit",
      "/privacy",
      "/reconciliation",
    ].map((p) => ({ who: STAFF.admin, path: `/app/admin${p}`, ready: "" })),
  ];
});

/** Words the screens no longer use. */
const OLD_WORDS = /\blearners?\b|\bmicro-credentials?\b/i;
/** Other people's product names that happen to contain one. */
const KEPT_NAMES = /Learner Credential Wallet/g;

test("every signed-in screen passes axe (WCAG 2.2 A/AA rules)", async ({ page }, info) => {
  let current = "";
  const failures: string[] = [];
  const wording: string[] = [];
  for (const s of screens) {
    if (s.who !== current) {
      await signIn(page, s.who);
      current = s.who;
    }
    await page.goto(s.path);
    await page.waitForLoadState("networkidle");
    if (s.ready) await expect(page.getByText(s.ready, { exact: false }).first()).toBeVisible();
    const v = await audit(page, `${s.who} ${s.path}`);
    if (v.length) failures.push(`${s.path} (${s.who}): ${v.map((x) => x.id).join(", ")}`);
    // One vocabulary: staff and students read "student" and "badge" on every screen.
    const words = (await page.locator("body").innerText()).replaceAll(KEPT_NAMES, "").match(OLD_WORDS);
    if (words) wording.push(`${s.path} (${s.who}): "${words[0]}"`);
  }
  expect(wording, `screens still say "learner" or "micro-credential":\n${wording.join("\n")}`).toEqual([]);
  // public pages: no account at all, including a page a student chose to share
  const stu = await Api.as(page.request, screens[0].who);
  const creds = await stu.get<Credential[]>("/api/v1/learners/me/credentials");
  const share = await stu.raw("PUT", `/api/v1/credentials/${creds[0].id}/share`, {});
  const shareUrl = new URL(((await share.json()) as { share: { url: string } }).share.url);
  await page.evaluate(() => sessionStorage.clear());
  for (const path of ["/verify", "/app/dev-login", shareUrl.pathname]) {
    await page.goto(path);
    const v = await audit(page, `public ${path}`);
    if (v.length) failures.push(`${path}: ${v.map((x) => x.id).join(", ")}`);
  }
  mkdirSync("results", { recursive: true });
  writeFileSync(`results/a11y-${info.project.name}.json`, JSON.stringify(findings, null, 2));
  expect(failures, failures.join("\n")).toEqual([]);
});

test("keyboard: skip link first, every navigation item reachable, focus visible", async ({ page }) => {
  await signIn(page, STAFF.admin);
  await page.goto("/app/admin");
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("Tab");
  const first = page.locator(":focus");
  await expect(first).toHaveText("Skip to main content");
  await expect(first).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main-content$/);
  // Tab order from the top reaches every navigation link, and each shows a focus outline
  await page.goto("/app/admin");
  await page.waitForLoadState("networkidle");
  const names = await page.getByRole("navigation", { name: "OpenCredential" }).getByRole("link").allInnerTexts();
  const reached: string[] = [];
  for (let i = 0; i < names.length + 1; i++) {
    await page.keyboard.press("Tab");
    const el = page.locator(":focus");
    const outline = await el.evaluate((e) => {
      const st = getComputedStyle(e);
      return `${st.outlineStyle} ${st.outlineWidth} ${st.boxShadow}`;
    });
    expect(outline, "focused element must show a focus indicator").not.toMatch(/^none 0px none$/);
    reached.push((await el.innerText()).trim());
  }
  for (const n of names) expect(reached).toContain(n.trim());
});

test("screen-reader structure: landmarks, one h1, navigation exposed as links", async ({ page }) => {
  await signIn(page, STAFF.admin);
  for (const path of ["/app/", "/app/badges", "/app/admin/credentials"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "OpenCredential" })).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    const nav = page.getByRole("navigation", { name: "OpenCredential" });
    await expect(nav.getByRole("button")).toHaveCount(0);
    expect(await nav.getByRole("link").count()).toBeGreaterThan(1);
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  }
});

test("400% zoom / 320px reflow: no horizontal scrolling on any screen", async ({ page }) => {
  // WCAG 1.4.10: 1280px at 400% zoom is a 320 CSS pixel viewport.
  await page.setViewportSize({ width: 320, height: 640 });
  const bad: string[] = [];
  let current = "";
  for (const s of screens) {
    if (s.who !== current) {
      await signIn(page, s.who);
      current = s.who;
    }
    await page.goto(s.path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) {
      const culprit = await page.evaluate(() => {
        const W = window.innerWidth;
        const out: string[] = [];
        for (const el of Array.from(document.querySelectorAll("body *"))) {
          const r = el.getBoundingClientRect();
          const kids = Array.from(el.children).filter((k) => k.getBoundingClientRect().right > W + 1);
          if (r.right > W + 1 && kids.length === 0) out.push(`${el.tagName}[${el.getAttribute("data-cid") ?? ""}] "${(el.textContent ?? "").slice(0, 30)}"`);
        }
        return out.slice(0, 3).join("; ");
      });
      bad.push(`${s.path}: ${overflow}px too wide (${culprit})`);
    }
  }
  for (const path of ["/verify"]) {
    await page.goto(path);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) bad.push(`${path}: ${overflow}px too wide`);
  }
  expect(bad, bad.join("\n")).toEqual([]);
});

test("reduced motion: transitions and animations are switched off", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await signIn(page, STAFF.lecturer);
  await page.goto("/app/badges");
  await page.waitForLoadState("networkidle");
  const longest = await page.evaluate(() => {
    let max = 0;
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const st = getComputedStyle(el);
      for (const d of [...st.transitionDuration.split(","), ...st.animationDuration.split(",")]) {
        const ms = d.trim().endsWith("ms") ? parseFloat(d) : parseFloat(d) * 1000;
        if (ms > max) max = ms;
      }
    }
    return max;
  });
  expect(longest).toBeLessThan(1);
  await ctx.close();
});
