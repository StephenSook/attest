import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { startRun } from "../api";

/* Operator-gated live call. Public visitors can read everything on this
   site; placing a real phone call requires the judge key that judges
   receive in the testing instructions. */
export default function NewRunPage() {
  const navigate = useNavigate();
  const [judgeKey, setJudgeKey] = useState("");
  const [org, setOrg] = useState("");
  const [phone, setPhone] = useState("");
  const [accepting, setAccepting] = useState("yes");
  const [plan, setPlan] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await startRun({
        judgeKey,
        org,
        phone,
        consent,
        claims: {
          office_name_confirmed: "yes",
          accepting_new_patients: accepting,
          ...(plan.trim()
            ? { plan_name: plan.trim(), accepts_plan: "yes" }
            : {}),
        },
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
            judge key
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

        <label className="block">
          <span className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
            insurance plan on the record (optional)
          </span>
          <input
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            placeholder="e.g. Aetna PPO"
            className="mt-1 w-full rounded-md border border-rule bg-white/70 px-3 py-2 font-evidence text-sm focus:border-trust focus:outline-none"
          />
          <span className="mt-1 block font-evidence text-[10px] text-ink-faint">
            when set, the call also verifies plan acceptance; the record claims
            the plan is accepted
          </span>
        </label>
        {error && <p className="font-evidence text-sm text-contra">{error}</p>}
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-1"
          />
          <span className="font-evidence text-[11px] text-ink-soft">
            This is my own phone number, or a line I am authorized to have
            called. I am requesting this call, and I understand it will
            identify itself as an automated assistant and may be recorded.
          </span>
        </label>

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
