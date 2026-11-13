// SPDX-License-Identifier: AGPL-3.0-or-later
/** Ed25519 key generation (Digital Bazaar Multikey) and did:key identifiers. */
import * as Ed25519Multikey from "@digitalbazaar/ed25519-multikey";

export interface GeneratedKey {
  publicKeyMultibase: string;
  secretKeyMultibase: string;
  did: string;
  verificationMethodId: string;
}

/**
 * Generate an Ed25519 key in `did:key` form. Development issuers use did:key (ADR-0004);
 * production issuers get did:web documents built by the api from the public key (W4).
 */
export async function generateDidKey(): Promise<GeneratedKey> {
  const keyPair = await Ed25519Multikey.generate();
  const exported = await keyPair.export({ publicKey: true, secretKey: true });
  if (!exported.secretKeyMultibase) throw new Error("key export did not include the secret key");
  const did = `did:key:${exported.publicKeyMultibase}`;
  return {
    publicKeyMultibase: exported.publicKeyMultibase,
    secretKeyMultibase: exported.secretKeyMultibase,
    did,
    verificationMethodId: `${did}#${exported.publicKeyMultibase}`,
  };
}
