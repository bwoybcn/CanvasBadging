// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Signer HTTP API (internal network only).
 *
 * Phase 1 (W2) implements key generation and storage. Signing and verification with
 * eddsa-rdfc-2022 arrive in W4; until then those routes answer 501 rather than pretending.
 */
import { timingSafeEqual } from "node:crypto";

import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";

import type { SignerConfig } from "./config.js";
import { encrypt } from "./envelope.js";
import { generateDidKey } from "./keys.js";
import type { KeyStore } from "./store.js";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function authorised(req: FastifyRequest, secret: string): boolean {
  const header = req.headers.authorization ?? "";
  const expected = Buffer.from(`Bearer ${secret}`);
  const given = Buffer.from(header);
  return given.length === expected.length && timingSafeEqual(given, expected);
}

export function buildApp(config: SignerConfig, store: KeyStore): FastifyInstance {
  const app = Fastify({
    logger: {
      level: config.env === "test" ? "silent" : "info",
      redact: ["req.headers.authorization", "secretKeyMultibase"],
    },
  });

  app.get("/healthz", async () => ({ status: "ok", service: "signer" }));

  app.get("/readyz", async (_req, reply) => {
    try {
      await store.ping();
      return { status: "ok" };
    } catch {
      return reply.code(503).send({ status: "unavailable", checks: { database: "error" } });
    }
  });

  app.addHook("onRequest", async (req, reply) => {
    if (req.url.startsWith("/v1/") && !authorised(req, config.sharedSecret)) {
      return reply.code(401).send({ code: "UNAUTHENTICATED", title: "Signer credentials missing" });
    }
  });

  app.post<{ Body: { issuer_key_id?: string; dev?: boolean } }>("/v1/keys", async (req, reply) => {
    const keyId = req.body?.issuer_key_id;
    const dev = req.body?.dev === true;
    if (!keyId || !UUID_RE.test(keyId)) {
      return reply.code(422).send({ code: "VALIDATION_FAILED", title: "issuer_key_id must be a UUID" });
    }
    if (dev && config.env === "production") {
      return reply.code(403).send({ code: "DEV_KEY_FORBIDDEN", title: "Development keys cannot be created in production" });
    }
    const key = await generateDidKey();
    const envelope = encrypt(config.kek, key.secretKeyMultibase, keyId);
    const result = await store.insert({
      issuerKeyId: keyId,
      ...envelope,
      kekRef: config.kekRef,
      isDev: dev,
    });
    if (result === "exists") {
      return reply.code(409).send({ code: "KEY_EXISTS", title: "A key with this id already exists" });
    }
    req.log.info({ issuer_key_id: keyId, dev }, "key generated");
    return reply.code(201).send({
      issuer_key_id: keyId,
      algorithm: "Ed25519",
      public_key_multibase: key.publicKeyMultibase,
      did: key.did,
      verification_method_id: key.verificationMethodId,
      is_dev: dev,
    });
  });

  const notYet = async (_req: FastifyRequest, reply: { code: (n: number) => { send: (b: unknown) => unknown } }) =>
    reply.code(501).send({
      code: "NOT_IMPLEMENTED",
      title: "Signing and verification are implemented in workstream W4 (eddsa-rdfc-2022)",
    });
  app.post("/v1/sign", notYet);
  app.post("/v1/verify", notYet);

  return app;
}
