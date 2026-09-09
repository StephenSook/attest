import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error("E2E_BASE_URL is required for the production smoke test");

export default defineConfig({
  testDir: ".",
  testMatch: "smoke.spec.ts",
  timeout: 120_000,
  use: {
    baseURL,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  reporter: process.env.CI ? "github" : "list",
});
