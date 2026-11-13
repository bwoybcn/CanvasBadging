// SPDX-License-Identifier: AGPL-3.0-or-later
/** Signer configuration from the environment. Production refuses committed dev secrets. */

/** Publicly known development KEK (32 bytes, base64). Never valid in production. */
export const DEV_KEK_B64 = Buffer.from("dev-only-kek-never-use-in-prod!!").toString("base64");
export const DEV_SHARED_SECRET = "dev-only-insecure-signer-secret";

export interface SignerConfig {
  env: "development" | "test" | "production";
  host: string;
  port: number;
  databaseUrl: string;
  kek: Buffer;
  kekRef: string;
  sharedSecret: string;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): SignerConfig {
  const mode = (env.OC_ENV ?? "development") as SignerConfig["env"];
  const kekB64 = env.SIGNER_KEK ?? DEV_KEK_B64;
  const kek = Buffer.from(kekB64, "base64");
  if (kek.length !== 32) {
    throw new Error("SIGNER_KEK must be 32 bytes, base64-encoded");
  }
  const config: SignerConfig = {
    env: mode,
    host: env.SIGNER_HOST ?? "0.0.0.0",
    port: Number(env.SIGNER_PORT ?? 8790),
    databaseUrl:
      env.SIGNER_DATABASE_URL ?? "postgresql://oc_signer:oc_signer_dev@localhost:5432/opencredential",
    kek,
    kekRef: kekB64 === DEV_KEK_B64 ? "dev:committed" : "env:SIGNER_KEK",
    sharedSecret: env.OC_SIGNER_SHARED_SECRET ?? DEV_SHARED_SECRET,
  };
  if (mode === "production") {
    const problems: string[] = [];
    if (kekB64 === DEV_KEK_B64) problems.push("SIGNER_KEK is the committed development KEK");
    if (config.sharedSecret === DEV_SHARED_SECRET)
      problems.push("OC_SIGNER_SHARED_SECRET is the committed development value");
    if (problems.length) throw new Error(`Refusing to start in production: ${problems.join("; ")}`);
  }
  return config;
}
