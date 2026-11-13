// SPDX-License-Identifier: AGPL-3.0-or-later
// End-to-end and accessibility suite (spec §19.3, §19.5). Runs against a running stack:
//   docker compose up   (or the "without Docker" steps in docs/development/local-setup.md)
//   cd tests/end_to_end && npm ci && npm test
// OC_BASE_URL overrides the target (default http://localhost:8000).
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"], ["json", { outputFile: "results/results.json" }]],
  use: {
    baseURL: process.env.OC_BASE_URL ?? "http://localhost:8000",
    trace: "off",
    screenshot: "only-on-failure",
  },
  // The scenarios run first: they create the credentials (issued, shared, revoked) that the
  // accessibility pass then looks at, so a freshly seeded database works.
  projects: [
    { name: "scenarios", use: { ...devices["Desktop Chrome"] }, testMatch: /scenarios\.spec\.ts/ },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /a11y\.spec\.ts/,
      dependencies: ["scenarios"],
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"] },
      testMatch: /a11y\.spec\.ts/,
      dependencies: ["scenarios"],
    },
  ],
});
