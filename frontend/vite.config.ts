// SPDX-License-Identifier: AGPL-3.0-or-later
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.OC_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  server: {
    port: 5173,
    proxy: { "/api": api, "/dev": api, "/healthz": api },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // The badge wizard tests click through up to seven steps with userEvent and take about
    // 5 seconds on a CI runner, right at Vitest's default limit, so they failed now and then.
    testTimeout: 20_000,
  },
});
