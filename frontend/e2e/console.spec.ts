import { expect, test, type Locator } from "@playwright/test";

const API = process.env.E2E_API_URL ?? "http://localhost:8000";

async function renderedTextSamples(locator: Locator) {
  return locator.evaluateAll((elements) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const parseColor = (value: string): [number, number, number, number] => {
      if (!context) throw new Error("canvas 2d context unavailable; contrast not measured");
      context.clearRect(0, 0, 1, 1);
      // The canvas silently keeps the previous fill on an unparseable
      // string, which would measure contrast against the wrong colour and
      // pass. Prime two different sentinels: a parsed value reads back the
      // same after both, an unparsed one reads back each sentinel in turn.
      context.fillStyle = "#010203";
      context.fillStyle = value;
      const afterFirst = context.fillStyle;
      context.fillStyle = "#040506";
      context.fillStyle = value;
      if (context.fillStyle !== afterFirst) {
        throw new Error(`unparseable colour: ${value}`);
      }
      context.fillRect(0, 0, 1, 1);
      const [red, green, blue, alpha] = context.getImageData(0, 0, 1, 1).data;
      return [red, green, blue, alpha / 255];
    };
    const compositeBackground = (element: Element): number[] => {
      const chain: Element[] = [];
      for (let current: Element | null = element; current; current = current.parentElement) {
        chain.push(current);
      }
      return chain.reverse().reduce<number[]>((background, current) => {
        const [red, green, blue, alpha] = parseColor(
          getComputedStyle(current).backgroundColor,
        );
        return [
          red * alpha + background[0] * (1 - alpha),
          green * alpha + background[1] * (1 - alpha),
          blue * alpha + background[2] * (1 - alpha),
        ];
      }, [255, 255, 255]);
    };
    const luminance = ([red, green, blue]: number[]) => {
      const channels = [red, green, blue].map((value) => {
        const channel = value / 255;
        return channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };

    return elements.flatMap((element) => {
      const text = element.textContent?.trim().toLowerCase() ?? "";
      const rect = element.getBoundingClientRect();
      if (!text || rect.width === 0 || rect.height === 0) return [];
      const style = getComputedStyle(element);
      const foreground = luminance(parseColor(style.color));
      const background = luminance(compositeBackground(element));
      const contrast =
        (Math.max(foreground, background) + 0.05) /
        (Math.min(foreground, background) + 0.05);
      return [{ text, fontSize: Number.parseFloat(style.fontSize), contrast }];
    });
  });
}

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
  const tour = page.getByRole("button", { name: /guided tour/i });
  await expect(tour).toBeVisible();
  const tourBox = await tour.boundingBox();
  expect(tourBox?.width).toBeGreaterThanOrEqual(44);
  expect(tourBox?.height).toBeGreaterThanOrEqual(44);
  await tour.click();
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  await page.waitForTimeout(300);
  await tour.press("Space");
  await expect(tour).toHaveAccessibleName(/resume guided tour/i);
  const pausedY = await page.evaluate(() => window.scrollY);
  await page.waitForTimeout(350);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - pausedY)).toBeLessThanOrEqual(1);
  await tour.press("Space");
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  const resumedY = await page.evaluate(() => window.scrollY);
  await page.waitForTimeout(350);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(resumedY);
  await tour.press("PageDown");
  await expect(tour).toHaveAccessibleName(/resume guided tour/i);
  // Let the browser's requested page movement settle before proving the
  // separate guided-tour tween has stayed paused.
  await page.waitForTimeout(800);
  const pagingPausedY = await page.evaluate(() => window.scrollY);
  await page.waitForTimeout(350);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - pagingPausedY)).toBeLessThanOrEqual(
    1,
  );
  // The control itself is the one pointer target that must not trip the
  // global pointerdown pause before its own click toggles state. Without
  // that exemption the pause button paused on pointerdown and resumed on
  // click, so pressing it while touring left the tour running.
  await tour.click();
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  await page.waitForTimeout(300);
  await tour.click();
  await expect(tour).toHaveAccessibleName(/resume guided tour/i);
  const pointerPausedY = await page.evaluate(() => window.scrollY);
  await page.waitForTimeout(350);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - pointerPausedY)).toBeLessThanOrEqual(
    1,
  );
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

