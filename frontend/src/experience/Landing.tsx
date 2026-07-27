import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useLayoutEffect, useRef } from "react";
import { Link } from "react-router-dom";
import AutoTour from "../components/AutoTour";
import ScrollVideo from "../components/ScrollVideo";
import SmoothScroll from "../components/SmoothScroll";
import "./Landing.css";

gsap.registerPlugin(ScrollTrigger);

const Chars = ({ text }: { text: string }) => (
  <>
    {text.split("").map((char, i) => (
      <span key={i} className="char" aria-hidden="true">
        {char === " " ? " " : char}
      </span>
    ))}
  </>
);

const CALL_LINES = [
  { who: "bot", at: "0:00", text: "Hi, this is an automated assistant calling to verify directory information. This call may be recorded." },
  { who: "bot", at: "0:14", text: "Is the practice currently accepting new patients?" },
  { who: "user", at: "0:19", text: "Yep." },
  { who: "bot", at: "0:21", text: "Got it, thanks." },
];

export default function Landing() {
  const root = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ctx = gsap.context(() => {
      if (reduced) {
        gsap.set(".char, .ch-rise, .call-line, .ev-mark, .meter-fill", {
          clearProps: "all",
          opacity: 1,
        });
        return;
      }

      // Hero: characters resolve out of blur, the dragonfly move, on paper.
      gsap.fromTo(
        ".hero .char",
        { opacity: 0, filter: "blur(10px)", y: 14 },
        {
          opacity: 1,
          filter: "blur(0px)",
          y: 0,
          stagger: 0.028,
          duration: 0.9,
          ease: "power2.out",
          delay: 0.2,
        },
      );
      // Anchored to the hero itself so progress is exactly zero at the top
      // of the page on every viewport; a chapter-relative trigger left the
      // hero pre-faded on short screens (caught by Lighthouse contrast).
      gsap.to(".hero-inner", {
        opacity: 0,
        y: -60,
        scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom 40%", scrub: true },
      });

      // Generic chapter rise-ins.
      gsap.utils.toArray<HTMLElement>(".ch-rise").forEach((el) => {
        gsap.fromTo(
          el,
          { opacity: 0, y: 44 },
          {
            opacity: 1,
            y: 0,
            ease: "none",
            scrollTrigger: { trigger: el, start: "top 88%", end: "top 55%", scrub: true },
          },
        );
      });

      // Chapter 3: transcript lines arrive one by one.
      gsap.utils.toArray<HTMLElement>(".call-line").forEach((el, i) => {
        gsap.fromTo(
          el,
          { opacity: 0, x: -18 },
          {
            opacity: 1,
            x: 0,
            ease: "none",
            scrollTrigger: {
              trigger: ".ch-call",
              start: `top+=${i * 90} 70%`,
              end: `top+=${i * 90 + 90} 45%`,
              scrub: true,
            },
          },
        );
      });

      // Chapter 4: the evidence mark sweeps across "Yep."
      gsap.fromTo(
        ".ev-mark",
        { scaleX: 0 },
        {
          scaleX: 1,
          transformOrigin: "left center",
          ease: "none",
          scrollTrigger: { trigger: ".ch-evidence", start: "top 60%", end: "top 25%", scrub: true },
        },
      );
      gsap.fromTo(
        ".meter-fill",
        { width: "0%" },
        {
          width: "68%",
          ease: "none",
          scrollTrigger: { trigger: ".bits-meter", start: "top 80%", end: "top 40%", scrub: true },
        },
      );

      // Stat numbers roll up to their printed value as they scrub in. The
      // printed JSX literal stays the source of truth (and stays test-pinned
      // to metrics.json); this only animates toward it.
      gsap.utils.toArray<HTMLElement>(".stat-n").forEach((el) => {
        const final = el.textContent ?? "";
        const match = /^([~+]?)(\d+(?:\.\d+)?)(.*)$/.exec(final);
        if (!match) return;
        const [, prefix, num, suffix] = match;
        const value = parseFloat(num);
        const decimals = num.includes(".") ? num.split(".")[1].length : 0;
        const counter = { v: 0 };
        gsap.to(counter, {
          v: value,
          ease: "none",
          scrollTrigger: { trigger: el, start: "top 85%", end: "top 45%", scrub: true },
          onUpdate: () => {
            el.textContent = `${prefix}${counter.v.toFixed(decimals)}${suffix}`;
          },
        });
      });

      // Palette shift for the proof chapters.
      ScrollTrigger.create({
        trigger: ".ch-guarantee",
        start: "top 70%",
        end: "bottom top",
        toggleClass: { targets: ".landing", className: "veil-deep" },
      });

      // Chapter 5: the coverage line draws itself against the ideal.
      const path = document.querySelector<SVGPathElement>(".cov-line");
      if (path) {
        const length = path.getTotalLength();
        gsap.fromTo(
          path,
          { strokeDasharray: length, strokeDashoffset: length },
          {
            strokeDashoffset: 0,
            ease: "none",
            scrollTrigger: { trigger: ".ch-guarantee", start: "top 70%", end: "top 15%", scrub: true },
          },
        );
      }
    }, root);
    return () => ctx.revert();
  }, []);

  return (
    <SmoothScroll>
      <div ref={root} className="landing">
        <ScrollVideo src="/hero.mp4" srcMobile="/hero-720.mp4" poster="/hero-poster.jpg" />

        {/* Notary registration marks framing the viewport. */}
        <div className="frame-marks" aria-hidden="true">
          <span>A</span>
          <span>T</span>
          <span>S</span>
          <span>T</span>
        </div>

        <header className="landing-top">
          <span className="font-display text-xl font-bold">Attest</span>
          <nav className="landing-nav">
            <Link to="/runs">console</Link>
            <Link to="/calibration">calibration</Link>
          </nav>
        </header>

        <section className="chapter hero" aria-label="Attest">
          <div className="hero-inner">
            <p className="kicker ch-rise">for every record only a phone call can verify</p>
            <h1 className="hero-line">
              <span className="sr-only">The phone agent that refuses to guess.</span>
              <Chars text="The phone agent" />
              <br />
              <Chars text="that refuses to guess." />
            </h1>
            <p className="scroll-cue" aria-hidden="true">
              scroll <span className="cue-line" />
            </p>
          </div>
        </section>

        <section className="chapter ch-problem" aria-label="The problem">
          <h2 className="ch-title ch-rise">
            Roughly half of provider directory listings are wrong.
          </h2>
          <p className="ch-body ch-rise">
            People call number after number from their insurer's list and reach
            practices that closed, moved, or never took the plan. The record
            exists. The record lies.
          </p>
          <div className="stat-row ch-rise" role="list">
            <div role="listitem" className="stat">
              <span className="stat-n">~50%</span>
              <span className="stat-l">listings inaccurate in a federal audit</span>
            </div>
            <div role="listitem" className="stat">
              <span className="stat-n">18%</span>
              <span className="stat-l">of secret-shopper calls reached a bookable appointment</span>
            </div>
            <div role="listitem" className="stat">
              <span className="stat-n">44.8%</span>
              <span className="stat-l">still wrong when re-audited months later</span>
            </div>
          </div>
        </section>

        <section className="chapter ch-call" aria-label="The call">
          <h2 className="ch-title ch-rise">One disclosed call.</h2>
          <p className="ch-body ch-rise">
            Attest says what it is and why it is calling in the same breath,
            then asks what a patient would ask.
          </p>
          <div className="call-sheet">
            {CALL_LINES.map((line) => (
              <p key={line.at} className={`call-line call-${line.who}`}>
                <span className="call-at">{line.at}</span>
                <span className="call-who">{line.who}</span>
                <span className="call-text">
                  {line.text === "Yep." ? (
                    <span className="ev-holder">
                      Yep.
                      <span className="ev-mark" aria-hidden="true" />
                    </span>
                  ) : (
                    line.text
                  )}
                </span>
              </p>
            ))}
          </div>
        </section>

        <section className="chapter ch-evidence" aria-label="The evidence">
          <h2 className="ch-title ch-rise">Every answer carries its receipt.</h2>
          <p className="ch-body ch-rise">
            Each extracted field cites the verbatim span that supports it, down
            to the character. No span, no answer: the system abstains instead.
          </p>
          <div className="bits-meter ch-rise" aria-label="Match weight example">
            <div className="meter-rail">
              <div className="meter-fill" />
            </div>
            <p className="meter-caption">
              accepting new patients agrees with the record: +1.36 bits of
              evidence toward a verified listing
            </p>
          </div>
        </section>

        <section className="chapter ch-guarantee" aria-label="The guarantee">
          <h2 className="ch-title ch-rise">Confidence with a warranty.</h2>
          <p className="ch-body ch-rise">
            Split conformal calibration turns trust into a measured promise: at
            a 90 percent target, the true answer landed inside the prediction
            set 90.3 percent of the time on held-out data.
          </p>
          <div className="cov-wrap ch-rise">
            <svg viewBox="0 0 400 240" className="cov-chart" role="img" aria-label="Reliability: empirical coverage tracks the target">
              <line x1="40" y1="200" x2="380" y2="20" className="cov-ideal" />
              <path d="M40 208 L108 186 L176 186 L244 168 L312 148 L380 26" className="cov-line" />
              <text x="374" y="16" className="cov-note">ideal</text>
              <text x="40" y="228" className="cov-note">70% target</text>
              <text x="340" y="228" className="cov-note">95%</text>
            </svg>
            <div className="stat-row">
              <div className="stat">
                <span className="stat-n">90.3%</span>
                <span className="stat-l">empirical coverage at a 90% target</span>
              </div>
              <div className="stat">
                <span className="stat-n">57.7%</span>
                <span className="stat-l">of calls end in an honest abstention</span>
              </div>
              <div className="stat">
                <span className="stat-n">96.9%</span>
                <span className="stat-l">accuracy when it does answer</span>
              </div>
            </div>
          </div>
        </section>

        <section className="chapter ch-close" aria-label="Get started">
          <h2 className="ch-title ch-rise">Verification you can audit.</h2>
          <p className="ch-body ch-rise">
            Watch a real recorded run, read the arithmetic behind every verdict,
            and regenerate every number from one seeded command.
          </p>
          <div className="cta-row ch-rise">
            <Link to="/runs" className="cta-primary">
              Open the console
            </Link>
            <Link to="/calibration" className="cta-secondary">
              See the method
            </Link>
          </div>
          <div className="pocket-row ch-rise">
            <img
              src="/android-apk-qr.png"
              width={96}
              height={96}
              alt="QR code to install Attest Pocket for Android"
              className="pocket-qr"
            />
            <div>
              <p className="pocket-title">Attest Pocket</p>
              <p className="pocket-note">
                The receipt in your pocket. Scan for the Android app, or{" "}
                <a
                  href="https://github.com/StephenSook/attest/releases/latest"
                  target="_blank"
                  rel="noreferrer"
                >
                  download the APK
                </a>
                . iOS via TestFlight on approval.
              </p>
            </div>
          </div>
          <div className="close-foot ch-rise">
            <Link to="/prompt">how this page was made</Link>
            <button
              type="button"
              onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
            >
              back to the top
            </button>
          </div>
        </section>

        <AutoTour />
      </div>
    </SmoothScroll>
  );
}
