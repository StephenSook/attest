import { verifyAsync } from "@noble/ed25519";
import { useState } from "react";

const BASE = import.meta.env.VITE_API_BASE ?? "";

/* Paste-and-verify: anyone can check an attestation certificate against
   this deployment's PUBLIC key, entirely in the browser. Nothing pasted
   here leaves the page. */

function pemToRawPublicKey(pem: string): Uint8Array {
  const b64 = pem
    .replace(/-----BEGIN PUBLIC KEY-----/, "")
    .replace(/-----END PUBLIC KEY-----/, "")
    .replace(/\s/g, "");
  const der = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  // Ed25519 SubjectPublicKeyInfo: the raw 32-byte key is the DER suffix.
  return der.slice(der.length - 32);
}

type Outcome =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "valid"; runId: string; verdict: string }
  | { state: "invalid"; reason: string }
  | { state: "unsigned" };

export default function VerifyPage() {
  const [pasted, setPasted] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ state: "idle" });

  const verify = async () => {
    setOutcome({ state: "checking" });
    try {
      const doc = JSON.parse(pasted) as Record<string, unknown>;
      const signature = doc.signature as
        | { signed?: boolean; value?: string | null }
        | undefined;
      if (!signature?.signed || !signature.value) {
        setOutcome({ state: "unsigned" });
        return;
      }
      const stripped = { ...doc };
      delete stripped.signature;
      // Canonical form matches the server exactly: recursive sorted keys,
      // compact separators, unescaped unicode.
      const canonicalize = (value: unknown): string => {
        if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
        if (value !== null && typeof value === "object") {
          const entries = Object.entries(value as Record<string, unknown>)
            .sort(([a], [b]) => (a < b ? -1 : 1))
            .map(([k, v]) => `${JSON.stringify(k)}:${canonicalize(v)}`);
          return `{${entries.join(",")}}`;
        }
        return JSON.stringify(value);
      };
      const message = new TextEncoder().encode(canonicalize(stripped));
      const pem = await (await fetch(`${BASE}/api/attestation-key`)).text();
      const publicKey = pemToRawPublicKey(pem);
      const signatureBytes = Uint8Array.from(atob(signature.value), (c) =>
        c.charCodeAt(0),
      );
      const ok = await verifyAsync(signatureBytes, message, publicKey);
      if (ok) {
        const recon = doc.reconciliation as { verdict?: string } | undefined;
        setOutcome({
          state: "valid",
          runId: String(doc.run_id ?? "unknown"),
          verdict: recon?.verdict ?? "unknown",
        });
      } else {
        setOutcome({ state: "invalid", reason: "signature does not match this document" });
      }
    } catch (error) {
      setOutcome({
        state: "invalid",
        reason: error instanceof Error ? error.message : "could not parse that JSON",
      });
    }
  };

  return (
    <section aria-labelledby="verify-heading" className="mx-auto max-w-2xl">
      <h1 id="verify-heading" className="font-display text-4xl font-semibold">
        Verify a certificate
      </h1>
      <p className="mt-2 text-ink-soft">
        Paste an attestation JSON (downloaded from any run's certificate page).
        Verification happens entirely in your browser against this
        deployment's public key; nothing you paste leaves the page.
      </p>
      <textarea
        value={pasted}
        onChange={(event) => setPasted(event.target.value)}
        rows={10}
        placeholder='{"schema": "attest/attestation/v1", ...}'
        className="mt-4 w-full rounded-md border border-rule bg-white/70 p-3 font-evidence text-xs focus:border-trust focus:outline-none"
      />
      <button
        type="button"
        onClick={verify}
        disabled={!pasted.trim() || outcome.state === "checking"}
        className="mt-3 rounded-md bg-ink px-6 py-3 font-evidence text-sm uppercase tracking-widest text-paper transition-colors hover:bg-trust disabled:opacity-50"
      >
        {outcome.state === "checking" ? "verifying..." : "verify signature"}
      </button>

      {outcome.state === "valid" && (
        <div className="stamp mt-6 inline-block rotate-[-2deg] rounded-lg border-2 border-trust bg-trust-soft px-5 py-3">
          <p className="font-evidence text-sm uppercase tracking-[0.2em] text-trust">
            signature valid
          </p>
          <p className="mt-1 font-evidence text-xs text-trust">
            {outcome.runId} · verdict {outcome.verdict}
          </p>
        </div>
      )}
      {outcome.state === "invalid" && (
        <div className="stamp mt-6 inline-block rotate-[-2deg] rounded-lg border-2 border-contra bg-contra-soft px-5 py-3">
          <p className="font-evidence text-sm uppercase tracking-[0.2em] text-contra">
            not valid
          </p>
          <p className="mt-1 font-evidence text-xs text-contra">{outcome.reason}</p>
        </div>
      )}
      {outcome.state === "unsigned" && (
        <p className="mt-6 font-evidence text-sm text-doubt">
          That document is unsigned; there is nothing to verify.
        </p>
      )}

      <p className="mt-8 font-evidence text-[11px] text-ink-faint">
        The production public key is also committed in the repository at
        docs/attestation-public-key.pem, so certificates remain checkable
        even if this page is unavailable.
      </p>
    </section>
  );
}
