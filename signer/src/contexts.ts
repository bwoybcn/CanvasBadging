// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Pinned JSON-LD contexts (ADR-0002). The signer never fetches a context from the network:
 * every context a credential may use is bundled here from audited npm packages, and anything
 * else is refused. The Open Badges context files are byte-identical to the 1EdTech originals at
 * https://purl.imsglobal.org/spec/ob/v3p0/ (checked in test/contexts.test.ts).
 */
import { createRequire } from "node:module";

import * as credentialsContext from "@digitalbazaar/credentials-context";
import * as dataIntegrityContext from "@digitalbazaar/data-integrity-context";
import * as multikeyContext from "@digitalbazaar/multikey-context";

const require = createRequire(import.meta.url);

export const VC_V2 = "https://www.w3.org/ns/credentials/v2";
export const OB_V3P0_303 = "https://purl.imsglobal.org/spec/ob/v3p0/context-3.0.3.json";
export const DID_V1 = "https://www.w3.org/ns/did/v1";
export const MULTIKEY_V1 = "https://w3id.org/security/multikey/v1";

const OB_PREFIX = "https://purl.imsglobal.org/spec/ob/v3p0/";
const obContextFiles: Record<string, string> = {
  "context-3.0.3.json": "context-3.0.3.js",
  "context-3.0.2.json": "context-3.0.2.js",
  "context-3.0.1.json": "context-3.0.1.js",
  "context.json": "context-3.0.js",
  "extensions.json": "context-extensions.js",
};

/** Minimal DID v1 context: only the terms our DID documents use (id, type, controller, keys). */
const DID_V1_CONTEXT = {
  "@context": {
    "@protected": true,
    id: "@id",
    type: "@type",
    alsoKnownAs: { "@id": "https://www.w3.org/ns/activitystreams#alsoKnownAs", "@type": "@id" },
    assertionMethod: { "@id": "https://w3id.org/security#assertionMethod", "@type": "@id", "@container": "@set" },
    authentication: { "@id": "https://w3id.org/security#authenticationMethod", "@type": "@id", "@container": "@set" },
    capabilityDelegation: { "@id": "https://w3id.org/security#capabilityDelegationMethod", "@type": "@id", "@container": "@set" },
    capabilityInvocation: { "@id": "https://w3id.org/security#capabilityInvocationMethod", "@type": "@id", "@container": "@set" },
    controller: { "@id": "https://w3id.org/security#controller", "@type": "@id" },
    keyAgreement: { "@id": "https://w3id.org/security#keyAgreementMethod", "@type": "@id", "@container": "@set" },
    service: {
      "@id": "https://www.w3.org/ns/did#service",
      "@type": "@id",
      "@context": {
        "@protected": true,
        id: "@id",
        type: "@type",
        serviceEndpoint: { "@id": "https://www.w3.org/ns/did#serviceEndpoint", "@type": "@id" },
      },
    },
    verificationMethod: { "@id": "https://w3id.org/security#verificationMethod", "@type": "@id" },
  },
};

function build(): Map<string, unknown> {
  const map = new Map<string, unknown>();
  for (const [url, doc] of credentialsContext.contexts as Map<string, unknown>) map.set(url, doc);
  for (const [url, doc] of dataIntegrityContext.contexts as Map<string, unknown>) map.set(url, doc);
  for (const [url, doc] of multikeyContext.contexts as Map<string, unknown>) map.set(url, doc);
  for (const [file, mod] of Object.entries(obContextFiles)) {
    map.set(OB_PREFIX + file, require(`@digitalcredentials/open-badges-context/js/contexts/${mod}`));
  }
  map.set(DID_V1, DID_V1_CONTEXT);
  return map;
}

export const CONTEXTS: ReadonlyMap<string, unknown> = build();
