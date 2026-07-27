import Constants from "expo-constants";

/* The pocket console is read-only against the same public API the web
   console uses. No secrets, no live dialing, phone numbers always masked
   server-side. */

const BASE: string =
  (Constants.expoConfig?.extra?.apiBase as string | undefined) ??
  "https://attest-api-o5gm.onrender.com";

export type RunSummary = {
  run_id: string;
  state: string;
  created_at: string;
  org: string | null;
  replay: boolean;
};

export type Span = {
  turn: number;
  text: string;
  char_start: number;
  char_end: number;
};

export type Claim = {
  claim: string;
  answer: "yes" | "no" | "unknown";
  trust_score: number;
  hedged: boolean;
  abstain: boolean;
  span: Span | null;
};

export type Reconciliation = {
  verdict: "verified" | "contradicted" | "unverifiable";
  posterior_probability: number;
  contributions: {
    field: string;
    call_answer: string;
    directory_claim: string;
    agreed: boolean | null;
    weight_bits: number;
  }[];
};

export type TranscriptTurn = {
  offset_seconds: number;
  speaker: "bot" | "user";
  text: string;
};

export type RunDetail = {
  run_id: string;
  state: string;
  created_at: string;
  updated_at: string;
  payload: {
    summary?: string;
    evidence?: string[];
    recipients?: { attempts?: { transcript_turns?: TranscriptTurn[] }[] }[];
  } | null;
  analysis?: {
    org: string | null;
    replay: boolean;
    claims: Claim[];
    reconciliation: Reconciliation;
  };
  failure?: { error: string; stage: string };
  has_audio?: boolean;
  audio_note?: string;
};

export type Attestation = {
  schema: string;
  run_id: string;
  completed_at: string;
  org: string | null;
  replay: boolean;
  claims: Claim[];
  reconciliation: Reconciliation;
  calibration: {
    available: boolean;
    qhat?: number;
    target_coverage?: number;
    empirical_coverage?: number;
  };
  terminal_payload_sha256: string;
  policy: string;
  signature: { alg: string | null; signed: boolean; value: string | null };
};

export type Metrics = {
  seed: number;
  headline: {
    target_coverage: number;
    empirical_coverage: number;
    coverage_wilson_95: [number, number];
    abstention_rate: number;
    accuracy_when_answering: number;
  };
  real_channel?: {
    provenance: string;
    n_collected: number;
    n_excluded_by_protocol: number;
    empirical_coverage: number;
    coverage_wilson_95: [number, number];
    abstention_rate: number;
    accuracy_when_answering: number | null;
    worst_case_coverage_all_excluded_as_misses: number | null;
  };
  mondrian?: {
    alpha: number;
    per_class: {
      label: string;
      n: number;
      marginal_coverage: number;
      mondrian_coverage: number;
    }[];
  };
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${path} responded ${response.status}`);
  return (await response.json()) as T;
}

export const fetchRuns = () => get<{ runs: RunSummary[] }>("/api/runs");
export const fetchRun = (runId: string) => get<RunDetail>(`/api/runs/${runId}`);
export const fetchMetrics = () => get<Metrics>("/api/metrics");
export const fetchAttestation = (runId: string) =>
  get<Attestation>(`/api/runs/${runId}/attestation`);
export const audioUrlOf = (runId: string) => `${BASE}/api/runs/${runId}/audio`;

export function transcriptOf(detail: RunDetail): TranscriptTurn[] {
  for (const recipient of detail.payload?.recipients ?? []) {
    for (const attempt of recipient.attempts ?? []) {
      if (attempt.transcript_turns?.length) return attempt.transcript_turns;
    }
  }
  return [];
}
