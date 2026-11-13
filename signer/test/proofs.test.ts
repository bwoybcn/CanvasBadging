// SPDX-License-Identifier: AGPL-3.0-or-later
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";
import { CONTEXTS, OB_V3P0_303 } from "../src/contexts.js";
import { DEV_SHARED_SECRET, loadConfig } from "../src/config.js";
import { generateDidKey } from "../src/keys.js";
import { publicFromSecret, signCredential, verifyProof } from "../src/proofs.js";
import { MemoryStore } from "./helpers.js";

const config = loadConfig({ OC_ENV: "test" });
const auth = { authorization: `Bearer ${DEV_SHARED_SECRET}` };

export function sampleCredential(issuer: string): Record<string, unknown> {
  return {
    "@context": ["https://www.w3.org/ns/credentials/v2", OB_V3P0_303],
    id: "urn:uuid:0190f3a2-7b1c-7d2e-8f00-123456789abc",
    type: ["VerifiableCredential", "OpenBadgeCredential"],
    issuer: { id: issuer, type: ["Profile"], name: "Demo University (DEVELOPMENT)", url: "https://demo.example/" },
    validFrom: "2026-11-13T12:00:00Z",
    name: "Academic Writing Foundations",
    credentialSubject: {
      type: ["AchievementSubject"],
      identifier: [
        {
          type: "IdentityObject",
          identityType: "emailAddress",
          hashed: true,
          identityHash: "sha256$c2f3e4c6a0f4e8b1d7f4c0c1d8e1a2f3b4c5d6e7f8091a2b3c4d5e6f708192a3",
          salt: "6f1c0e2d9a3b4c5d",
        },
      ],
      achievement: {
        id: "https://demo.example/achievements/0190f3a2-0000-7000-8000-000000000001",
        type: ["Achievement"],
        achievementType: "Badge",
        name: "Academic Writing Foundations",
        description: "Completed the academic writing modules.",
        criteria: { narrative: "Complete all three modules." },
      },
    },
  };
}

describe("pinned contexts", () => {
  it("bundles the official Open Badges 3.0.3 context byte-for-byte", () => {
    const official = JSON.parse(readFileSync(new URL("../../tests/conformance/contexts/ob-v3p0-context-3.0.3.json", import.meta.url), "utf8"));
    expect(CONTEXTS.get(OB_V3P0_303)).toEqual(official);
  });
});

