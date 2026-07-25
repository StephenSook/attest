import { motion } from "motion/react";

const tone: Record<string, string> = {
  verified: "text-trust",
  contradicted: "text-contra",
  unverifiable: "text-ink-soft",
};

export default function VerdictStamp({
  verdict,
  probability,
}: {
  verdict: string;
  probability: number;
}) {
  return (
    <motion.div
      initial={{ scale: 1.6, opacity: 0, rotate: -10 }}
      animate={{ scale: 1, opacity: 1, rotate: 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 20 }}
      className="text-right"
    >
      <span className={`stamp text-lg ${tone[verdict] ?? "text-ink-soft"}`}>
        {verdict.toUpperCase()}
      </span>
      <p className="mt-2 font-evidence text-xs text-ink-faint">
        {Math.round(probability * 100)}% record-accurate posterior
      </p>
    </motion.div>
  );
}
