// SPDX-License-Identifier: AGPL-3.0-or-later
import { buildApp } from "./app.js";
import { loadConfig } from "./config.js";
import { PgKeyStore } from "./store.js";

const config = loadConfig();
const store = new PgKeyStore(config.databaseUrl);

if (config.env === "production" && (await store.devKeysPresent())) {
  console.error(
    "Refusing to start in production: keys.private_keys holds development keys, or keys wrapped with the " +
      "committed development KEK. Retire and destroy them, then create new keys under your own SIGNER_KEK.",
  );
  process.exit(1);
}

const app = buildApp(config, store);
await app.listen({ host: config.host, port: config.port });

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, async () => {
    await app.close();
    await store.close();
    process.exit(0);
  });
}
