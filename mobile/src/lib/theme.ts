/* The evidence-ledger design language, ported to native. Same tokens as
   the web console's @theme block. */

export const colors = {
  paper: "#faf9f5",
  paperDeep: "#f0eee6",
  ink: "#191712",
  inkSoft: "#57544b",
  inkFaint: "#8a8678",
  trust: "#2456d6",
  trustSoft: "#dfe7fa",
  doubt: "#c25e00",
  doubtSoft: "#f7e8d8",
  contra: "#a3232f",
  contraSoft: "#f6dfe0",
  rule: "#e4e1d6",
  white: "#ffffff",
} as const;

export const fonts = {
  display: "Fraunces_600SemiBold",
  displayBold: "Fraunces_700Bold",
  evidence: "IBMPlexMono_400Regular",
  evidenceMedium: "IBMPlexMono_500Medium",
  body: "SourceSans3_400Regular",
  bodySemi: "SourceSans3_600SemiBold",
} as const;

export function verdictTone(verdict: string): { color: string; soft: string } {
  if (verdict === "verified") return { color: colors.trust, soft: colors.trustSoft };
  if (verdict === "contradicted") return { color: colors.contra, soft: colors.contraSoft };
  return { color: colors.doubt, soft: colors.doubtSoft };
}
