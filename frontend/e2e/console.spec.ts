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

test("console header and certificate stay inside a phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const routes = [
    { path: "/runs", ready: page.getByRole("heading", { name: "Verification runs" }) },
    {
      path: "/calibration",
      ready: page.getByRole("heading", { name: "The guarantee, measured" }),
    },
    {
      path: "/verify",
      ready: page.getByRole("heading", { name: "Verify a certificate" }),
    },
    { path: "/runs/new", ready: page.getByLabel(/judge key/i) },
    {
      path: "/runs/run_replay_builder_0001/certificate",
      ready: page.getByRole("button", { name: /download json/i }),
    },
  ];
  for (const { path, ready } of routes) {
    await page.goto(path);
    await expect(ready).toBeVisible();
    // The certificate stamp enters with a spring. Measure the final layout,
    // not an intentional transform between its first and settled frames.
    await page.waitForTimeout(800);
    const width = await page.evaluate(() => ({
      client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
      offenders: Array.from(document.body.querySelectorAll<HTMLElement>("*"))
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName.toLowerCase(),
            className: element.className.toString().slice(0, 120),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
          };
        })
        .filter(
          ({ left, right }) =>
            right - left > 1 && (left < -1 || right > window.innerWidth + 1),
        )
        .slice(0, 8),
    }));
    expect(width.offenders, `${path} clips responsive content`).toEqual([]);
    expect(width.scroll, `${path} overflows by ${width.scroll - width.client}px`).toBeLessThanOrEqual(
      width.client + 1,
    );
  }
});

test("runs ledger lists the seeded replay with its verdict badge", async ({ page }) => {
  await page.goto("/runs");
  const row = page.getByRole("link", { name: /Example Counseling Center/ });
  await expect(row).toBeVisible();
  await expect(row).toContainText("replay of real call");
  // The verdict reads at a glance without opening the run.
  await expect(row).toContainText(/verified|contradicted|unverifiable/);
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
  const targets = [...metrics.per_alpha].sort((a, b) => a.target - b.target);
  // Move to the strictest evaluated target. Slider values increase with the
  // visible target, so ArrowRight has the direction users expect.
  await slider.fill(String(targets.length - 1));
  const strictest = targets.at(-1)!;
  await expect(
    page.getByText(`${Math.round(strictest.target * 100)}%`).first(),
  ).toBeVisible();
  await expect(
    page.getByText(`${(strictest.abstention_rate * 100).toFixed(1)}%`).first(),
  ).toBeVisible();
  await expect(slider).toHaveAttribute(
    "aria-valuetext",
    new RegExp(`^${Math.round(strictest.target * 100)} percent target coverage`),
  );
});

test("disabled live sandbox explains the safe replay path", async ({ page }) => {
  await page.route("**/healthz", async (route) => {
    await route.fulfill({
      json: {
        status: "ok",
        service: "attest",
        poller: "running",
        provider: "live",
        sandbox: "disabled",
      },
    });
  });
  await page.goto("/runs/new");
  await expect(page.getByText(/live call sandbox paused/i)).toBeVisible();
  await expect(page.getByLabel(/judge key/i)).toHaveCount(0);
  await expect(page.getByRole("link", { name: /recorded calls/i })).toBeVisible();
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
  await page.getByLabel(/judge key/i).fill("wrong-key-entirely");
  await page.getByLabel(/organization/i).fill("Gate Test Practice");
  await page.getByLabel(/published phone line/i).fill("+15550101234");
  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page.getByText(/key was not accepted/i)).toBeVisible();
});

test("capability promotion failure keeps the same safe retry identity", async ({ page }) => {
  const attempts: { requestId: string; accessToken: string }[] = [];
  await page.route("**/healthz", async (route) => {
    await route.fulfill({
      json: {
        status: "ok",
        service: "attest",
        poller: "running",
        provider: "live",
        sandbox: "enabled",
      },
    });
  });
  await page.route("**/internal/runs", async (route) => {
    const body = route.request().postDataJSON() as { request_id: string };
    const accessToken = route.request().headers()["x-attest-run-token"];
    attempts.push({ requestId: body.request_id, accessToken });
    await route.fulfill({
      status: 201,
      json: { run_id: `run_${body.request_id}`, access_token: accessToken },
    });
  });
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Object.defineProperty(window, "failRunTokenPromotion", {
      configurable: true,
      value: true,
      writable: true,
    });
    Storage.prototype.setItem = function (key: string, value: string) {
      if (
        key.startsWith("attest:run-token:") &&
        (window as Window & { failRunTokenPromotion?: boolean }).failRunTokenPromotion
      ) {
        throw new DOMException("storage unavailable", "QuotaExceededError");
      }
      return original.call(this, key, value);
    };
  });

  await page.goto("/runs/new");
  await page.getByLabel(/judge key/i).fill("demo-mode-key");
  await page.getByLabel(/organization/i).fill("Recovery Test Practice");
  await page.getByLabel(/published phone line/i).fill("+15550109999");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page.getByText(/storage unavailable/i)).toBeVisible();

  await page.evaluate(() => {
    (window as Window & { failRunTokenPromotion?: boolean }).failRunTokenPromotion = false;
  });
  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page).toHaveURL(/\/runs\/run_/);

  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
  await expect
    .poll(() =>
      page.evaluate(() => ({
        pending: sessionStorage.getItem("attest:pending-run"),
        promoted: Object.keys(sessionStorage).some((key) =>
          key.startsWith("attest:run-token:"),
        ),
      })),
    )
    .toEqual({ pending: null, promoted: true });
});

