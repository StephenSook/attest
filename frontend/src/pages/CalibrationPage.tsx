import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchMetrics, type Metrics } from "../api";

const INK = "#191712";
const FAINT = "#a09b8c";
const RULE = "#e4e1d6";
const TRUST = "#2456d6";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-rule bg-white/60 p-4">
      <p className="font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
        {label}
      </p>
      <p className="font-display text-3xl font-semibold">{value}</p>
    </div>
  );
}

export default function CalibrationPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alphaIndex, setAlphaIndex] = useState<number | null>(null);

  useEffect(() => {
    fetchMetrics()
      .then(setMetrics)
      .catch((err) => {
        const message = err instanceof Error ? err.message : "";
        setError(
          message.includes("404")
            ? "Metrics have not been generated on this deployment."
            : `Could not load metrics: ${message || "network failure"}.`,
        );
      });
  }, []);

  if (error) return <p className="font-evidence text-sm text-ink-soft">{error}</p>;
  if (!metrics)
    return <p className="font-evidence text-sm text-ink-faint">Loading the evidence...</p>;

  const head = metrics.headline;
  const reliability = metrics.per_alpha.map((row) => ({
    target: row.target,
    empirical: row.empirical_coverage,
  }));
  const headlineIndex = metrics.per_alpha.findIndex((row) => row.alpha === head.alpha);
  const selected =
    metrics.per_alpha[alphaIndex ?? (headlineIndex >= 0 ? headlineIndex : 0)];

  return (
    <section aria-labelledby="calibration-heading">
      <h1 id="calibration-heading" className="font-display text-4xl font-semibold">
        The guarantee, measured
      </h1>
      <p className="mt-2 max-w-2xl text-ink-soft">
        Every number below regenerates from one seeded command on held-out data.
        Scripted adversarial personas, disjoint folds, seed {metrics.seed}.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <Stat
          label={`coverage at ${Math.round(head.target_coverage * 100)}% target`}
          value={`${(head.empirical_coverage * 100).toFixed(1)}%`}
        />
        <Stat
          label="abstention rate"
          value={`${(head.abstention_rate * 100).toFixed(1)}%`}
        />
        <Stat
          label="accuracy when answering"
          value={`${(head.accuracy_when_answering * 100).toFixed(1)}%`}
        />
      </div>

      <div className="mt-10 rounded-lg border border-rule bg-white/60 p-5">
        <h2 className="font-display text-lg font-semibold">
          Choose your own guarantee
        </h2>
        <p className="mt-1 max-w-2xl font-evidence text-xs text-ink-soft">
          Drag the target. Every displayed value is a measured point from the
          held-out fold; the slider snaps to evaluated targets and never
          interpolates.
        </p>
        <input
          type="range"
          min={0}
          max={metrics.per_alpha.length - 1}
          step={1}
          value={alphaIndex ?? headlineIndex}
          onChange={(event) => setAlphaIndex(Number(event.target.value))}
          className="explorer-slider mt-4 w-full"
          aria-label="Target coverage selector, snaps to evaluated targets"
        />
        <div className="mt-4 grid gap-4 sm:grid-cols-4">
          <Stat label="target coverage" value={`${Math.round(selected.target * 100)}%`} />
          <Stat
            label="measured coverage"
            value={`${(selected.empirical_coverage * 100).toFixed(1)}%`}
          />
          <Stat
            label="abstention"
            value={`${(selected.abstention_rate * 100).toFixed(1)}%`}
          />
          <Stat
            label="accuracy when answering"
            value={`${(selected.accuracy_when_answering * 100).toFixed(1)}%`}
          />
        </div>
      </div>

      <div className="mt-8 rounded-lg border border-rule bg-white/60 p-5">
        <h2 className="font-display text-lg font-semibold">
          Empirical coverage tracks the target
        </h2>
        <div className="mt-3 h-72">
          <ResponsiveContainer>
            <LineChart data={reliability} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke={RULE} strokeWidth={0.7} />
              <XAxis
                dataKey="target"
                type="number"
                domain={[0.65, 1]}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                stroke={FAINT}
                fontSize={11}
              />
              <YAxis
                domain={[0.6, 1]}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                stroke={FAINT}
                fontSize={11}
              />
              <Tooltip
                formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`}
                labelFormatter={(v) => `target ${Math.round(Number(v) * 100)}%`}
                contentStyle={{ fontFamily: "IBM Plex Mono", fontSize: 12 }}
              />
              <ReferenceLine
                segment={[
                  { x: 0.65, y: 0.65 },
                  { x: 1, y: 1 },
                ]}
                stroke={FAINT}
                strokeDasharray="5 4"
              />
              <Line
                dataKey="empirical"
                stroke={TRUST}
                strokeWidth={2}
                dot={{ r: 4, fill: TRUST }}
                isAnimationActive={false}
              />
              <ReferenceDot
                x={selected.target}
                y={selected.empirical_coverage}
                r={8}
                fill="none"
                stroke={INK}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {metrics.real_channel && (
        <div className="mt-8 rounded-lg border-2 border-trust bg-white/60 p-5">
          <h2 className="font-display text-lg font-semibold">
            The guarantee survived the real telephone
          </h2>
          <p className="mt-1 max-w-2xl font-evidence text-xs text-ink-soft">
            {metrics.real_channel.n_collected} real calls to a consented line,
            answered from pre-registered scripted ground truth, scored with the
            HARNESS-calibrated threshold (never fit on this data).{" "}
            {metrics.real_channel.n_excluded_by_protocol} calls excluded by the
            documented deviation protocol. {metrics.real_channel.provenance}.
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Stat
              label={`real-channel coverage (n=${metrics.real_channel.n_collected})`}
              value={`${(metrics.real_channel.empirical_coverage * 100).toFixed(1)}%`}
            />
            <Stat
              label="Wilson 95% lower bound"
              value={`${(metrics.real_channel.coverage_wilson_95[0] * 100).toFixed(1)}%`}
            />
            <Stat
              label="accuracy when answering"
              value={
                metrics.real_channel.accuracy_when_answering === null
                  ? "n/a"
                  : `${(metrics.real_channel.accuracy_when_answering * 100).toFixed(1)}%`
              }
            />
          </div>
        </div>
      )}

      {metrics.mondrian && (
        <div className="mt-8 rounded-lg border border-rule bg-white/60 p-5">
          <h2 className="font-display text-lg font-semibold">
            The average was hiding a class
          </h2>
          <p className="mt-1 max-w-2xl font-evidence text-xs text-ink-soft">
            Marginal coverage looked healthy while under-covering one answer
            class. Class-conditional (Mondrian) thresholds fix what the
            average concealed.
          </p>
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="border-b border-rule text-left font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
                <th className="py-2 font-medium">true answer</th>
                <th className="py-2 font-medium">n</th>
                <th className="py-2 font-medium">marginal coverage</th>
                <th className="py-2 font-medium">class-conditional</th>
              </tr>
            </thead>
            <tbody className="font-evidence text-xs" style={{ color: INK }}>
              {metrics.mondrian.per_class.map((row) => (
                <tr key={row.label} className="border-b border-rule">
                  <td className="py-2">{row.label}</td>
                  <td className="py-2">{row.n}</td>
                  <td
                    className="py-2"
                    style={{
                      color:
                        row.marginal_coverage < 1 - metrics.mondrian!.alpha
                          ? "#c25e00"
                          : INK,
                    }}
                  >
                    {(row.marginal_coverage * 100).toFixed(1)}%
                  </td>
                  <td className="py-2">{(row.mondrian_coverage * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-8 rounded-lg border border-rule bg-white/60 p-5">
        <h2 className="font-display text-lg font-semibold">
          What each component buys
        </h2>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-evidence text-[11px] uppercase tracking-widest text-ink-faint">
              <th className="py-2 font-medium">config</th>
              <th className="py-2 font-medium">coverage</th>
              <th className="py-2 font-medium">abstention</th>
              <th className="py-2 font-medium">accuracy when answering</th>
            </tr>
          </thead>
          <tbody className="font-evidence text-xs" style={{ color: INK }}>
            {metrics.ablation.map((row) => (
              <tr key={row.config} className="border-b border-rule">
                <td className="py-2">{row.config}</td>
                <td className="py-2">
                  {row.coverage === null ? "n/a" : `${(row.coverage * 100).toFixed(1)}%`}
                </td>
                <td className="py-2">{(row.abstention_rate * 100).toFixed(1)}%</td>
                <td className="py-2">
                  {(row.accuracy_when_answering * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
