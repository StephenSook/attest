import type { Reconciliation } from "../api";

/* The match-weight arithmetic, drawn as cumulative bars. Same numbers the
   backend computed; the browser only renders them. */
export default function Waterfall({ recon }: { recon: Reconciliation }) {
  const steps = recon.contributions.map((c) => ({
    label: c.field.replaceAll("_", " "),
    sub:
      c.agreed === null ? "no evidence" : c.agreed ? "agrees" : "disagrees",
    weight: c.weight_bits,
    tone:
      c.agreed === null
        ? "bg-rule"
        : c.agreed
          ? "bg-trust"
          : "bg-doubt",
  }));
  const maxAbs = Math.max(1, ...steps.map((s) => Math.abs(s.weight)));

  return (
    <div>
      <h3 className="font-display text-lg font-semibold">
        Why this verdict: the arithmetic
      </h3>
      <p className="font-evidence text-xs text-ink-faint">
        prior {recon.prior_log_odds >= 0 ? "+" : ""}
        {recon.prior_log_odds.toFixed(2)} bits (50/50 audit odds)
      </p>
      <ul className="mt-3 space-y-2">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center gap-3">
            <span className="w-44 shrink-0 text-sm">
              {step.label}
              <span className="block font-evidence text-[10px] uppercase tracking-widest text-ink-faint">
                {step.sub}
              </span>
            </span>
            <span className="relative h-4 flex-1 rounded-sm bg-paper-deep">
              <span
                className={`absolute top-0 h-4 rounded-sm ${step.tone}`}
                style={{
                  width: `${(Math.abs(step.weight) / maxAbs) * 50}%`,
                  left: step.weight >= 0 ? "50%" : undefined,
                  right: step.weight < 0 ? "50%" : undefined,
                }}
              />
              <span className="absolute left-1/2 top-[-2px] h-5 w-px bg-rule" />
            </span>
            <span className="w-16 shrink-0 text-right font-evidence text-xs">
              {step.weight === 0 ? "±0.00" : `${step.weight > 0 ? "+" : ""}${step.weight.toFixed(2)}`}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 border-t border-rule pt-2 text-right font-evidence text-sm">
        posterior {recon.posterior_log_odds >= 0 ? "+" : ""}
        {recon.posterior_log_odds.toFixed(2)} bits ={" "}
        {Math.round(recon.posterior_probability * 100)}% accurate
      </p>
    </div>
  );
}