test("definite provider rejection clears the terminal request identity", async ({ page }) => {
  const attempts: { requestId: string; accessToken: string }[] = [];
  await page.route("**/healthz", async (route) => {
    await route.fulfill({
      json: {
        status: "ok",
        service: "attest",
        poller: "running",
        provider: "live",
        sandbox: "enabled",
      },
    });
  });
  await page.route("**/internal/runs", async (route) => {
    const body = route.request().postDataJSON() as { request_id: string };
    const accessToken = route.request().headers()["x-attest-run-token"];
    attempts.push({ requestId: body.request_id, accessToken });
    if (attempts.length === 1) {
      await route.fulfill({
        status: 502,
        json: {
          detail: {
            code: "call_rejected_before_acceptance",
            message: "CALL-E rejected the request before accepting a call.",
          },
        },
      });
      return;
    }
    await route.fulfill({
      status: 201,
      json: { run_id: `run_${body.request_id}`, access_token: accessToken },
    });
  });

  await page.goto("/runs/new");
  await page.getByLabel(/judge key/i).fill("demo-mode-key");
  await page.getByLabel(/organization/i).fill("Fresh Retry Practice");
  await page.getByLabel(/published phone line/i).fill("+15550108888");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page.getByText(/rejected the request before accepting/i)).toBeVisible();
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem("attest:pending-run"))).toBeNull();

  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page).toHaveURL(/\/runs\/run_/);
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).not.toEqual(attempts[0]);
});

test("expired request tombstones the destination instead of redialing", async ({ page }) => {
  const attempts: { requestId: string; accessToken: string }[] = [];
  await page.route("**/healthz", async (route) => {
    await route.fulfill({
      json: {
        status: "ok",
        service: "attest",
        poller: "running",
        provider: "live",
        sandbox: "enabled",
      },
    });
  });
  await page.route("**/internal/runs", async (route) => {
    const body = route.request().postDataJSON() as { request_id: string };
    const accessToken = route.request().headers()["x-attest-run-token"];
    attempts.push({ requestId: body.request_id, accessToken });
    await route.fulfill({
      status: 409,
      json: {
        detail: {
          code: "call_request_not_retried",
          message: "The safe retry window ended.",
        },
      },
    });
  });

  await page.goto("/runs/new");
  await page.getByLabel(/judge key/i).fill("demo-mode-key");
  await page.getByLabel(/organization/i).fill("Expired Retry Practice");
  await page.getByLabel(/published phone line/i).fill("+15550107777");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page.getByText(/safe retry window ended/i)).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => JSON.parse(sessionStorage.getItem("attest:pending-run") ?? "null")),
    )
    .toMatchObject({ terminal: "expired", phone: "+15550107777" });

  await page.getByRole("button", { name: /place the call/i }).click();
  await expect(page.getByText(/will not create a fresh call identity/i)).toBeVisible();
  expect(attempts).toHaveLength(1);
});

test("the whole loop: a judge-key run travels to a verdict", async ({ page }) => {
  await page.goto("/runs/new");
  await page.getByLabel(/judge key/i).fill("demo-mode-key");
  await page.getByLabel(/organization/i).fill("E2E Loop Practice");
  // A fresh fictional number per attempt: the sandbox dedupes per phone.
  const phone = `+1555010${String(Math.floor(Math.random() * 10000)).padStart(4, "0")}`;
  await page.getByLabel(/published phone line/i).fill(phone);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /place the call/i }).click();

  // Lands on the run page; the poller completes the mock call within a tick.
  await expect(page).toHaveURL(/\/runs\/run_/);
  await expect(page.getByText(/record-accurate posterior/)).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.locator(".evidence-span")).toBeVisible();
});
