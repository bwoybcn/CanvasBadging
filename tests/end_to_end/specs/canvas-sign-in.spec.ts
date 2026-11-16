// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Opening Badges the way Canvas does, in a real browser.
 *
 * The other specs sign in through the development sign-in page. These go through the real
 * sign-in: a course page posts Canvas's login request to Badges, Badges sends the browser to
 * Canvas's authorize address, Canvas posts a signed launch back, and Badges opens inside Canvas's
 * frame. "Canvas" here is the stand-in in canvas-standin.ts.
 *
 * Two addresses are used for the stand-in on purpose:
 *
 *  - a different site from Badges (127.0.0.1 against localhost). The browser then withholds the
 *    sign-in cookie inside the frame, as browsers do for a real Canvas on another domain, and
 *    Badges has to recognise the browser through Canvas's storage frame instead;
 *  - the same site as Badges, where the cookie is sent and is enough.
 *
 * Needs OC_E2E_OC: a command that runs `oc` for the stack under test, used once to register the
 * stand-in, for example `cd ../../backend && uv run oc`. The API must run on this machine, since
 * it fetches the stand-in's signing key from a local address.
 */
import { execSync } from "node:child_process";
import { randomInt, randomUUID } from "node:crypto";
import { join } from "node:path";
import { type Page, expect, test } from "@playwright/test";
import { type CourseInfo, type Person, type Registration, StandInCanvas } from "./canvas-standin";

const OC = process.env.OC_E2E_OC;
const TOOL = (process.env.OC_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
const PORT = Number(process.env.OC_E2E_CANVAS_PORT ?? 3210);
const INSTITUTION = "standin-canvas-e2e";

const toolHost = new URL(TOOL).hostname;
const otherHost = toolHost === "localhost" ? "127.0.0.1" : "localhost";
/** Canvas on another site: the usual case, and the one where the cookie is withheld. */
const OTHER_SITE: Registration = { origin: `http://${otherHost}:${PORT}`, clientId: "e2e-10000000000001", deploymentId: "1:e2e-other-site" };
/** Canvas on the same site as Badges: the cookie is sent. */
const SAME_SITE: Registration = { origin: `http://${toolHost}:${PORT}`, clientId: "e2e-10000000000002", deploymentId: "2:e2e-same-site" };

const TEACHER: Person = { sub: "e2e-sub-teacher", canvasUserId: "9001", name: "Tess Teacher", given: "Tess", family: "Teacher", email: "tess.teacher@standin.example", role: "Instructor" };
const STUDENT: Person = { sub: "e2e-sub-student", canvasUserId: "9002", name: "Sam Student", given: "Sam", family: "Student", email: "sam.student@standin.example", role: "Learner" };
const CLASSMATE: Person = { sub: "e2e-sub-classmate", canvasUserId: "9003", name: "Chris Classmate", given: "Chris", family: "Classmate", email: "chris.classmate@standin.example", role: "Learner" };

let canvas: StandInCanvas;

/** A course nobody has opened before, so each test starts from "not switched on yet". */
function newCourse(): CourseInfo {
  const id = randomUUID().slice(0, 8);
  return { contextId: `e2e-ctx-${id}`, canvasCourseId: String(randomInt(100_000, 999_999_999)), code: `E2E-${id}`, title: `Stand-in course ${id}` };
}

/** The sign-in requests the browser makes to Badges, in order (paths only). */
function watchSignIn(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.origin === TOOL && url.pathname.startsWith("/lti/")) seen.push(`${r.method()} ${url.pathname}`);
  });
  return seen;
}

/** The students Badges holds for a course, asked of its API with the session the frame was given. */
async function classNames(page: Page, course: CourseInfo): Promise<string[]> {
  const token = await page.frame({ name: "tool_content" })!.evaluate(() => window.sessionStorage.getItem("oc.session"));
  const headers = { authorization: `Bearer ${token}` };
  const courses = (await (await page.request.get(`${TOOL}/api/v1/courses`, { headers })).json()) as { id: string; title: string }[];
  const mine = courses.find((c) => c.title === course.title);
  if (!mine) return [];
  const progress = (await (await page.request.get(`${TOOL}/api/v1/courses/${mine.id}/progress`, { headers })).json()) as { learners?: { name: string | null }[] };
  return (progress.learners ?? []).map((l) => l.name ?? "").sort();
}

function register(reg: Registration): void {
  const args = [
    "canvas register",
    `--institution ${INSTITUTION}`,
    `--create-institution "Stand-in Canvas (end-to-end tests)"`,
    `--name "Stand-in Canvas"`,
    `--base-url ${reg.origin}`,
    `--issuer ${reg.origin}`,
    `--client-id ${reg.clientId}`,
    `--deployment-id ${reg.deploymentId}`,
  ].join(" ");
  execSync(`${OC} ${args}`, { stdio: "inherit" });
}

