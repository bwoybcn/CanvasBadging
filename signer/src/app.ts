// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Signer HTTP API (internal network only).
 *
 * Key generation and lifecycle (W2/W4), Data Integrity signing with eddsa-rdfc-2022 and proof
 * verification (W4). Private keys are decrypted only for the duration of one signing call.
 */
import { timingSafeEqual } from "node:crypto";

import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";

import type { SignerConfig } from "./config.js";
import { decrypt, encrypt } from "./envelope.js";
import { generateDidKey } from "./keys.js";
import type { DidDocuments } from "./loader.js";
import { publicFromSecret, signCredential, SigningRefused, verifyProof } from "./proofs.js";
import type { KeyStore } from "./store.js";

const PUBLIC_ROUTES = new Set(["/healthz", "/readyz"]);

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
      redact: ["req.headers.authorization", "secretKeyMultibase", "*.secretKeyMultibase", "secret"],
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

  // Authenticate on the route Fastify actually matched, never on the raw request target:
  // the router percent-decodes paths ("/%761/sign" routes to /v1/sign) and strips
  // absolute-form targets, so a prefix check on req.url could be skipped. Everything except
  // the two health routes needs the shared secret, including unmatched paths.
  app.addHook("onRequest", async (req, reply) => {
    const route = req.routeOptions.url;
    if (!(route !== undefined && PUBLIC_ROUTES.has(route)) && !authorised(req, config.sharedSecret)) {
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

  // ---- key lifecycle -------------------------------------------------------------------
  app.post<{ Params: { id: string } }>("/v1/keys/:id/retire", async (req, reply) => {
    if (!UUID_RE.test(req.params.id)) return reply.code(404).send({ code: "NOT_FOUND", title: "No such key" });
    if (!(await store.retire(req.params.id))) return reply.code(404).send({ code: "NOT_FOUND", title: "No such key" });
    req.log.info({ issuer_key_id: req.params.id }, "key retired");
    return { issuer_key_id: req.params.id, signing: false };
  });

  app.post<{ Params: { id: string } }>("/v1/keys/:id/destroy", async (req, reply) => {
    if (!UUID_RE.test(req.params.id)) return reply.code(404).send({ code: "NOT_FOUND", title: "No such key" });
    if (!(await store.destroy(req.params.id))) return reply.code(404).send({ code: "NOT_FOUND", title: "No such key" });
    req.log.warn({ issuer_key_id: req.params.id }, "private key material destroyed");
    return { issuer_key_id: req.params.id, destroyed: true };
  });

  // ---- signing ---------------------------------------------------------------------------
  app.post<{
    Body: { issuer_key_id?: string; verification_method_id?: string; document?: Record<string, unknown>; created?: string };
  }>("/v1/sign", { bodyLimit: 512 * 1024 }, async (req, reply) => {
    const { issuer_key_id: keyId, verification_method_id: vmId, document } = req.body ?? {};
    if (!keyId || !UUID_RE.test(keyId) || typeof vmId !== "string" || !document || typeof document !== "object") {
      return reply.code(422).send({
        code: "VALIDATION_FAILED",
        title: "issuer_key_id (UUID), verification_method_id and document are required",
      });
    }
    const key = await store.get(keyId);
    if (!key) return reply.code(404).send({ code: "KEY_NOT_FOUND", title: "No such signing key" });
    if (key.destroyedAt || key.retiredAt) {
      return reply.code(409).send({ code: "KEY_NOT_ACTIVE", title: "This key is retired and can no longer sign" });
    }
    if (key.isDev && config.env === "production") {
      return reply.code(403).send({ code: "DEV_KEY_FORBIDDEN", title: "Development keys cannot sign in production" });
    }
    // JS strings cannot be wiped; the secret lives only in this request's scope.
    const secret = decrypt(config.kek, key, keyId);
    try {
      const publicKey = publicFromSecret(secret);
      if (vmId.startsWith("did:key:") && vmId !== `did:key:${publicKey}#${publicKey}`) {
        return reply.code(422).send({ code: "BAD_VERIFICATION_METHOD", title: "did:key method does not match this key" });
      }
      const created = req.body.created ? new Date(req.body.created) : undefined;
      if (created && Number.isNaN(created.getTime())) {
        return reply.code(422).send({ code: "VALIDATION_FAILED", title: "created must be an ISO 8601 date-time" });
      }
      const signed = await signCredential({ document, verificationMethodId: vmId, secretKeyMultibase: secret, created });
      req.log.info({ issuer_key_id: keyId, credential_id: document.id }, "signed");
      return { signed, public_key_multibase: publicKey };
    } catch (err) {
      if (err instanceof SigningRefused) return reply.code(422).send({ code: err.code, title: err.message });
      // JSON-LD safe mode, undefined terms or bad dates: the document is not a valid credential.
      req.log.warn({ issuer_key_id: keyId, err: (err as Error).message }, "document refused");
      return reply.code(422).send({ code: "DOCUMENT_INVALID", title: "The document could not be signed", detail: (err as Error).message });
    }
  });

  // ---- verification (proof only; dates and status are the caller's job) -----------------
  app.post<{ Body: { credential?: Record<string, unknown>; did_documents?: DidDocuments } }>(
    "/v1/verify",
    { bodyLimit: 512 * 1024 },
    async (req, reply) => {
      const credential = req.body?.credential;
      if (!credential || typeof credential !== "object" || Array.isArray(credential)) {
        return reply.code(422).send({ code: "VALIDATION_FAILED", title: "credential must be a JSON object" });
      }
      return verifyProof(credential, req.body?.did_documents ?? {});
    },
  );

  return app;
}
