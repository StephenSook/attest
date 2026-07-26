import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchAttestation, type Attestation } from "../api";
import VerdictStamp from "../components/VerdictStamp";

/* The receipt, literal: a printable certificate of one completed
   verification. Every value comes from the attestation endpoint; nothing
   on this page is composed by hand. */
export default function CertificatePage() {
  const { runId } = useParams();
  const [doc, setDoc] = useState<Attestation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    fetchAttestation(runId)
      .then(setDoc)
      .catch((err) => {
        const message = err instanceof Error ? err.message : "";
        setError(
          message.includes("409")
            ? "This run has not completed; attestations exist only for completed verifications."
            : "Could not load the attestation.",
        );
      });
  }, [runId]);

  if (error) return <p className="font-evidence text-sm text-ink-soft">{error}</p>;
  if (!doc)
    return <p className="font-evidence text-sm text-ink-faint">Preparing the certificate...</p>;

  const download = () => {
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${doc.run_id}-attestation.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <article className="certificate mx-auto max-w-3xl">
      <div className="cert-actions flex items-center justify-between print:hidden">
        <Link
          to={`/runs/${doc.run_id}`}
          className="font-evidence text-xs text-ink-faint hover:text-ink"
        >
          &larr; back to the run
        </Link>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={download}
            className="rounded-md border border-rule px-4 py-2 font-evidence text-xs uppercase tracking-widest text-ink hover:border-trust hover:text-trust"
          >
            download JSON
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-md bg-ink px-4 py-2 font-evidence text-xs uppercase tracking-widest text-paper hover:bg-trust"
          >
            print
          </button>
        </div>
      </div>

      <div className="mt-6 rounded-lg border-2 border-ink bg-white/70 p-8">
        <header className="flex items-start justify-between border-b border-rule pb-6">
          <div>
            <p className="font-evidence text-[11px] uppercase tracking-[0.25em] text-ink-faint">
              certificate of verification
            </p>
            <h1 className="mt-1 font-display text-3xl font-bold">
              {doc.org ?? "Verification run"}
            </h1>
            <p className="mt-1 font-evidence text-xs text-ink-faint">
              {doc.run_id} · completed {doc.completed_at}
              {doc.replay && " · replay of a real recorded call"}
            </p>
          </div>
          <VerdictStamp
            verdict={doc.reconciliation.verdict}
            probability={doc.reconciliation.posterior_probability}
          />
        </header>

        <section className="mt-6" aria-label="Attested claims">
          {doc.claims.map((claim) => (
            <div key={claim.claim} className="border-b border-rule py-3">
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
                  {claim.claim.replaceAll("_", " ")}
                </span>
                <span className="font-display text-xl font-semibold">
                  {claim.abstain ? "abstained" : claim.answer}
                </span>
              </div>
              <p className="mt-1 font-evidence text-xs text-ink-soft">
                {claim.span
                  ? `supporting span: "${claim.span.text}" (turn ${claim.span.turn}, chars ${claim.span.char_start}-${claim.span.char_end})`
                  : "no supporting span: the system did not answer"}
              </p>
            </div>
          ))}
        </section>

        <section className="mt-6 grid gap-2 font-evidence text-[11px] text-ink-soft" aria-label="Verification integrity">
          <p>
            posterior {Math.round(doc.reconciliation.posterior_probability * 100)}% ·
            verdict {doc.reconciliation.verdict}
          </p>
          {doc.calibration.available && (
            <p>
              abstention gate calibrated at qhat {doc.calibration.qhat}, target coverage{" "}
              {Math.round((doc.calibration.target_coverage ?? 0) * 100)}%, measured{" "}
              {((doc.calibration.empirical_coverage ?? 0) * 100).toFixed(1)}% on held-out data
            </p>
          )}
          <p className="break-all">payload sha256 {doc.terminal_payload_sha256}</p>
          <p className="break-all">
            {doc.signature.signed
              ? `signature ${doc.signature.alg} ${doc.signature.value?.slice(0, 32)}… (full value in the JSON export)`
              : "unsigned: no signing key configured on this deployment"}
          </p>
          <p className="text-ink-faint">{doc.policy}</p>
        </section>
      </div>
    </article>
  );
}
