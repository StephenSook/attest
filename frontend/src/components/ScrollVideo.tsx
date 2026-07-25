import { useEffect, useRef } from "react";

/* Fixed, full-screen hero film scrubbed by scroll progress.

   The film's REAL duration is read from loadedmetadata, never hardcoded.
   Scrubbing happens in one rAF loop with a lerped target, touching the DOM
   through refs only: no React re-renders per frame. If the film is missing
   or reduced motion is requested, the layered paper fallback carries the
   page on its own. */
export default function ScrollVideo({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return; // static first frame is the reduced-motion experience
    }

    let duration = 0;
    let target = 0;
    let current = 0;
    let frame = 0;

    const onMeta = () => {
      duration = video.duration;
    };
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      target = max > 0 ? window.scrollY / max : 0;
    };
    const loop = () => {
      if (duration > 0) {
        current += (target - current) * 0.12;
        const clamped = Math.min(Math.max(current, 0), 1);
        // Leave a hair before the end so the last frame holds cleanly.
        video.currentTime = clamped * Math.max(duration - 0.05, 0);
      }
      frame = requestAnimationFrame(loop);
    };

    video.addEventListener("loadedmetadata", onMeta);
    if (video.readyState >= 1) onMeta();
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    frame = requestAnimationFrame(loop);
    return () => {
      video.removeEventListener("loadedmetadata", onMeta);
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="landing-film" aria-hidden="true">
      <video
        ref={videoRef}
        src={src}
        muted
        playsInline
        preload="auto"
        tabIndex={-1}
      />
      <div className="landing-film-veil" />
    </div>
  );
}
