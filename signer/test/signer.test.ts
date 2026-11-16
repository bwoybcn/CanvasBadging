// SPDX-License-Identifier: AGPL-3.0-or-later
import { connect, type AddressInfo } from "node:net";

import { describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";
import { DEV_KEK_B64, DEV_SHARED_SECRET, loadConfig } from "../src/config.js";
import { decrypt, encrypt } from "../src/envelope.js";
import { generateDidKey } from "../src/keys.js";
import { MemoryStore } from "./helpers.js";


const config = loadConfig({ OC_ENV: "test" });
const auth = { authorization: `Bearer ${DEV_SHARED_SECRET}` };
const KEY_ID = "0190f3a2-7b1c-7d2e-8f00-123456789abc";

describe("key generation", () => {
  it("produces an Ed25519 multikey in did:key form", async () => {
    const key = await generateDidKey();
    expect(key.publicKeyMultibase).toMatch(/^z6Mk/); // multicodec ed25519-pub, base58btc
    expect(key.did).toBe(`did:key:${key.publicKeyMultibase}`);
    expect(key.verificationMethodId).toBe(`${key.did}#${key.publicKeyMultibase}`);
    expect(key.secretKeyMultibase).toMatch(/^z/);
  });
});

describe("envelope encryption", () => {
  it("round-trips and binds ciphertext to the key id", () => {
    const kek = Buffer.from(DEV_KEK_B64, "base64");
    const env = encrypt(kek, "zSecret", KEY_ID);
    expect(env.ciphertext.includes(Buffer.from("zSecret"))).toBe(false);
    expect(decrypt(kek, env, KEY_ID)).toBe("zSecret");
    expect(() => decrypt(kek, env, "another-key-id")).toThrow();
  });
});

describe("config", () => {
  it("refuses committed development secrets in production", () => {
    expect(() => loadConfig({ OC_ENV: "production" })).toThrow(/Refusing to start in production/);
  });
  it("never guesses its mode", () => {
    // Unset or mistyped used to mean development, which accepts the committed secrets.
    expect(() => loadConfig({})).toThrow(/OC_ENV must be set/);
    for (const bad of ["prod", "Production", "", "live"]) {
      expect(() => loadConfig({ OC_ENV: bad })).toThrow(/OC_ENV must be set/);
    }
    expect(loadConfig({ OC_ENV: "development" }).kekRef).toBe("dev:committed");
  });
  it("accepts real secrets in production", () => {
    const kek = Buffer.alloc(32, 7).toString("base64");
    const c = loadConfig({ OC_ENV: "production", SIGNER_KEK: kek, OC_SIGNER_SHARED_SECRET: "x".repeat(40) });
    expect(c.kekRef).toBe("env:SIGNER_KEK");
  });
});

describe("HTTP API", () => {
  it("refuses to sign in production with a key wrapped by the development KEK", async () => {
    // Such a key exists when a signer once ran without its own SIGNER_KEK. It was not marked
    // as a development key, so only the way it was wrapped gives it away.
    const store = new MemoryStore();
    const key = await generateDidKey();
    const wrapped = encrypt(Buffer.from(DEV_KEK_B64, "base64"), key.secretKeyMultibase, KEY_ID);
    await store.insert({ issuerKeyId: KEY_ID, ...wrapped, kekRef: "dev:committed", isDev: false });
    expect(await store.devKeysPresent()).toBe(true);
    const secret = "x".repeat(40);
    const prod = loadConfig({
      OC_ENV: "production",
      SIGNER_KEK: Buffer.alloc(32, 7).toString("base64"),
      OC_SIGNER_SHARED_SECRET: secret,
    });
    const res = await buildApp(prod, store).inject({
      method: "POST",
      url: "/v1/sign",
      headers: { authorization: `Bearer ${secret}` },
      payload: { issuer_key_id: KEY_ID, verification_method_id: key.verificationMethodId, document: {} },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json().code).toBe("DEV_KEY_FORBIDDEN");
  });

  it("answers health checks without auth", async () => {
    const app = buildApp(config, new MemoryStore());
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(200);
  });

  it("requires the shared secret", async () => {
    const app = buildApp(config, new MemoryStore());
    const res = await app.inject({ method: "POST", url: "/v1/keys", payload: { issuer_key_id: KEY_ID } });
    expect(res.statusCode).toBe(401);
  });

  it.each([
    ["percent-encoded prefix", "/%761/keys"],
    ["percent-encoded digit", "/v%31/keys"],
  ])("requires the shared secret whatever the path spelling (%s)", async (_name, url) => {
    const store = new MemoryStore();
    const app = buildApp(config, store);
    const res = await app.inject({ method: "POST", url, payload: { issuer_key_id: KEY_ID } });
    expect(res.statusCode).toBe(401);
    expect(store.rows.size).toBe(0);
  });

  it("requires the shared secret for an absolute-form request target on a real socket", async () => {
    const store = new MemoryStore();
    const app = buildApp(config, store);
    await app.listen({ port: 0, host: "127.0.0.1" });
    try {
      const { port } = app.server.address() as AddressInfo;
      const body = JSON.stringify({ issuer_key_id: KEY_ID });
      const raw = await new Promise<string>((resolve, reject) => {
        const sock = connect(port, "127.0.0.1", () => {
          sock.write(
            `POST http://signer:8790/v1/keys HTTP/1.1\r\nHost: signer\r\nContent-Type: application/json\r\n` +
              `Content-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`,
          );
        });
        let out = "";
        sock.on("data", (d) => (out += d.toString()));
        sock.on("end", () => resolve(out));
        sock.on("error", reject);
      });
      expect(raw.split("\r\n")[0]).toContain(" 401 ");
      expect(store.rows.size).toBe(0);
    } finally {
      await app.close();
    }
  });

  it("requires the shared secret on encoded destroy and sign paths", async () => {
    const app = buildApp(config, new MemoryStore());
    for (const url of [`/%76%31/keys/${KEY_ID}/destroy`, "/%761/sign"]) {
      const res = await app.inject({ method: "POST", url, payload: {} });
      expect(res.statusCode).toBe(401);
    }
  });

  it("generates and stores an encrypted key, never returning the secret", async () => {
    const store = new MemoryStore();
    const app = buildApp(config, store);
    const res = await app.inject({
      method: "POST",
      url: "/v1/keys",
      headers: auth,
      payload: { issuer_key_id: KEY_ID, dev: true },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.did).toMatch(/^did:key:z6Mk/);
    expect(JSON.stringify(body)).not.toMatch(/secret/i);
    const row = store.rows.get(KEY_ID)!;
    expect(row.isDev).toBe(true);
    expect(row.kekRef).toBe("dev:committed");
    const again = await app.inject({ method: "POST", url: "/v1/keys", headers: auth, payload: { issuer_key_id: KEY_ID } });
    expect(again.statusCode).toBe(409);
  });

  it("validates sign requests", async () => {
    const app = buildApp(config, new MemoryStore());
    const res = await app.inject({ method: "POST", url: "/v1/sign", headers: auth, payload: {} });
    expect(res.statusCode).toBe(422);
  });
});
