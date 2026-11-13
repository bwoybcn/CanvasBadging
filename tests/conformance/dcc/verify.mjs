// SPDX-License-Identifier: AGPL-3.0-or-later
// Usage: node verify.mjs <expected: active|revoked> <credential.json>...
// Verifies each credential with @digitalcredentials/verifier-core, an implementation maintained
// by the Digital Credentials Consortium (independent of OpenCredential), and fails unless the
// signature is valid, the credential is unexpired, and the revocation result matches.
// With DCC_REQUIRE_SCHEMA=1 (CI, which can reach purl.imsglobal.org) every credentialSchema the
// credential lists must also validate with the verifier's own JSON Schema check.
import { readFileSync } from "node:fs";

import { verifyCredential } from "@digitalcredentials/verifier-core";

const [expected, ...files] = process.argv.slice(2);
if (!["active", "revoked"].includes(expected) || files.length === 0) {
  console.error("usage: node verify.mjs active|revoked file...");
  process.exit(2);
}
let failed = false;
for (const file of files) {
  const credential = JSON.parse(readFileSync(file, "utf8"));
  const result = await verifyCredential({ credential, knownDIDRegistries: [] });
  const log = Object.fromEntries((result.log ?? []).map((e) => [e.id, e]));
  const summary = {
    file,
    errors: result.errors ?? null,
    valid_signature: log.valid_signature?.valid,
    expiration: log.expiration?.valid,
    revocation_status: log.revocation_status?.valid,
    registered_issuer: log.registered_issuer?.valid,
    schema: result.additionalInformation ?? null,
  };
  console.log(JSON.stringify(summary, null, 2));
  const wantRevocation = expected === "active";
  const schemaResults = result.additionalInformation?.find((e) => e.id === "schema_check")?.results;
  const schemaOk =
    process.env.DCC_REQUIRE_SCHEMA !== "1" ||
    (Array.isArray(schemaResults) && schemaResults.length > 0 && schemaResults.every((r) => r.result?.valid === true));
  if (!schemaOk) console.error(`FAIL ${file}: JSON Schema check did not pass`);
  if (!schemaOk || summary.valid_signature !== true || summary.expiration !== true || summary.revocation_status !== wantRevocation) {
    console.error(`FAIL ${file}: expected signature ok, unexpired, ${expected}`);
    failed = true;
  }
}
process.exit(failed ? 1 : 0);
