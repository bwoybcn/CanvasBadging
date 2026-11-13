// SPDX-License-Identifier: AGPL-3.0-or-later
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
  it("accepts real secrets in production", () => {
    const kek = Buffer.alloc(32, 7).toString("base64");
    const c = loadConfig({ OC_ENV: "production", SIGNER_KEK: kek, OC_SIGNER_SHARED_SECRET: "x".repeat(40) });
    expect(c.kekRef).toBe("env:SIGNER_KEK");
  });
});

describe("HTTP API", () => {
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
