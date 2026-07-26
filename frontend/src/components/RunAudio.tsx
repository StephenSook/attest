import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import WaveSurfer from "wavesurfer.js";

export type RunAudioHandle = {
  seekTo: (seconds: number) => void;
};

/* Waveform evidence player. The CALL-E API exposes no recording URL, so any
   audio here was captured on our own end of a consented call; the provenance
   label always says exactly where it came from. Clicking an evidence span in
   the transcript seeks here; playback time flows back up so the transcript
   can light the active turn. */
const RunAudio = forwardRef<
  RunAudioHandle,
  { src: string; note?: string; onTime: (seconds: number) => void }
>(function RunAudio({ src, note, onTime }, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const surferRef = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const surfer = WaveSurfer.create({
      container,
      url: src,
      height: 56,
      waveColor: "#c9c4b4",
      progressColor: "#2456d6",
      cursorColor: "#191712",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
    });
    surferRef.current = surfer;
    surfer.on("timeupdate", onTime);
    surfer.on("play", () => setPlaying(true));
    surfer.on("pause", () => setPlaying(false));
    surfer.on("finish", () => setPlaying(false));
    surfer.on("error", () => setFailed(true));
    return () => {
      surferRef.current = null;
      surfer.destroy();
    };
    // The player binds to one source for its lifetime; onTime is stable
    // enough via the parent's useCallback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  useImperativeHandle(ref, () => ({
    seekTo: (seconds: number) => {
      const surfer = surferRef.current;
      if (!surfer) return;
      surfer.setTime(seconds);
      if (!surfer.isPlaying()) void surfer.play();
    },
  }));

  if (failed) return null;

  return (
    <div className="mt-4 rounded-lg border border-rule bg-white/60 p-4" data-testid="run-audio">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => void surferRef.current?.playPause()}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-rule bg-paper text-ink transition-colors hover:border-trust hover:text-trust focus-visible:outline-2 focus-visible:outline-trust"
          aria-label={playing ? "Pause the call audio" : "Play the call audio"}
        >
          {playing ? (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <rect x="3" y="2" width="4" height="12" fill="currentColor" />
              <rect x="9" y="2" width="4" height="12" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M4 2l10 6-10 6z" fill="currentColor" />
            </svg>
          )}
        </button>
        <div ref={containerRef} className="min-w-0 flex-1" />
      </div>
      <p className="mt-2 font-evidence text-[11px] text-ink-faint">
        {note ?? "audio captured on the receiving end of this consented call, builder line"}
        {" · "}click an evidence span to hear it in context
      </p>
    </div>
  );
});

export default RunAudio;
