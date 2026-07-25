import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRuns, type RunSummary } from "../api";

const stateTone: Record<string, string> = {
  completed: "text-trust",
  failed: "text-contra",
  canceled: "text-ink-faint",
  submitted: "text-doubt",
  created: "text-ink-faint",
};

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRuns()
      .then((data) => setRuns(data.runs))
      .catch(() => setError("The backend is waking up. Give it a moment and reload."));
  }, []);

  if (error) {
    return <p className="font-evidence text-sm text-ink-soft">{error}</p>;
  }
  if (runs === null) {
    return <p className="font-evidence text-sm text-ink-faint">Opening the ledger...</p>;
  }

  return (
    <section aria-labelledby="runs-heading">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 id="runs-heading" className="font-display text-4xl font-semibold">
            Verification runs
          </h1>
          <p className="mt-2 max-w-2xl text-ink-soft">
            One disclosed call per record. Every answer carries its supporting
            span from the transcript, or an explicit abstention.
          </p>
        </div>
        <Link
          to="/runs/new"
          className="rounded-md border border-rule px-4 py-2 font-evidence text-xs uppercase tracking-widest text-ink transition-colors hover:border-trust hover:text-trust focus-visible:outline-2 focus-visible:outline-trust"
        >
          + live verification
        </Link>
      </div>
      <ul className="ledger mt-8 border-t border-rule">
        {runs.map((run, index) => (
          <motion.li
            key={run.run_id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05, duration: 0.3 }}
          >
            <Link
              to={`/runs/${run.run_id}`}
              className="flex items-baseline justify-between gap-4 border-b border-rule py-[14px] hover:bg-paper-deep/60 focus-visible:outline-2 focus-visible:outline-trust"
            >
              <span className="flex items-baseline gap-3 min-w-0">
                <span className="font-evidence text-xs text-ink-faint shrink-0">
                  {run.created_at.slice(0, 10)}
                </span>
                <span className="truncate font-medium">
                  {run.org ?? "Unnamed record"}
                </span>
                {run.replay && (
                  <span className="shrink-0 rounded border border-rule px-1.5 font-evidence text-[10px] uppercase tracking-widest text-ink-faint">
                    replay of real call
                  </span>
                )}
              </span>
              <span
                className={`font-evidence text-xs uppercase tracking-widest ${stateTone[run.state] ?? "text-ink-faint"}`}
              >
                {run.state}
              </span>
            </Link>
          </motion.li>
        ))}
      </ul>
      {runs.length === 0 && (
        <p className="mt-6 font-evidence text-sm text-ink-faint">
          No runs recorded yet.
        </p>
      )}
    </section>
  );
}