test("a touch drag pauses the guided tour even when it starts on the control", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.waitForTimeout(600);
  const tour = page.getByRole("button", { name: /guided tour/i });
  await tour.click();
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  await page.waitForTimeout(300);
  // A touch that begins on the control is a tap until it moves past slop:
  // touchstart alone and a few pixels of finger wobble must leave the tour
  // running, or the click that follows the tap would resume what the
  // wobble paused. Movement past slop is a drag, and a drag pauses, or the
  // tween keeps snapping the page back under the reader's thumb.
  const dispatchTouch = (type: string, dx: number, dy: number) =>
    tour.evaluate(
      (el, [eventType, offsetX, offsetY]) => {
        const box = el.getBoundingClientRect();
        const touch = new Touch({
          identifier: 1,
          target: el,
          clientX: box.left + box.width / 2 + offsetX,
          clientY: box.top + box.height / 2 + offsetY,
        });
        el.dispatchEvent(
          new TouchEvent(eventType, {
            bubbles: true,
            touches: [touch],
            targetTouches: [touch],
            changedTouches: [touch],
          }),
        );
      },
      [type, dx, dy] as [string, number, number],
    );
  await dispatchTouch("touchstart", 0, 0);
  await dispatchTouch("touchmove", 3, 4);
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  const stillTouringY = await page.evaluate(() => window.scrollY);
  await expect
    .poll(() => page.evaluate(() => window.scrollY), { timeout: 5_000 })
    .toBeGreaterThan(stillTouringY);
  await dispatchTouch("touchmove", 0, 40);
  await expect(tour).toHaveAccessibleName(/resume guided tour/i);
  const pausedY = await page.evaluate(() => window.scrollY);
  await page.waitForTimeout(350);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - pausedY)).toBeLessThanOrEqual(1);
});

test("a drag from the control pauses the tour with another finger resting on the page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.waitForTimeout(600);
  const tour = page.getByRole("button", { name: /guided tour/i });
  await tour.click();
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  await page.waitForTimeout(300);
  // A thumb already resting at the screen edge is the oldest touch, so
  // touches[0] is the thumb. The control finger has to be tracked by its
  // own identifier, or its drag reads as the thumb standing still.
  const dispatch = (type: string, dy: number) =>
    tour.evaluate(
      (el, [eventType, offsetY]) => {
        const box = el.getBoundingClientRect();
        const thumb = new Touch({
          identifier: 7,
          target: document.body,
          clientX: 8,
          clientY: 600,
        });
        const finger = new Touch({
          identifier: 1,
          target: el,
          clientX: box.left + box.width / 2,
          clientY: box.top + box.height / 2 + offsetY,
        });
        el.dispatchEvent(
          new TouchEvent(eventType, {
            bubbles: true,
            touches: [thumb, finger],
            targetTouches: [finger],
            changedTouches: [finger],
          }),
        );
      },
      [type, dy] as [string, number],
    );
  await dispatch("touchstart", 0);
  await expect(tour).toHaveAccessibleName(/pause guided tour/i);
  await dispatch("touchmove", 40);
  await expect(tour).toHaveAccessibleName(/resume guided tour/i);
});

test("mobile calibration evidence labels meet text contrast and size floors", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const metrics = await page.request.get(`${API}/api/metrics`);
  expect(metrics.ok()).toBe(true);
  const metricsBody = await metrics.body();
  await page.route("**/api/metrics", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: metricsBody,
    }),
  );
  await page.goto("/calibration");
  await expect(page.getByRole("heading", { name: "The guarantee, measured" })).toBeVisible();

  const samples = await renderedTextSamples(
    page.locator('[role="list"] p, [role="list"] span'),
  );

  const observed = new Set(samples.map(({ text }) => text));
  for (const label of [
    "true answer",
    "config",
    "n",
    "marginal",
    "conditional",
    "coverage",
    "abstention",
    "accuracy when answering",
  ]) {
    expect(observed.has(label), `${label} was not inspected`).toBe(true);
  }
  for (const sample of samples) {
    expect(sample.fontSize, `${sample.text} is too small`).toBeGreaterThanOrEqual(11);
    expect(sample.contrast, `${sample.text} lacks 4.5:1 contrast`).toBeGreaterThanOrEqual(4.5);
  }
});

