import { useEffect, useRef } from "react";

/* Fixed, full-screen hero film scrubbed by scroll progress, decoder-safe.

   The failure mode this component exists to prevent: assigning
   video.currentTime on every animation frame floods the decoder with seeks.
   On machines without cheap hardware decode, each mid-file seek re-decodes
   from the previous keyframe, the main thread starves, and because Lenis
   applies scroll inside the same rAF clock, scrolling itself freezes.

   Rules, per the site spec:
   - one rAF loop eases an internal playhead toward the scroll target with
     frame-rate-independent exponential damping
   - never issue a new seek while the decoder is still seeking
   - while seeking, only the newest eased value is retained; it drains
     through seeked (or requestVideoFrameCallback where available)
   - no seek for a movement smaller than one output frame, and none at all
     once the playhead has settled
   - a stuck decoder is released by a watchdog so one lost event can never
     freeze the film

   The film's REAL duration is read from loadedmetadata, never hardcoded.
   DOM is touched through refs only: no React re-renders per frame. */

const DAMPING_PER_SECOND = 7; // higher = snappier catch-up to the scroll bar
const MIN_SEEK_DELTA = 1 / 30; // never seek less than one 30fps frame of movement
const SETTLE_EPSILON = 0.004; // seconds: playhead considered settled
const SEEK_WATCHDOG_MS = 600; // release a decoder that never reports seeked
const END_HOLD = 0.05; // seconds held back so the final frame stays clean

export default function ScrollVideo({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const bufferRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    const frame = frameRef.current;
    if (!video || !frame) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return; // static first frame is the reduced-motion experience
    }

    let duration = 0;
    let progress = 0; // scroll target, 0..1
    let playhead = 0; // eased position, seconds
    let lastSought = -1;
    let seeking = false;
    let seekIssuedAt = 0;
    let seekBlockedUntil = 0; // cooldown after a watchdog release
    let prevNow = performance.now();
    let rafId = 0;
    let failed = false;

    const onMeta = () => {
      duration = video.duration;
    };
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      progress = max > 0 ? Math.min(Math.max(window.scrollY / max, 0), 1) : 0;
    };
    const seekSettled = () => {
      seeking = false;
    };
    const onError = () => {
      // The layered paper background carries the page without the film.
      failed = true;
      frame.style.display = "none";
    };
    const onProgress = () => {
      if (!bufferRef.current || !duration || video.buffered.length === 0) return;
      const fraction = video.buffered.end(video.buffered.length - 1) / duration;
      bufferRef.current.style.transform = `scaleX(${Math.min(fraction, 1)})`;
      bufferRef.current.style.opacity = fraction >= 0.999 ? "0" : "1";
    };
    const onCanPlay = () => {
      video.style.opacity = "";
    };

    const issueSeek = (time: number) => {
      seeking = true;
      seekIssuedAt = performance.now();
      lastSought = time;
      video.currentTime = time;
      // Prefer frame presentation as the settle signal where supported: the
      // seeked event can fire before the frame is actually displayed. Only a
      // frame near the sought time counts; a stale queued frame re-arms.
      if ("requestVideoFrameCallback" in video) {
        const confirm = (_: number, meta: VideoFrameCallbackMetadata) => {
          if (!seeking) return;
          if (Math.abs(meta.mediaTime - lastSought) < 0.08) seekSettled();
          else video.requestVideoFrameCallback(confirm);
        };
        video.requestVideoFrameCallback(confirm);
      }
    };

    const loop = (now: number) => {
      rafId = requestAnimationFrame(loop);
      if (failed) return;
      const dt = Math.min((now - prevNow) / 1000, 0.1);
      prevNow = now;
      if (duration <= 0) return;

      const targetTime = progress * Math.max(duration - END_HOLD, 0);
      playhead += (targetTime - playhead) * (1 - Math.exp(-DAMPING_PER_SECOND * dt));
      if (Math.abs(targetTime - playhead) < SETTLE_EPSILON) playhead = targetTime;

      if (seeking && now - seekIssuedAt > SEEK_WATCHDOG_MS) {
        // The decoder is genuinely slow (or an event was lost). Release it,
        // but rate-limit further seeks so a slow decoder gets breathing room
        // instead of a reopened seek storm.
        seeking = false;
        seekBlockedUntil = now + SEEK_WATCHDOG_MS;
      }
      if (
        !seeking &&
        now >= seekBlockedUntil &&
        Math.abs(playhead - lastSought) >= MIN_SEEK_DELTA
      ) {
        issueSeek(playhead);
      }
    };

    video.addEventListener("loadedmetadata", onMeta);
    if (video.readyState >= 1) onMeta();
    video.addEventListener("seeked", seekSettled);
    video.addEventListener("error", onError);
    video.addEventListener("progress", onProgress);
    video.addEventListener("canplay", onCanPlay);
    if (video.readyState < 3) video.style.opacity = "0";
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    rafId = requestAnimationFrame(loop);

    // Subtle desktop mouse parallax; never on touch devices.
    const fine = window.matchMedia("(pointer: fine)").matches;
    const onPointer = (event: PointerEvent) => {
      const dx = (event.clientX / window.innerWidth - 0.5) * 10;
      const dy = (event.clientY / window.innerHeight - 0.5) * 6;
      frame.style.transform = `scale(1.06) translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`;
    };
    if (fine) window.addEventListener("pointermove", onPointer, { passive: true });

    return () => {
      // StrictMode-safe: listeners and the loop go, the src stays.
      video.removeEventListener("loadedmetadata", onMeta);
      video.removeEventListener("seeked", seekSettled);
      video.removeEventListener("error", onError);
      video.removeEventListener("progress", onProgress);
      video.removeEventListener("canplay", onCanPlay);
      window.removeEventListener("scroll", onScroll);
      if (fine) window.removeEventListener("pointermove", onPointer);
      cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <div className="landing-film" aria-hidden="true">
      <div ref={frameRef} className="landing-film-frame">
        <video
          ref={videoRef}
          src={src}
          muted
          playsInline
          preload="auto"
          disablePictureInPicture
          tabIndex={-1}
        />
      </div>
      <div className="landing-film-veil" />
      <div ref={bufferRef} className="landing-film-buffer" />
    </div>
  );
}
