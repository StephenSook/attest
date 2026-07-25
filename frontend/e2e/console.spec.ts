import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL ?? "http://localhost:8000";

test("landing renders the hero and the tour control", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Attest/);
  await expect(page.getByLabel("Attest")).toContainText("phone agent");
  await expect(
    page.getByRole("button", { name: /guided tour/i }),
  ).toBeVisible();
});

test("runs ledger lists the seeded replay, labeled as a replay", async ({ page }) => {
  await page.goto("/runs");
  const row = page.getByRole("link", { name: /Example Counseling Center/ });
  await expect(row).toBeVisible();
  await expect(row).toContainText("replay of real call");
});

test("run detail shows the verdict stamp and the supporting span", async ({ page }) => {
  await page.goto("/runs/run_replay_probe_0001");
  await expect(page.getByText(/record-accurate posterior/)).toBeVisible();
  await expect(page.locator(".evidence-span")).toHaveText("Yep");
  await expect(page.getByText("abstain")).toBeVisible();
  await expect(page.getByText(/no supporting span/)).toBeVisible();
});

test("calibration page serves live metrics, never hardcoded", async ({ page }) => {
  const metrics = await (await fetch(`${API}/api/metrics`)).json();
  const coverage = (metrics.headline.empirical_coverage * 100).toFixed(1);
  await page.goto("/calibration");
  await expect(page.getByText(`${coverage}%`).first()).toBeVisible();
  await expect(page.getByText("no_dead_end")).toBeVisible();
});

test("live-call gate refuses a wrong key", async ({ page }) => {
  await page.goto("/runs/new");
  await page.getByLabel(/operator key/i).fill("wrong-key-entirely");
  await page.getByLabel(/organization/i).fill("Gate Test Practice");
  await page.getByLabel(/published phone line/i).fill("+15550101234");
  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page.getByText(/key was not accepted/i)).toBeVisible();
});

test("the whole loop: a demo-key run travels to a verdict", async ({ page }) => {
  await page.goto("/runs/new");
  await page.getByLabel(/operator key/i).fill("demo-mode-key");
  await page.getByLabel(/organization/i).fill("E2E Loop Practice");
  await page.getByLabel(/published phone line/i).fill("+15550101234");
  await page.getByRole("button", { name: /place the call/i }).click();

  // Lands on the run page; the poller completes the mock call within a tick.
  await expect(page).toHaveURL(/\/runs\/run_/);
  await expect(page.getByText(/record-accurate posterior/)).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.locator(".evidence-span")).toBeVisible();
});
