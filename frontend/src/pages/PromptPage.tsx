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
          FILM. A fixed, full-viewport 8 second extreme-macro film: a cobalt ink
          line drawn across handmade paper, the camera traveling the wet groove,
          ending in a seal-like ink bloom. The film sits behind a paper-gradient
          veil at 55 percent opacity and is scrubbed by scroll position: a
          ScrollVideo component reads the real duration from loadedmetadata,
          lerps a target progress in one requestAnimationFrame loop, and never
          re-renders React per frame. Without the film, layered radial paper
          gradients carry the page.
        </p>
        <p>
          NARRATIVE. Six chapters over roughly 550vh telling one verification
          call: hero claim (characters resolve from blur, staggered), the
          problem (half of directory listings are wrong; stat instruments ~50%,
          18%, 44.8%), the disclosed call (a transcript sheet whose lines arrive
          as you scroll), the evidence (a citation mark sweeps across the
          answer; a match-weight meter fills to +1.36 bits), the guarantee (an
          SVG coverage line draws itself against a dashed ideal; 90.3% coverage,
          26.7% abstention, 94.5% accuracy when answering, all regenerated from
          a seeded eval), and a commercial close with two CTAs into the console
          and the calibration page.
        </p>
        <p>
          MOTION SYSTEM. Lenis smooth scrolling driven from the GSAP ticker.
          All timelines scoped in one gsap.context and reverted on unmount.
          ScrollTrigger scrubs, no time-based autoplay except the hero reveal.
          An AutoTour control (fixed, bottom right) drives a single linear GSAP
          tween through Lenis over about 45 seconds; wheel, touch, pointer, and
          paging keys pause it; Escape stops it without moving the reader;
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
