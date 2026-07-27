import { NavLink, Outlet } from "react-router-dom";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 text-sm rounded-md transition-colors ${
    isActive
      ? "bg-ink text-paper"
      : "text-ink-soft hover:text-ink hover:bg-paper-deep"
  }`;

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-paper/90 backdrop-blur sticky top-0 z-20">
        <div className="mx-auto flex max-w-5xl items-baseline justify-between px-6 py-4">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-2xl font-bold tracking-tight">
              Attest
            </span>
            <span className="font-evidence text-[11px] uppercase tracking-[0.2em] text-ink-faint">
              the phone agent that refuses to guess
            </span>
          </div>
          <nav aria-label="Console" className="flex gap-1">
            <NavLink to="/runs" className={navClass}>
              Verification runs
            </NavLink>
            <NavLink to="/calibration" className={navClass}>
              Calibration
            </NavLink>
            <NavLink to="/verify" className={navClass}>
              Verify
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-5xl px-6 pb-10">
        <p className="font-evidence text-[11px] text-ink-faint">
          Public view serves labeled replays of real recorded runs. Live calls
          are operator-gated. Phone numbers are always masked.{" "}
          <a
            href="https://github.com/StephenSook/attest/releases/latest"
            target="_blank"
            rel="noreferrer"
            className="text-trust hover:text-ink"
          >
            Get Attest Pocket (Android APK; iOS on TestFlight)
          </a>
          .
        </p>
      </footer>
    </div>
  );
}
