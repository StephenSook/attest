import { gsap } from "gsap";
import { useEffect, useRef, useState } from "react";
import { getLenis } from "./SmoothScroll";
import "./AutoTour.css";

const TOUR_SECONDS = 20; // full page at 1x; 2x halves it

/* Minimal fixed tour control. A single linear GSAP tween drives scroll
   position through Lenis (or native scrollTo as the fallback). Progress is
   normalized to document height and rendered through refs: no React
   re-render per animation frame. Any manual input pauses; Escape stops
   without moving the reader's position; leaving the page kills the tween. */
export default function AutoTour() {
  const [state, setState] = useState<"idle" | "touring" | "paused" | "done">("idle");
  const [speed, setSpeed] = useState<1 | 2>(1);
  const tween = useRef<gsap.core.Tween | null>(null);
  const ringRef = useRef<SVGCircleElement | null>(null);
  const pctRef = useRef<HTMLSpanElement | null>(null);
  const restartRef = useRef<HTMLButtonElement | null>(null);
  const speedRef = useRef<1 | 2>(1);
  speedRef.current = speed;

  useEffect(() => {
    const pause = () => {
      if (tween.current?.isActive()) {
        tween.current.pause();
        setState("paused");
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        tween.current?.kill();
        tween.current = null;
        setState("idle");
        return;
      }
      if (
        ["PageUp", "PageDown", "Home", "End", " ", "ArrowUp", "ArrowDown"].includes(
          event.key,
        )
      ) {
        pause();
      }
    };
    window.addEventListener("wheel", pause, { passive: true });
    window.addEventListener("touchstart", pause, { passive: true });
    window.addEventListener("pointerdown", pause);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", pause);
      window.removeEventListener("touchstart", pause);
      window.removeEventListener("pointerdown", pause);
      window.removeEventListener("keydown", onKey);
      tween.current?.kill();
      tween.current = null;
    };
  }, []);

  const paint = (y: number, max: number) => {
    const p = max > 0 ? Math.min(y / max, 1) : 0;
    if (ringRef.current) {
      ringRef.current.style.strokeDashoffset = String(88 * (1 - p));
    }
    if (pctRef.current) {
      pctRef.current.textContent = `${Math.round(p * 100)}%`;
    }
    if (restartRef.current) {
      restartRef.current.style.visibility = p > 0.02 ? "visible" : "hidden";
    }
  };

  const begin = (fromTop: boolean) => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    if (max <= 0) return; // nothing to tour on a viewport-height document
    const startY = fromTop ? 0 : window.scrollY;
    if (fromTop) {
      const lenis = getLenis();
      if (lenis) lenis.scrollTo(0, { immediate: true });
      else window.scrollTo(0, 0);
    }
    const proxy = { y: startY };
    const remaining = Math.max(0, 1 - startY / max);
    tween.current?.kill();
    tween.current = gsap.to(proxy, {
      y: max,
      duration: TOUR_SECONDS * remaining,
      ease: "none",
      onUpdate: () => {
        const lenis = getLenis();
        if (lenis) lenis.scrollTo(proxy.y, { immediate: true });
        else window.scrollTo(0, proxy.y);
        paint(proxy.y, max);
      },
      onComplete: () => setState("done"),
    });
    tween.current.timeScale(speedRef.current);
    setState("touring");
  };

  const toggle = () => {
    if (state === "touring") {
      tween.current?.pause();
      setState("paused");
      return;
    }
    if (state === "paused" && tween.current) {
      tween.current.resume();
      setState("touring");
      return;
    }
    // idle starts from wherever the reader is; done replays from the top
    begin(state === "done");
  };

  const flipSpeed = () => {
    const next = speed === 1 ? 2 : 1;
    setSpeed(next);
    tween.current?.timeScale(next);
  };

  const restart = () => begin(true);

  const label =
    state === "touring"
      ? "pause"
      : state === "paused"
        ? "resume"
        : state === "done"
          ? "replay"
          : "auto tour";

  return (
    <div className="auto-tour">
      <button
        ref={restartRef}
        type="button"
        onClick={restart}
        className="auto-tour-restart"
        style={{ visibility: "hidden" }}
        aria-label="Restart the guided tour from the top"
      >
        restart
      </button>
      <button
        type="button"
        onClick={flipSpeed}
        className="auto-tour-speed"
        aria-label={`Tour speed ${speed}x, click to switch`}
      >
        {speed}x
      </button>
      <button
        type="button"
        onClick={toggle}
        className="auto-tour-button"
        aria-label={state === "touring" ? "Pause the guided tour" : "Play the guided tour"}
      >
        <svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true">
          <circle cx="16" cy="16" r="14" className="auto-tour-track" />
          <circle
            ref={ringRef}
            cx="16"
            cy="16"
            r="14"
            className="auto-tour-ring"
            strokeDasharray="88"
            strokeDashoffset="88"
          />
          {state === "touring" ? (
            <g className="auto-tour-glyph">
              <rect x="12" y="11" width="3" height="10" />
              <rect x="17" y="11" width="3" height="10" />
            </g>
          ) : (
            <path d="M13 11l8 5-8 5z" className="auto-tour-glyph" />
          )}
        </svg>
        <span className="auto-tour-label">
          {label} <span ref={pctRef} className="auto-tour-pct" />
        </span>
      </button>
      <p aria-live="polite" className="sr-only">
        {state === "touring"
          ? "Guided tour playing. Scroll or press Escape to take over."
          : state === "paused"
            ? "Guided tour paused."
            : state === "done"
              ? "Guided tour finished."
              : "Guided tour stopped."}
      </p>
    </div>
  );
}