describe("eddsa-rdfc-2022 proofs", () => {
  it("derives the public key from the stored secret", async () => {
    const key = await generateDidKey();
    expect(publicFromSecret(key.secretKeyMultibase)).toBe(key.publicKeyMultibase);
  });

  it("signs an OpenBadgeCredential that verifies, and detects tampering", async () => {
    const key = await generateDidKey();
    const signed = await signCredential({
      document: sampleCredential(key.did),
      verificationMethodId: key.verificationMethodId,
      secretKeyMultibase: key.secretKeyMultibase,
    });
    const proof = signed.proof as Record<string, string>;
    expect(proof.type).toBe("DataIntegrityProof");
    expect(proof.cryptosuite).toBe("eddsa-rdfc-2022");
    expect(proof.proofPurpose).toBe("assertionMethod");
    expect(proof.verificationMethod).toBe(key.verificationMethodId);
    expect(proof.proofValue).toMatch(/^z/);

    expect((await verifyProof(signed)).verified).toBe(true);

    const tampered = structuredClone(signed) as { credentialSubject: { achievement: { name: string } } };
    tampered.credentialSubject.achievement.name = "Something Grander";
    const bad = await verifyProof(tampered as unknown as Record<string, unknown>);
    expect(bad.verified).toBe(false);
    expect(bad.unresolvable).toBe(false);
  });

  it("refuses to sign for an issuer that does not control the key", async () => {
    const key = await generateDidKey();
    const other = await generateDidKey();
    await expect(
      signCredential({
        document: sampleCredential(other.did),
        verificationMethodId: key.verificationMethodId,
        secretKeyMultibase: key.secretKeyMultibase,
      }),
    ).rejects.toThrow(/does not control/);
  });

  it("refuses undefined terms (JSON-LD safe mode)", async () => {
    const key = await generateDidKey();
    const doc = sampleCredential(key.did);
    (doc as Record<string, unknown>).madeUpProperty = "not in any context";
    await expect(
      signCredential({ document: doc, verificationMethodId: key.verificationMethodId, secretKeyMultibase: key.secretKeyMultibase }),
    ).rejects.toThrow();
  });

  it("verifies did:web credentials against a caller-supplied DID document, and says when it cannot resolve", async () => {
    const key = await generateDidKey();
    const did = "did:web:credentials.example.ac.uk:issuers:demo";
    const vm = `${did}#key-1`;
    const signed = await signCredential({ document: sampleCredential(did), verificationMethodId: vm, secretKeyMultibase: key.secretKeyMultibase });
    const didDoc = {
      "@context": ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/multikey/v1"],
      id: did,
      verificationMethod: [{ id: vm, type: "Multikey", controller: did, publicKeyMultibase: key.publicKeyMultibase }],
      assertionMethod: [vm],
    };
    expect((await verifyProof(signed, { [did]: didDoc })).verified).toBe(true);

    const unresolved = await verifyProof(signed);
    expect(unresolved.verified).toBe(false);
    expect(unresolved.unresolvable).toBe(true);

    // A key removed from assertionMethod (compromise procedure) no longer verifies.
    const revoked = { ...didDoc, assertionMethod: [] };
    const res = await verifyProof(signed, { [did]: revoked });
    expect(res.verified).toBe(false);
    expect(res.unresolvable).toBe(false);
  });
});

describe("signing over HTTP", () => {
  async function setup() {
    const store = new MemoryStore();
    const app = buildApp(config, store);
    const keyId = crypto.randomUUID();
    const res = await app.inject({ method: "POST", url: "/v1/keys", headers: auth, payload: { issuer_key_id: keyId, dev: true } });
    return { app, store, keyId, key: res.json() as { did: string; verification_method_id: string } };
  }

  it("signs with a stored key and verifies the result", async () => {
    const { app, keyId, key } = await setup();
    const res = await app.inject({
      method: "POST",
      url: "/v1/sign",
      headers: auth,
      payload: { issuer_key_id: keyId, verification_method_id: key.verification_method_id, document: sampleCredential(key.did) },
    });
    expect(res.statusCode).toBe(200);
    expect(res.body).not.toMatch(/secretKey/);
    const { signed } = res.json();
    const v = await app.inject({ method: "POST", url: "/v1/verify", headers: auth, payload: { credential: signed } });
    expect(v.json().verified).toBe(true);
  });

  it("will not sign with a retired or destroyed key", async () => {
    const { app, keyId, key, store } = await setup();
    await app.inject({ method: "POST", url: `/v1/keys/${keyId}/retire`, headers: auth });
    const res = await app.inject({
      method: "POST",
      url: "/v1/sign",
      headers: auth,
      payload: { issuer_key_id: keyId, verification_method_id: key.verification_method_id, document: sampleCredential(key.did) },
    });
    expect(res.statusCode).toBe(409);
    await app.inject({ method: "POST", url: `/v1/keys/${keyId}/destroy`, headers: auth });
    expect(store.rows.get(keyId)!.ciphertext.length).toBe(0);
  });

  it("rejects a did:key verification method that is not this key", async () => {
    const { app, keyId } = await setup();
    const other = await generateDidKey();
    const res = await app.inject({
      method: "POST",
      url: "/v1/sign",
      headers: auth,
      payload: { issuer_key_id: keyId, verification_method_id: other.verificationMethodId, document: sampleCredential(other.did) },
    });
    expect(res.statusCode).toBe(422);
    expect(res.json().code).toBe("BAD_VERIFICATION_METHOD");
  });
});
