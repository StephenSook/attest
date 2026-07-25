import { defineConfig } from "@playwright/test";

/* e2e against the compose stack: api on :8000 (mock mode, seeded), web dev
   server on :5173. CI runs `docker compose up` first; locally, do the same. */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
  reporter: process.env.CI ? "github" : "list",
});
