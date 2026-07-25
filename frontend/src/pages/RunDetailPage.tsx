import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchRun,
  transcriptOf,
  type Claim,
  type RunDetail,
  type TranscriptTurn,
} from "../api";
import VerdictStamp from "../components/VerdictStamp";
import Waterfall from "../components/Waterfall";

function TurnLine({
  turn,
  index,
  claims,
  liveClaim,
}: {
  turn: TranscriptTurn;
  index: number;
  claims: Claim[];
  liveClaim: string | null;
}) {
  const marking = claims.find((c) => c.span?.turn === index);
  const isBot = turn.speaker === "bot";
  let body: React.ReactNode = turn.text;
  if (marking?.span) {
    const { char_start, char_end } = marking.span;
    body = (
      <>
        {turn.text.slice(0, char_start)}
        <mark
          className="evidence-span"
          data-live={liveClaim === marking.claim}
          title={`supporting span for ${marking.claim}`}
        >
          {turn.text.slice(char_start, char_end)}
        </mark>
        {turn.text.slice(char_end)}
      </>
    );
  }
  return (
    <li className="flex gap-4 border-b border-rule py-[6px] leading-[22px]">
      <span className="w-10 shrink-0 text-right font-evidence text-[11px] text-ink-faint">
        {String(Math.floor(turn.offset_seconds / 60)).padStart(1, "0")}:
        {String(turn.offset_seconds % 60).padStart(2, "0")}
      </span>
      <span
        className={`w-10 shrink-0 font-evidence text-[11px] uppercase ${isBot ? "text-ink-faint" : "text-trust"}`}
      >
        {isBot ? "bot" : "user"}
      </span>
      <span className={isBot ? "text-ink-soft" : "text-ink"}>{body}</span>
    </li>
  );
}

function ClaimCard({
  claim,
  onHover,
}: {
  claim: Claim;
  onHover: (claim: string | null) => void;
}) {
  const answerTone =
    claim.answer === "unknown"
      ? "text-ink-soft"
      : claim.answer === "yes"
        ? "text-trust"
        : "text-doubt";
  return (
    <div
      className="rounded-lg border border-rule bg-white/60 p-4"
      onMouseEnter={() => claim.span && onHover(claim.claim)}
      onMouseLeave={() => onHover(null)}
    >
      <p className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
        {claim.claim.replaceAll("_", " ")}
      </p>
      <p className={`font-display text-3xl font-semibold ${answerTone}`}>
        {claim.abstain ? "abstain" : claim.answer}
      </p>
      <p className="mt-1 font-evidence text-xs text-ink-soft">
        trust {claim.trust_score.toFixed(2)}
        {claim.hedged && <span className="text-doubt"> · hedged</span>}
      </p>
      <p className="mt-2 font-evidence text-xs text-ink-faint">
        {claim.span
          ? `evidence: "${claim.span.text}"`
          : "no supporting span: the call did not establish this, so no answer is given"}
      </p>
    </div>
  );
}

export default function RunDetailPage() {
  const { runId } = useParams();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveClaim, setLiveClaim] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    fetchRun(runId)
      .then(setDetail)
      .catch(() => setError("Could not load this run."));
  }, [runId]);

  if (error) return <p className="font-evidence text-sm text-contra">{error}</p>;
  if (!detail)
    return <p className="font-evidence text-sm text-ink-faint">Opening the record...</p>;

  const turns = transcriptOf(detail);
  const analysis = detail.analysis;

  return (
    <article>
      <Link
        to="/runs"
        className="font-evidence text-xs text-ink-faint hover:text-ink"
      >
        &larr; all runs
      </Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-6">
        <div>
          <h1 className="font-display text-4xl font-semibold">
            {analysis?.org ?? "Verification run"}
          </h1>
          <p className="mt-1 font-evidence text-xs text-ink-faint">
            {detail.run_id} · {detail.state}
            {analysis?.replay && " · replay of a real recorded call"}
          </p>
          {detail.payload?.summary && (
            <p className="mt-3 max-w-xl text-ink-soft">{detail.payload.summary}</p>
          )}
        </div>
        {analysis && (
          <VerdictStamp
            verdict={analysis.reconciliation.verdict}
            probability={analysis.reconciliation.posterior_probability}
          />
        )}
      </div>

      {analysis && (
        <motion.section
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          aria-label="Extracted claims"
          className="mt-8 grid gap-4 sm:grid-cols-2"
        >
          {analysis.claims.map((claim) => (
            <ClaimCard key={claim.claim} claim={claim} onHover={setLiveClaim} />
          ))}
        </motion.section>
      )}

      <section aria-label="Transcript" className="mt-10">
        <h2 className="font-display text-lg font-semibold">
          Transcript, with evidence marked
        </h2>
        <p className="font-evidence text-[11px] text-ink-faint">
          hover a claim card to light its supporting span
        </p>
        <ul className="mt-3">
          {turns.map((turn, index) => (
            <TurnLine
              key={index}
              turn={turn}
              index={index}
              claims={analysis?.claims ?? []}
              liveClaim={liveClaim}
            />
          ))}
        </ul>
        {turns.length === 0 && (
          <p className="font-evidence text-sm text-ink-faint">
            No transcript recorded for this run.
          </p>
        )}
      </section>

      {analysis && (
        <section className="mt-10 max-w-2xl" aria-label="Reconciliation">
          <Waterfall recon={analysis.reconciliation} />
        </section>
      )}

      {detail.payload?.evidence && (
        <section className="mt-10" aria-label="Platform evidence">
          <h2 className="font-display text-lg font-semibold">
            What the caller itself reported
          </h2>
          <ul className="mt-2 list-inside list-disc text-sm text-ink-soft">
            {detail.payload.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
