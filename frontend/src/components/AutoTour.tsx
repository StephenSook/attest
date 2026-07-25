import { gsap } from "gsap";
import { useEffect, useRef, useState } from "react";
import { getLenis } from "./SmoothScroll";
import "./AutoTour.css";

const TOUR_SECONDS = 45;

/* Minimal fixed tour control. A single linear GSAP tween drives scroll
   position through Lenis (or native scrollTo as the fallback). Progress is
   normalized to document height. Any manual input pauses; Escape stops
   without moving the reader's position; leaving the page kills the tween.
   Status changes are announced through an aria-live region. */
export default function AutoTour() {
  const [state, setState] = useState<"idle" | "touring" | "paused">("idle");
  const tween = useRef<gsap.core.Tween | null>(null);
  const ringRef = useRef<SVGCircleElement | null>(null);

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

  const start = () => {
    if (state === "paused" && tween.current) {
      tween.current.resume();
      setState("touring");
      return;
    }
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const proxy = { y: window.scrollY };
    const remaining = Math.max(0, 1 - window.scrollY / max);
    tween.current?.kill();
    tween.current = gsap.to(proxy, {
      y: max,
      duration: TOUR_SECONDS * remaining,
      ease: "none",
      onUpdate: () => {
        const lenis = getLenis();
        if (lenis) lenis.scrollTo(proxy.y, { immediate: true });
        else window.scrollTo(0, proxy.y);
        if (ringRef.current) {
          ringRef.current.style.strokeDashoffset = String(
            88 * (1 - proxy.y / max),
          );
        }
      },
      onComplete: () => setState("idle"),
    });
    setState("touring");
  };

  const toggle = () => {
    if (state === "touring") {
      tween.current?.pause();
      setState("paused");
    } else {
      start();
    }
  };

  return (
    <div className="auto-tour">
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
          {state === "touring" ? "pause" : state === "paused" ? "resume" : "auto tour"}
        </span>
      </button>
      <p aria-live="polite" className="sr-only">
        {state === "touring"
          ? "Guided tour playing. Scroll or press Escape to take over."
          : state === "paused"
            ? "Guided tour paused."
            : "Guided tour stopped."}
      </p>
    </div>
  );
}
