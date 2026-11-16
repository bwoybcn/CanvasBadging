// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A stand-in for Canvas, just enough of it to open Badges the way Canvas does (LTI 1.3).
 *
 * It does the four things Canvas does when someone chooses Badges in a course menu:
 *
 *   1. shows a course page with the tool in a frame, and posts the "login" request to the tool;
 *   2. answers the tool's redirect to its authorize address with a signed launch (an id_token),
 *      sent back to the tool as a form post;
 *   3. publishes the public half of its signing key, so the tool can check that signature;
 *   4. keeps a small value for the tool in the browser (Canvas's "platform storage" frame), which
 *      is how the tool recognises the same browser when its cookie is blocked inside a frame.
 *
 * It also serves the class list (LTI Names and Roles), so switching a course on has something
 * to read. It is not Canvas: it proves the browser side of the sign-in, not Canvas's own code.
 */
import { type JsonWebKey, type KeyObject, createHash, createPrivateKey, createPublicKey, createSign, generateKeyPairSync, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { type IncomingMessage, type Server, type ServerResponse, createServer } from "node:http";
import { dirname } from "node:path";

const ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#";
const LTI = "https://purl.imsglobal.org/spec/lti/claim/";

export interface Person {
  sub: string;
  canvasUserId: string;
  name: string;
  given: string;
  family: string;
  email: string;
  role: "Instructor" | "Learner";
}

export interface CourseInfo {
  /** The opaque LTI context id. */
  contextId: string;
  /** Canvas's own course number. */
  canvasCourseId: string;
  code: string;
  title: string;
}

export interface Registration {
  /** The address people (and the tool) use for this Canvas, for example http://127.0.0.1:3210 */
  origin: string;
  clientId: string;
  deploymentId: string;
}

/** What should go wrong with a launch, for the refusal tests. */
export type Fault = "none" | "wrong-key" | "unapproved-deployment";

interface PendingLaunch {
  registration: Registration;
  person: Person;
  course: CourseInfo;
  fault: Fault;
}

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}

function b64url(data: Buffer | string): string {
  return Buffer.from(data).toString("base64url");
}

function esc(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

function newKey(): { privateKey: KeyObject; jwk: JsonWebKey } {
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  return { privateKey, jwk: publicKey.export({ format: "jwk" }) };
}

/**
 * The stand-in's signing key. The tool remembers a Canvas's keys for an hour, so the key is kept
 * in a file (ignored by Git) and reused: a second run against the same stack still signs with a
 * key the tool knows.
 */
function loadOrCreateKey(file: string): { privateKey: KeyObject; jwk: JsonWebKey; kid: string } {
  if (existsSync(file)) {
    const saved = JSON.parse(readFileSync(file, "utf8")) as { kid: string; pem: string };
    const privateKey = createPrivateKey(saved.pem);
    return { privateKey, jwk: createPublicKey(privateKey).export({ format: "jwk" }), kid: saved.kid };
  }
  const { privateKey, jwk } = newKey();
  const kid = `standin-${randomUUID()}`;
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify({ kid, pem: privateKey.export({ type: "pkcs8", format: "pem" }) }), { mode: 0o600 });
  return { privateKey, jwk, kid };
}

export class StandInCanvas {
  private server: Server | null = null;
  private readonly key: { privateKey: KeyObject; jwk: JsonWebKey; kid: string };
  /** The token for the class list. It goes with the key, because the tool keeps a token it was
   * given for up to an hour: a second run must still accept the one the first run issued. */
  private readonly serviceToken: string;
  private readonly pending = new Map<string, PendingLaunch>();
  private readonly rosters = new Map<string, Person[]>();
  /** Every path asked of the stand-in, for tests that check what the tool fetched. */
  readonly requests: string[] = [];

  constructor(
    /** The tool's address, for example http://localhost:8000 */
    readonly tool: string,
    readonly port: number,
    keyFile: string,
  ) {
    this.key = loadOrCreateKey(keyFile);
    const pem = this.key.privateKey.export({ type: "pkcs8", format: "pem" });
    this.serviceToken = createHash("sha256").update(`service-token:${pem}`).digest("base64url");
  }

  async start(): Promise<void> {
    this.server = createServer((req, res) => {
      this.handle(req, res).catch((err: unknown) => {
        res.writeHead(500, { "content-type": "text/plain" }).end(String(err));
      });
    });
    await new Promise<void>((resolve, reject) => {
      this.server!.once("error", reject);
      // No host: listen on every local address, so both "localhost" and "127.0.0.1" reach it.
      this.server!.listen(this.port, resolve);
    });
  }

  async stop(): Promise<void> {
    if (!this.server) return;
    this.server.closeAllConnections();
    await new Promise<void>((resolve) => this.server!.close(() => resolve()));
    this.server = null;
  }

  /** Who is in a course, as the class list will report it. */
  enrol(course: CourseInfo, people: Person[]): void {
    this.rosters.set(course.canvasCourseId, people);
  }

  /**
   * The address of a course page with Badges open in it, as this person. `where` is "frame" for
   * the usual course-menu placement, or "tab" for a tool Canvas opens in a tab of its own.
   */
  coursePage(registration: Registration, person: Person, course: CourseInfo, where: "frame" | "tab", fault: Fault = "none"): string {
    const hint = randomUUID();
    this.pending.set(hint, { registration, person, course, fault });
    return `${registration.origin}/courses/${course.canvasCourseId}/external_tools/1?hint=${hint}&where=${where}`;
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", `http://${req.headers.host}`);
    this.requests.push(`${req.method} ${url.pathname}`);
    const html = (body: string) => res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" }).end(body);
    const json = (body: unknown, status = 200) => res.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(body));

    if (url.pathname === "/api/lti/security/jwks") {
      return void json({ keys: [{ ...this.key.jwk, kid: this.key.kid, alg: "RS256", use: "sig" }] });
    }
    if (url.pathname === "/post_message_forwarding") return void html(STORAGE_FRAME);
    if (/^\/courses\/[^/]+\/external_tools\/1$/.test(url.pathname)) {
      const launch = this.pending.get(url.searchParams.get("hint") ?? "");
      if (!launch) return void json({ error: "unknown launch" }, 404);
      return void html(this.coursePageHtml(url.searchParams.get("hint")!, launch, url.searchParams.get("where") === "tab"));
    }
    if (url.pathname === "/api/lti/authorize_redirect") return void this.authorize(url, res);
    if (url.pathname === "/login/oauth2/token" && req.method === "POST") {
      // Canvas issues a service token to a tool that proves who it is with a signed assertion.
      const form = new URLSearchParams(await readBody(req));
      if (form.get("grant_type") !== "client_credentials" || !form.get("client_assertion")) {
        return void json({ error: "invalid_request" }, 400);
      }
      return void json({ access_token: this.serviceToken, token_type: "Bearer", expires_in: 3600, scope: form.get("scope") ?? "" });
    }
    const roster = /^\/api\/lti\/courses\/([^/]+)\/names_and_roles$/.exec(url.pathname);
    if (roster) {
      // The class list is only given to a caller holding the token issued above.
      if (req.headers.authorization !== `Bearer ${this.serviceToken}`) return void json({ error: "unauthorized" }, 401);
      const origin = `http://${req.headers.host}`;
      const people = this.rosters.get(roster[1]) ?? [];
      res.writeHead(200, { "content-type": "application/vnd.ims.lti-nrps.v2.membershipcontainer+json" });
      return void res.end(
        JSON.stringify({
          id: `${origin}${url.pathname}`,
          context: { id: roster[1] },
          members: people.map((p) => ({
            status: "Active",
            user_id: p.sub,
            name: p.name,
            given_name: p.given,
            family_name: p.family,
            email: p.email,
            roles: [ROLE + p.role],
          })),
        }),
      );
    }
    json({ error: "not found" }, 404);
  }

  /** Step 1: the course page. It posts Canvas's "login" request to the tool. */
  private coursePageHtml(hint: string, launch: PendingLaunch, inTab: boolean): string {
    const { registration, course } = launch;
    const fields: Record<string, string> = {
      iss: registration.origin,
      login_hint: hint,
      client_id: registration.clientId,
      lti_deployment_id: registration.deploymentId,
      target_link_uri: `${this.tool}/lti/launch`,
      lti_message_hint: hint,
    };
    // Canvas offers its storage frame only when the tool is shown inside a frame.
    if (!inTab) fields.lti_storage_target = "post_message_forwarding";
    const inputs = Object.entries(fields)
      .map(([k, v]) => `<input type="hidden" name="${esc(k)}" value="${esc(v)}">`)
      .join("");
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(course.title)}</title></head>
<body><h1>${esc(course.title)}</h1>
<form id="launch" method="post" action="${esc(this.tool)}/lti/login" target="${inTab ? "_self" : "tool_content"}">${inputs}</form>
${inTab ? "" : '<iframe name="tool_content" title="Badges" style="width:100%;height:900px;border:0"></iframe>'}
<iframe name="post_message_forwarding" title="post_message_forwarding" src="/post_message_forwarding" hidden></iframe>
<script>
  // Canvas has its storage frame ready before the tool loads.
  document.querySelector('iframe[name="post_message_forwarding"]').addEventListener(
    "load", function () { document.getElementById("launch").submit(); }, { once: true });
</script></body></html>`;
  }

  /** Step 2: the tool sent the browser back here; answer with a signed launch as a form post. */
  private authorize(url: URL, res: ServerResponse): void {
    const q = url.searchParams;
    const launch = this.pending.get(q.get("login_hint") ?? "");
    const redirect = q.get("redirect_uri") ?? "";
    const fail = (why: string) => res.writeHead(400, { "content-type": "text/plain" }).end(why);
    if (!launch) return void fail("unknown login_hint");
    if (q.get("client_id") !== launch.registration.clientId) return void fail("wrong client_id");
    if (redirect !== `${this.tool}/lti/launch`) return void fail("redirect_uri is not a registered address");
    if (q.get("response_type") !== "id_token" || q.get("response_mode") !== "form_post") return void fail("unsupported response");
    if (!q.get("nonce") || !q.get("state")) return void fail("nonce and state are required");

    const idToken = this.sign(this.claims(launch, q.get("nonce")!), launch.fault);
    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" }).end(
      `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Opening Badges</title></head><body>
<form id="f" method="post" action="${esc(redirect)}">
<input type="hidden" name="id_token" value="${esc(idToken)}">
<input type="hidden" name="state" value="${esc(q.get("state")!)}">
</form><script>document.getElementById("f").submit();</script></body></html>`,
    );
  }

  private claims(launch: PendingLaunch, nonce: string): Record<string, unknown> {
    const { registration, person, course, fault } = launch;
    const now = Math.floor(Date.now() / 1000);
    return {
      iss: registration.origin,
      aud: registration.clientId,
      azp: registration.clientId,
      sub: person.sub,
      iat: now,
      exp: now + 3600,
      nonce,
      name: person.name,
      given_name: person.given,
      family_name: person.family,
      email: person.email,
      [`${LTI}message_type`]: "LtiResourceLinkRequest",
      [`${LTI}version`]: "1.3.0",
      [`${LTI}deployment_id`]: fault === "unapproved-deployment" ? "99:not-approved" : registration.deploymentId,
      [`${LTI}target_link_uri`]: `${this.tool}/lti/launch`,
      [`${LTI}resource_link`]: { id: `rl-${course.contextId}`, title: "Badges" },
      [`${LTI}roles`]: [ROLE + person.role],
      [`${LTI}context`]: {
        id: course.contextId,
        label: course.code,
        title: course.title,
        type: ["http://purl.imsglobal.org/vocab/lis/v2/course#CourseOffering"],
      },
      [`${LTI}custom`]: { canvas_course_id: course.canvasCourseId, canvas_user_id: person.canvasUserId },
      "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice": {
        context_memberships_url: `${registration.origin}/api/lti/courses/${course.canvasCourseId}/names_and_roles`,
        service_versions: ["2.0"],
      },
    };
  }

  private sign(claims: Record<string, unknown>, fault: Fault): string {
    // A forged launch names the real key but is signed with another one.
    const key = fault === "wrong-key" ? newKey().privateKey : this.key.privateKey;
    const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT", kid: this.key.kid }));
    const body = b64url(JSON.stringify(claims));
    const signature = createSign("RSA-SHA256").update(`${head}.${body}`).sign(key);
    return `${head}.${body}.${b64url(signature)}`;
  }
}

/**
 * Step 4: Canvas's storage frame. A tool in a neighbouring frame asks it to keep a value
 * (lti.put_data) and later to give it back (lti.get_data); values are kept per asking site.
 */
const STORAGE_FRAME = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>post_message_forwarding</title></head><body><script>
  var kept = {};
  window.addEventListener("message", function (ev) {
    var d = ev.data || {};
    if (!d.message_id || !ev.source) return;
    var slot = ev.origin + "|" + d.key;
    if (d.subject === "lti.put_data") {
      kept[slot] = d.value;
      ev.source.postMessage({ subject: "lti.put_data.response", message_id: d.message_id, key: d.key, value: d.value }, ev.origin);
    } else if (d.subject === "lti.get_data") {
      ev.source.postMessage({ subject: "lti.get_data.response", message_id: d.message_id, key: d.key, value: kept[slot] }, ev.origin);
    }
  });
</script></body></html>`;
