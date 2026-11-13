// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Offline JSON-LD document loader.
 *
 * - Contexts come only from the pinned bundle (contexts.ts).
 * - `did:key` DIDs are resolved locally (they are self-describing).
 * - `did:web` DIDs are never fetched by the signer: the caller (the api's verification service,
 *   which owns network policy and the "unable to verify" decision) passes the DID documents it
 *   resolved. Anything else is refused, so a credential cannot make the signer reach the network.
 */
import * as Ed25519Multikey from "@digitalbazaar/ed25519-multikey";
import { driver as didKeyDriver } from "@digitalbazaar/did-method-key";

import { CONTEXTS } from "./contexts.js";

export class UnresolvableDocument extends Error {
  constructor(public readonly url: string) {
    super(`Document not available offline: ${url}`);
    this.name = "UnresolvableDocument";
  }
}

const didKey = didKeyDriver();
didKey.use({ multibaseMultikeyHeader: "z6Mk", fromMultibase: Ed25519Multikey.from });

export type DidDocuments = Record<string, Record<string, unknown>>;

interface RemoteDocument {
  contextUrl: null;
  documentUrl: string;
  document: unknown;
}

function fragmentOf(doc: Record<string, unknown>, url: string): Record<string, unknown> | undefined {
  const methods = (doc.verificationMethod ?? []) as Array<Record<string, unknown>>;
  const found = methods.find((m) => m.id === url);
  if (!found) return undefined;
  return { "@context": doc["@context"], ...found };
}

export function makeLoader(didDocuments: DidDocuments = {}) {
  return async function documentLoader(url: string): Promise<RemoteDocument> {
    const context = CONTEXTS.get(url);
    if (context) return { contextUrl: null, documentUrl: url, document: context };

    if (url.startsWith("did:key:")) {
      const document = await didKey.get({ url });
      return { contextUrl: null, documentUrl: url, document };
    }

    if (url.startsWith("did:web:")) {
      const [did] = url.split("#") as [string];
      const doc = didDocuments[did];
      if (doc && doc.id === did) {
        const document = url.includes("#") ? fragmentOf(doc, url) : doc;
        if (document) return { contextUrl: null, documentUrl: url, document };
        // The issuer's DID resolved, but it no longer lists this key (e.g. revoked after a
        // compromise): that is a verification failure, not missing infrastructure.
        throw new Error(`Verification method ${url} is not published by ${did}`);
      }
    }
    throw new UnresolvableDocument(url);
  };
}
