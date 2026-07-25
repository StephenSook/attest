import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { startRun } from "../api";

/* Operator-gated live call. Public visitors can read everything on this
   site; placing a real phone call requires the operator key that judges
   receive in the testing instructions. */
export default function NewRunPage() {
  const navigate = useNavigate();
  const [judgeKey, setJudgeKey] = useState("");
  const [org, setOrg] = useState("");
  const [phone, setPhone] = useState("");
  const [accepting, setAccepting] = useState("yes");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const task =
        `You are placing a short verification call to ${org} on behalf of a records ` +
        "verification service. Open with: 'Hi, this is an automated assistant calling " +
        `to verify directory information for ${org}. This call may be recorded.' ` +
        "Then politely ask whether the practice is currently accepting new patients. " +
        "Record the answer exactly as given. If the person hedges, capture their exact " +
        "wording. If they decline to speak with an automated caller, thank them and end " +
        "the call immediately. Never guess: anything not clearly stated is unknown. " +
        "Keep the call under two minutes.";
      const { run_id } = await startRun({
        judgeKey,
        org,
        phone,
        task,
        claims: { accepting_new_patients: accepting },
      });
      navigate(`/runs/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  };

  const field =
    "mt-1 w-full rounded-md border border-rule bg-white/70 px-3 py-2 " +
    "font-evidence text-sm focus:outline-2 focus:outline-trust";

  return (
    <section className="max-w-lg" aria-labelledby="new-run-heading">
      <Link to="/runs" className="font-evidence text-xs text-ink-faint hover:text-ink">
        &larr; all runs
      </Link>
      <h1 id="new-run-heading" className="mt-2 font-display text-4xl font-semibold">
        Place a live verification call
      </h1>
      <p className="mt-2 text-ink-soft">
        One disclosed call to a number you are authorized to dial. The call
        announces itself as automated and may be recorded. Operator key
        required; judges receive it in the testing instructions.
      </p>
      <form onSubmit={submit} className="mt-8 space-y-5">
        <label className="block">
          <span className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
            operator key
          </span>
          <input
            type="password"
            required
            value={judgeKey}
            onChange={(e) => setJudgeKey(e.target.value)}
            className={field}
            autoComplete="off"
          />
        </label>
        <label className="block">
          <span className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
            organization, as listed
          </span>
          <input
            type="text"
            required
            minLength={2}
            value={org}
            onChange={(e) => setOrg(e.target.value)}
            className={field}
            placeholder="Example Counseling Center"
          />
        </label>
        <label className="block">
          <span className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
            published phone line, E.164
          </span>
          <input
            type="tel"
            required
            pattern="^\+1\d{10}$"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className={field}
            placeholder="+15550101234"
          />
        </label>
        <fieldset>
          <legend className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
            the directory record claims
          </legend>
          <div className="mt-1 flex gap-4">
            {["yes", "no"].map((value) => (
              <label key={value} className="flex items-center gap-2 font-evidence text-sm">
                <input
                  type="radio"
                  name="accepting"
                  value={value}
                  checked={accepting === value}
                  onChange={() => setAccepting(value)}
                />
                accepting new patients: {value}
              </label>
            ))}
          </div>
        </fieldset>
        {error && <p className="font-evidence text-sm text-contra">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-ink px-6 py-3 font-evidence text-sm uppercase tracking-widest text-paper transition-colors hover:bg-trust focus-visible:outline-2 focus-visible:outline-trust disabled:opacity-50"
        >
          {busy ? "placing the call..." : "place the call"}
        </button>
      </form>
    </section>
  );
}