test.describe("opening Badges from Canvas", () => {
  // Skipped on a developer's machine when no command is given. The automatic checks (CI) must
  // never skip them quietly, so there a missing command fails instead.
  test.skip(!OC && !process.env.CI, "set OC_E2E_OC to a command that runs `oc` for the stack under test, for example: cd ../../backend && uv run oc");

  test.beforeAll(async ({}, testInfo) => {
    if (!OC) throw new Error("OC_E2E_OC is not set, so the Canvas sign-in tests cannot register their stand-in Canvas");
    register(OTHER_SITE);
    register(SAME_SITE);
    canvas = new StandInCanvas(TOOL, PORT, join(testInfo.project.testDir, "..", ".cache", "canvas-standin-key.json"));
    await canvas.start();
  });

  test.afterAll(async () => {
    await canvas?.stop();
  });

  test("a lecturer opens Badges inside Canvas's frame, switches the course on and sees the class", async ({ page }) => {
    const course = newCourse();
    canvas.enrol(course, [TEACHER, STUDENT, CLASSMATE]);
    const signIn = watchSignIn(page);

    await page.goto(canvas.coursePage(OTHER_SITE, TEACHER, course, "frame"));
    const badges = page.frameLocator('iframe[name="tool_content"]');

    // Signed in as the person and into the course that Canvas named.
    await expect(badges.getByRole("heading", { name: course.title })).toBeVisible();
    await expect(badges.getByText(`Canvas course ${course.canvasCourseId}`)).toContainText("Your role: Course staff");
    // Canvas is another site, so the cookie was withheld and its storage frame was used instead.
    expect(signIn).toEqual(["POST /lti/login", "POST /lti/launch", "POST /lti/verify"]);
    // Badges stayed inside the frame: the page in the address bar is still the course in Canvas.
    expect(new URL(page.url()).origin).toBe(OTHER_SITE.origin);

    await badges.getByRole("button", { name: "Switch on badges for this course" }).click();
    await expect(badges.getByRole("button", { name: "Switch on badges for this course" })).toHaveCount(0);

    // Switching on reads the class list from Canvas, with a token Canvas issued to Badges, and
    // the two students Canvas named are now in the course (the lecturer is not a student).
    await expect.poll(() => classNames(page, course), { timeout: 45_000 }).toEqual(["Chris Classmate", "Sam Student"]);
    expect(canvas.requests).toContain(`GET /api/lti/courses/${course.canvasCourseId}/names_and_roles`);
  });

  test("a student opens Badges in a course that is not switched on yet", async ({ page }) => {
    const course = newCourse();
    const signIn = watchSignIn(page);

    await page.goto(canvas.coursePage(OTHER_SITE, STUDENT, course, "frame"));
    const badges = page.frameLocator('iframe[name="tool_content"]');

    await expect(badges.getByRole("heading", { name: course.title })).toBeVisible();
    await expect(badges.getByText(`Canvas course ${course.canvasCourseId}`)).toContainText("Your role: Student");
    await expect(badges.getByText("Course staff have not switched on badges for this course yet.")).toBeVisible();
    // A student is never offered the staff's switch.
    await expect(badges.getByRole("button", { name: "Switch on badges for this course" })).toHaveCount(0);
    expect(signIn).toContain("POST /lti/verify");
  });

  test("Badges opened in a tab of its own signs in with the cookie alone", async ({ page }) => {
    const course = newCourse();
    const signIn = watchSignIn(page);

    await page.goto(canvas.coursePage(SAME_SITE, TEACHER, course, "tab"));

    await expect(page.getByRole("heading", { name: course.title })).toBeVisible();
    expect(new URL(page.url()).origin).toBe(TOOL);
    // The session arrives in the address and is removed from it at once.
    expect(page.url()).not.toContain("session=");
    expect(signIn).toEqual(["POST /lti/login", "POST /lti/launch"]);
  });

  test("a launch signed with a key that is not Canvas's is refused", async ({ page }) => {
    await page.goto(canvas.coursePage(OTHER_SITE, TEACHER, newCourse(), "frame", "wrong-key"));
    const badges = page.frameLocator('iframe[name="tool_content"]');

    await expect(badges.getByRole("heading", { name: "Badges could not open" })).toBeVisible();
    await expect(badges.getByText("Error code: SIGNATURE_INVALID.")).toBeVisible();
  });

  test("a launch from a Canvas installation that no administrator approved is refused", async ({ page }) => {
    await page.goto(canvas.coursePage(OTHER_SITE, TEACHER, newCourse(), "frame", "unapproved-deployment"));
    const badges = page.frameLocator('iframe[name="tool_content"]');

    await expect(badges.getByRole("heading", { name: "Badges could not open" })).toBeVisible();
    await expect(badges.getByText("Error code: DEPLOYMENT_UNKNOWN.")).toBeVisible();
  });
});
