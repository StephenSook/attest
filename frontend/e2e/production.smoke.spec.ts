import { expect, test } from "@playwright/test";

test("deployed judge path renders API-backed evidence", async ({ page }) => {
  test.setTimeout(120_000);
  const failures: string[] = [];
  const appOrigin = new URL(process.env.E2E_BASE_URL ?? "http://localhost:5173").origin;

  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => failures.push(`page: ${error.message}`));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === appOrigin && response.status() >= 400) {
      failures.push(`response ${response.status()}: ${url.pathname}`);
    }
  });

  await page.goto("/");
  await expect(page.getByLabel("Attest")).toContainText("phone agent");
  await expect(page.getByRole("button", { name: /guided tour/i })).toBeVisible();

  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "Verification runs" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Example Counseling Center/ })).toBeVisible({
    timeout: 90_000,
  });

  await page.goto("/runs/run_replay_probe_0001");
  await expect(page.getByText(/record-accurate posterior/)).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".evidence-span")).toHaveText("Yep");

  await page.goto("/calibration");
  await expect(page.getByRole("heading", { name: "The guarantee, measured" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("accuracy when answering").first()).toBeVisible();

  await page.goto("/runs/run_replay_builder_0001/certificate");
  await expect(page.getByRole("button", { name: /download json/i })).toBeVisible({
    timeout: 30_000,
  });

  await page.goto("/runs/new");
  await expect(page.getByRole("heading", { name: "Live call sandbox paused" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByLabel(/judge key/i)).toHaveCount(0);
  expect(failures, failures.join("\n")).toEqual([]);
});
