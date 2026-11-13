// SPDX-License-Identifier: AGPL-3.0-or-later
import { buildApp } from "./app.js";
import { loadConfig } from "./config.js";
import { PgKeyStore } from "./store.js";

const config = loadConfig();
const store = new PgKeyStore(config.databaseUrl);

if (config.env === "production" && (await store.devKeysPresent())) {
  console.error("Refusing to start in production: development keys are present in keys.private_keys");
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