test("amber warning cards and badges meet rendered contrast floors", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/verify");
  await page.locator("textarea").fill("{");
  await page.getByRole("button", { name: "verify signature" }).click();
  await expect(page.getByText("not checked", { exact: true })).toBeVisible();
  const warningSamples = await renderedTextSamples(
    page.locator(".bg-doubt-soft .text-doubt"),
  );

  await page.route("**/api/runs", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        runs: [
          {
            run_id: "run_unverifiable_contrast",
            state: "completed",
            created_at: "2026-09-10T00:00:00Z",
            org: "Contrast fixture",
            replay: false,
            verdict: "unverifiable",
          },
        ],
      }),
    }),
  );
  await page.goto("/runs");
  const badge = page.getByText("unverifiable", { exact: true });
  await expect(badge).toBeVisible();
  const badgeSamples = await renderedTextSamples(badge);

  expect(warningSamples.length).toBeGreaterThanOrEqual(2);
  expect(badgeSamples).toHaveLength(1);
  for (const sample of [...warningSamples, ...badgeSamples]) {
    expect(sample.contrast, `${sample.text} lacks 4.5:1 contrast`).toBeGreaterThanOrEqual(4.5);
  }
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

test("phone ledger wraps a maximum-length unbroken organization name", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const organization = "A".repeat(120);
  await page.route("**/api/runs", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        runs: [
          {
            run_id: "run_boundary_name",
            state: "completed",
            created_at: "2026-09-10T00:00:00Z",
            org: organization,
            replay: true,
            verdict: "verified",
          },
        ],
      }),
    }),
  );
  await page.goto("/runs");
  const name = page.getByText(organization, { exact: true });
  await expect(name).toBeVisible();
  // A clipped `truncate` span keeps the document inside the viewport and
  // still reads as visible, so the document-level check alone passed on the
  // old markup. The span's own scrollWidth exceeds its clientWidth only when
  // the name is cut off; a wrapped name fits.
  // getByText resolves to the innermost element holding the name. If that is
  // ever an inline wrapper (a link, a highlight), measure the nearest
  // laid-out ancestor, since an inline box reports 0 for both widths.
  const span = await name.evaluate((el) => {
    let box: Element = el;
    while (box.parentElement && getComputedStyle(box).display === "inline") {
      box = box.parentElement;
    }
    return { client: box.clientWidth, scroll: box.scrollWidth };
  });
  // Zero would pass the wrap check with no signal, so the measured box has
  // to have real width first.
  expect(span.client, "organization name span is not a laid-out box").toBeGreaterThan(0);
  expect(span.scroll, "organization name is clipped instead of wrapped").toBeLessThanOrEqual(
    span.client + 1,
  );
  const width = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(width.scroll).toBeLessThanOrEqual(width.client + 1);
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
        recovery_blocked: 0,
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
  await expect(page.getByRole("cell", { name: "no_dead_end" })).toBeVisible();
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
        recovery_blocked: 0,
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
        recovery_blocked: 0,
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
        recovery_blocked: 0,
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

test("transport rotation is visible without falsely failing the call", async ({ page }) => {
  const runId = "run_transport_blocked";
  await page.addInitScript((id) => {
    sessionStorage.setItem(
      `attest:run-token:${id}`,
      "transport-blocked-capability-token-1234567890abcdef",
    );
  }, runId);
  await page.route(`**/internal/runs/${runId}`, async (route) => {
    await route.fulfill({
      json: {
        run_id: runId,
        state: "submitted",
        created_at: "2026-09-09T20:00:00Z",
        updated_at: "2026-09-09T20:01:00Z",
        published: false,
        provider: "live",
        payload: {
          error: "CALL-E transport no longer matches the original dispatch.",
          stage: "transport_identity_mismatch",
        },
        blocked: {
          error: "CALL-E transport no longer matches the original dispatch.",
          stage: "transport_identity_mismatch",
        },
        has_audio: false,
      },
    });
  });

  await page.goto(`/runs/${runId}`);
  await expect(page.getByRole("region", { name: "Run recovery blocked" })).toBeVisible();
  await expect(page.getByText(/restore the original CALL-E transport/i)).toBeVisible();
  await expect(page.getByText(/call failed at stage/i)).toHaveCount(0);
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
