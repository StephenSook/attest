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

test("landing scrolls to the very end under a wheel stream", async ({ page }) => {
  await page.goto("/");
  await page.waitForTimeout(600);
  const result = await page.evaluate(async () => {
    const max = () =>
      document.documentElement.scrollHeight - window.innerHeight;
    const video = document.querySelector<HTMLVideoElement>(".landing-film video");
    const startTime = video?.currentTime ?? 0;
    const interval = setInterval(() => {
      window.dispatchEvent(
        new WheelEvent("wheel", { deltaY: 260, bubbles: true, cancelable: true }),
      );
    }, 25);
    const t0 = performance.now();
    let stalledMs = 0;
    let lastY = -1;
    while (performance.now() - t0 < 20_000) {
      await new Promise((r) => setTimeout(r, 150));
      const y = window.scrollY;
      stalledMs = y === lastY ? stalledMs + 150 : 0;
      lastY = y;
      if (y >= max() - 4) break;
      // A stall longer than 3s mid-page is exactly the shipped bug.
      if (stalledMs > 3000) break;
    }
    clearInterval(interval);
    return {
      reachedEnd: window.scrollY >= max() - 4,
      stalledMs,
      filmAdvanced: video ? video.currentTime > startTime : null,
      filmDuration: video?.duration ?? 0,
    };
  });
  expect(result.reachedEnd, `stalled for ${result.stalledMs}ms before the end`).toBe(true);
  // Playwright's bundled Chromium ships without proprietary codecs, so the
  // film may not decode in CI (duration 0). Traversal is the load-bearing
  // assertion here; the committed asset itself is enforced by
  // tests/test_film_asset.py. When the film does decode, it must advance.
  if (result.filmDuration > 0) {
    expect(result.filmAdvanced).toBe(true);
  }
});

test("mobile viewport: full traversal, no horizontal overflow, 720p film", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.waitForTimeout(600);
  const result = await page.evaluate(async () => {
    const video = document.querySelector<HTMLVideoElement>(".landing-film video");
    const max = () => document.documentElement.scrollHeight - window.innerHeight;
    let overflow = document.documentElement.scrollWidth > window.innerWidth + 1;
    const t0 = performance.now();
    while (window.scrollY < max() - 4 && performance.now() - t0 < 15_000) {
      window.scrollBy(0, 260);
      await new Promise((r) => setTimeout(r, 40));
      overflow ||= document.documentElement.scrollWidth > window.innerWidth + 1;
    }
    return {
      reachedEnd: window.scrollY >= max() - 4,
      overflow,
      src: video?.currentSrc ?? "",
      poster: video?.poster ?? "",
    };
  });
  expect(result.reachedEnd).toBe(true);
  expect(result.overflow, "horizontal overflow on mobile").toBe(false);
  expect(result.src).toContain("hero-720.mp4");
  expect(result.poster).toContain("hero-poster.jpg");
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
  await expect(page.getByText("abstain").first()).toBeVisible();
  await expect(page.getByText(/no supporting span/).first()).toBeVisible();
});

test("audio evidence: waveform when audio exists, honest absence otherwise", async ({ page }) => {
  // The CALL-E API exposes no recording URL, so run audio only exists when
  // captured on our own end. CI seeds a labeled synthetic tone
  // (ATTEST_SEED_TEST_TONE=1); the default judge compose stays audio-free.
  const probe = await fetch(`${API}/api/runs/run_replay_probe_0001/audio`);
  // In CI the tone is seeded, so a non-200 here is a broken audio path, not
  // honest absence; never let the spec neutralize itself.
  if (process.env.E2E_EXPECT_AUDIO === "1") {
    expect(probe.status, "CI seeds a tone; audio must be served").toBe(200);
  }
  await page.goto("/runs/run_replay_probe_0001");
  await expect(page.getByText(/record-accurate posterior/)).toBeVisible();
  if (probe.status === 200) {
    const player = page.getByTestId("run-audio");
    await expect(player).toBeVisible();
    // The CI tone must never wear the real-call provenance label.
    await expect(player).toContainText(
      process.env.E2E_EXPECT_AUDIO === "1"
        ? /synthetic alignment tone, CI harness only/
        : /synthetic alignment tone|receiving end/,
    );
    // Clicking a transcript turn seeks the player and starts playback; the
    // control's accessible label flips to pause once playing.
    await page.locator(".evidence-span").click();
    await expect(page.getByLabel("Pause the call audio")).toBeVisible({ timeout: 10_000 });
  } else {
    await expect(page.getByTestId("run-audio")).toHaveCount(0);
  }
});

test("builder-line replay serves real audio with honest provenance", async ({ page }) => {
  // This replay's audio was captured on the receiving end of a consented
  // builder-line call and ships with the repo, so it must exist in EVERY
  // environment: CI, judge compose, and the deployed site.
  const probe = await fetch(`${API}/api/runs/run_replay_builder_0001/audio`);
  expect(probe.status, "builder replay audio must always be served").toBe(200);
  await page.goto("/runs/run_replay_builder_0001");
  const player = page.getByTestId("run-audio");
  await expect(player).toBeVisible();
  await expect(player).toContainText(/receiving end of this consented call, builder line/);
  await expect(page.getByText(/accepting new patients/).first()).toBeVisible();
});

test("attestation certificate renders signed and verifiable fields", async ({ page }) => {
  await page.goto("/runs/run_replay_builder_0001/certificate");
  await expect(page.getByText(/certificate of verification/i)).toBeVisible();
  await expect(page.getByText(/payload sha256 [0-9a-f]{16}/)).toBeVisible();
  await expect(page.getByText(/signature Ed25519|unsigned:/)).toBeVisible();
  await expect(page.getByRole("button", { name: /download json/i })).toBeVisible();
  await expect(page.getByText(/supporting span/).first()).toBeVisible();
});

test("risk-coverage explorer snaps to measured targets only", async ({ page }) => {
  const metrics = await (await fetch(`${API}/api/metrics`)).json();
  await page.goto("/calibration");
  const slider = page.getByLabel(/target coverage selector/i);
  await expect(slider).toBeVisible();
  // Move to the strictest evaluated target (index 0 = smallest alpha).
  await slider.fill("0");
  const strictest = metrics.per_alpha[0];
  await expect(
    page.getByText(`${Math.round(strictest.target * 100)}%`).first(),
  ).toBeVisible();
  await expect(
    page.getByText(`${(strictest.abstention_rate * 100).toFixed(1)}%`).first(),
  ).toBeVisible();
});

test("a real certificate verifies in the browser; a tampered one fails", async ({ page }) => {
  const doc = await (await fetch(`${API}/api/runs/run_replay_builder_0001/attestation`)).json();
  await page.goto("/verify");
  await page.getByPlaceholder(/attestation\/v1/).fill(JSON.stringify(doc));
  await page.getByRole("button", { name: /verify signature/i }).click();
  await expect(page.getByText(/signature valid/i)).toBeVisible({ timeout: 15_000 });
  // Tamper with the verdict and verify again: must fail.
  doc.reconciliation.verdict = "verified";
  await page.getByPlaceholder(/attestation\/v1/).fill(JSON.stringify(doc));
  await page.getByRole("button", { name: /verify signature/i }).click();
  await expect(page.getByText(/not valid/i)).toBeVisible({ timeout: 15_000 });
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
