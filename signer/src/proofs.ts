// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Data Integrity proofs with the `eddsa-rdfc-2022` cryptosuite (ADR-0002), implemented only with
 * Digital Bazaar's audited libraries: no cryptographic code of our own beyond key decoding.
 */
import { DataIntegrityProof } from "@digitalbazaar/data-integrity";
import { cryptosuite as eddsaRdfc2022 } from "@digitalbazaar/eddsa-rdfc-2022-cryptosuite";
import * as Ed25519Multikey from "@digitalbazaar/ed25519-multikey";
import { CredentialIssuancePurpose, issue } from "@digitalbazaar/vc";
import { decode, encode } from "base58-universal";
import jsigs from "jsonld-signatures";

import { type DidDocuments, makeLoader } from "./loader.js";

export class SigningRefused extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = "SigningRefused";
  }
}

const ED25519_PUB = [0xed, 0x01];
const ED25519_PRIV = [0x80, 0x26];

/** Derive the public Multikey from a stored secret (`ed25519-priv` multikey = seed ‖ public key). */
export function publicFromSecret(secretKeyMultibase: string): string {
  if (!secretKeyMultibase.startsWith("z")) throw new Error("secret key is not base58btc multibase");
  const bytes = decode(secretKeyMultibase.slice(1));
  if (bytes.length !== 66 || bytes[0] !== ED25519_PRIV[0] || bytes[1] !== ED25519_PRIV[1]) {
    throw new Error("secret key is not an Ed25519 multikey");
  }
  const pub = new Uint8Array(34);
  pub.set(ED25519_PUB, 0);
  pub.set(bytes.subarray(34), 2);
  return `z${encode(pub)}`;
}

function issuerId(document: Record<string, unknown>): string | undefined {
  const issuer = document.issuer;
  if (typeof issuer === "string") return issuer;
  if (issuer && typeof issuer === "object") return (issuer as { id?: string }).id;
  return undefined;
}

export interface SignInput {
  document: Record<string, unknown>;
  verificationMethodId: string;
  secretKeyMultibase: string;
  /** Proof creation time; defaults to now. */
  created?: Date;
}

/** Sign a VC 2.0 credential (an OpenBadgeCredential or a BitstringStatusListCredential). */
export async function signCredential(input: SignInput): Promise<Record<string, unknown>> {
  const { document, verificationMethodId } = input;
  if ("proof" in document) throw new SigningRefused("ALREADY_SIGNED", "document already has a proof");
  const controller = verificationMethodId.split("#")[0];
  if (!controller || !verificationMethodId.includes("#")) {
    throw new SigningRefused("BAD_VERIFICATION_METHOD", "verification method must be a DID URL with a fragment");
  }
  if (issuerId(document) !== controller) {
    // The proof's key must belong to the credential's issuer (spec §7.4: no vendor-as-issuer).
    throw new SigningRefused("ISSUER_MISMATCH", "credential issuer does not control this key");
  }
  const keyPair = await Ed25519Multikey.from({
    type: "Multikey",
    id: verificationMethodId,
    controller,
    publicKeyMultibase: publicFromSecret(input.secretKeyMultibase),
    secretKeyMultibase: input.secretKeyMultibase,
  });
  const suite = new DataIntegrityProof({
    signer: keyPair.signer(),
    cryptosuite: eddsaRdfc2022,
    date: input.created ?? new Date(),
  });
  // structuredClone: vc.issue mutates its input.
  return issue({ credential: structuredClone(document), suite, documentLoader: makeLoader() });
}

export interface VerifyOutput {
  verified: boolean;
  verification_method: string | null;
  errors: Array<{ name: string; message: string }>;
  /** True when the failure was an unresolvable DID/context, not a bad signature. */
  unresolvable: boolean;
}

function flattenErrors(err: unknown): Error[] {
  if (!err) return [];
  const e = err as { errors?: unknown[] };
  if (Array.isArray(e.errors) && e.errors.length) return e.errors.flatMap(flattenErrors);
  return [err as Error];
}

/**
 * Verify the proof only: signature, cryptosuite, verification method, and that the method is
 * an assertionMethod of the credential's issuer. Validity dates and status are checked by the
 * caller, so an expired or revoked credential can still be reported as authentic-but-expired.
 */
export async function verifyProof(
  credential: Record<string, unknown>,
  didDocuments: DidDocuments = {},
): Promise<VerifyOutput> {
  const proof = credential.proof as Record<string, unknown> | undefined;
  if (!proof || typeof proof !== "object" || Array.isArray(proof)) {
    return { verified: false, verification_method: null, unresolvable: false, errors: [{ name: "NO_PROOF", message: "credential has exactly one embedded proof required" }] };
  }
  if (proof.type !== "DataIntegrityProof" || proof.cryptosuite !== "eddsa-rdfc-2022") {
    return {
      verified: false,
      verification_method: (proof.verificationMethod as string) ?? null,
      unresolvable: false,
      errors: [{ name: "UNSUPPORTED_PROOF", message: `unsupported proof ${String(proof.type)}/${String(proof.cryptosuite)}` }],
    };
  }
  const suite = new DataIntegrityProof({ cryptosuite: eddsaRdfc2022 });
  const result = await jsigs.verify(structuredClone(credential), {
    suite,
    purpose: new CredentialIssuancePurpose(),
    documentLoader: makeLoader(didDocuments),
  });
  const errors = flattenErrors(result.error).map((e) => ({ name: e.name ?? "Error", message: e.message ?? String(e) }));
  const unresolvable = flattenErrors(result.error).some(
    (e) => e.name === "UnresolvableDocument" || /Document not available offline/.test(e.message ?? ""),
  );
  return {
    verified: result.verified,
    verification_method: (proof.verificationMethod as string) ?? null,
    unresolvable,
    errors,
  };
}
