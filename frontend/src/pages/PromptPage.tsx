import { Link } from "react-router-dom";

/* The reconstruction brief: enough for another builder (human or agent) to
   recreate this landing page from scratch. */
export default function PromptPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link to="/" className="font-evidence text-xs text-ink-faint hover:text-ink">
        &larr; back to the page
      </Link>
      <h1 className="mt-4 font-display text-4xl font-semibold">
        How this page was made
      </h1>
      <p className="mt-3 text-ink-soft">
        A reconstruction brief for rebuilding the Attest landing experience.
      </p>
      <div className="ledger mt-8 space-y-[28px] font-evidence text-[13px] leading-[28px] text-ink">
        <p>
          BRAND. Attest: a phone agent that verifies directory listings with one
          disclosed call and refuses to guess. Notarial evidence-ledger
          aesthetic on warm paper (#faf9f5) with near-black ink (#191712), one
          trust blue (#2456d6), amber for doubt (#c25e00). Fraunces for display,
          IBM Plex Mono for evidence, Source Sans 3 for body. Persistent corner
          registration marks (A T S T) frame the viewport like a notarized page.
        </p>
        <p>
          FILM. A single continuous 8 second extreme-macro journey generated
          with Higgsfield Cinema Studio (pro mode, 16:9, linear speed, sound
          off): the camera starts inside the woven brass grille of a telephone
          handset, travels the copper wire as light, emerges onto cream
          archival paper where a nib writes in deep blue ink, and ends as a
          brass notary seal certifies the page. The raw 24fps take is
          motion-interpolated to 60fps and re-encoded with a keyframe every 8
          frames so scroll scrubbing seeks stay cheap on any machine.
        </p>
        <p>
          SCRUB ENGINE. The film sits fixed behind a paper-gradient veil and is
          scrubbed by scroll: ScrollVideo reads the real duration from
          loadedmetadata and eases an internal playhead toward the scroll
          target in one requestAnimationFrame loop with frame-rate-independent
          damping. Decoder safety is the point: it never issues a seek while
          one is in flight, retains only the newest target and drains it
          through seeked (or requestVideoFrameCallback where available), skips
          movements smaller than one output frame, stops seeking once settled,
          and a watchdog releases a stuck decoder. Subtle desktop-only mouse
          parallax; a buffered-progress hairline; layered paper gradients carry
          the page if the film fails. A repository test parses the shipped
          mp4's sync-sample table and fails if keyframes are sparser than one
          per half second.
        </p>
        <p>
          NARRATIVE. Six chapters over roughly 550vh telling one verification
          call: hero claim (characters resolve from blur, staggered), the
          problem (half of directory listings are wrong; stat instruments ~50%,
          18%, 44.8%), the disclosed call (a transcript sheet whose lines arrive
          as you scroll), the evidence (a citation mark sweeps across the
          answer; a match-weight meter fills to +1.36 bits), the guarantee (an
          SVG coverage line draws itself against a dashed ideal; 90.3% coverage,
          57.7% abstention, 96.9% accuracy when answering, all regenerated from
          a seeded eval), and a commercial close with two CTAs into the console
          and the calibration page.
        </p>
        <p>
          MOTION SYSTEM. Lenis smooth scrolling driven from the GSAP ticker.
          All timelines scoped in one gsap.context and reverted on unmount.
          ScrollTrigger scrubs, no time-based autoplay except the hero reveal.
          An AutoTour control (fixed, bottom right) drives a single linear GSAP
          tween through Lenis, 20 seconds at 1x with a 2x toggle, live percent
          readout, and a restart control past 2 percent; wheel, touch, pointer,
          and paging keys pause it; Escape stops it without moving the reader;
          route changes kill it; progress lives in a stroke-dashoffset ring;
          status is announced via aria-live. prefers-reduced-motion disables
          Lenis, the film scrub, and every scrub tween, leaving static,
          fully-readable chapters.
        </p>
        <p>
          QUALITY BARS. Semantic sections with aria-labels, keyboard-operable
          controls with visible focus, no horizontal overflow (overflow-x:
          clip), authored mobile breakpoints, real buttons and links only, no
          fake loading states, and commercial copy with real numbers from the
          shipped evaluation, no invented claims.
        </p>
      </div>
    </main>
  );
}
