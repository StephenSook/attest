const BASE = import.meta.env.VITE_API_BASE ?? "";

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

export type Contribution = {
  field: string;
  call_answer: string;
  directory_claim: string;
  agreed: boolean | null;
  weight_bits: number;
};

export type Reconciliation = {
  verdict: "verified" | "contradicted" | "unverifiable";
  posterior_probability: number;
  prior_log_odds: number;
  posterior_log_odds: number;
  contributions: Contribution[];
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
    task_completed?: boolean;
    completion_confidence?: { score: number; label: string };
    evidence?: string[];
    summary?: string;
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
  created_at: string;
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
    provenance?: string;
  };
  terminal_payload_sha256: string;
  policy: string;
  signature: { alg: string | null; signed: boolean; value: string | null; covers?: string };
};

export type Metrics = {
  seed: number;
  n_calibration: number;
  n_test: number;
  headline: {
    alpha: number;
    target_coverage: number;
    empirical_coverage: number;
    coverage_wilson_95: [number, number];
    abstention_rate: number;
    accuracy_when_answering: number;
  };
  per_alpha: {
    alpha: number;
    target: number;
    empirical_coverage: number;
    abstention_rate: number;
    accuracy_when_answering: number;
  }[];
  ablation: {
    config: string;
    coverage: number | null;
    abstention_rate: number;
    accuracy_when_answering: number;
  }[];
  mondrian?: {
    alpha: number;
    overall_coverage: number;
    per_class: {
      label: string;
      n: number;
      marginal_coverage: number;
      mondrian_coverage: number;
    }[];
  };
  real_channel?: {
    provenance: string;
    n_collected: number;
    n_excluded_by_protocol: number;
    n_manifest: number;
    qhat: number;
    empirical_coverage: number;
    coverage_wilson_95: [number, number];
    abstention_rate: number;
    accuracy_when_answering: number | null;
    worst_case_coverage_all_excluded_as_misses: number | null;
  };
  calibration_sensitivity?: {
    n_cal: number;
    qhat: number;
    coverage: number;
    abstention_rate: number;
  }[];
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} responded ${response.status}`);
  }
  return (await response.json()) as T;
}

export const fetchRuns = () => get<{ runs: RunSummary[] }>("/api/runs");
export const fetchRun = (runId: string) => get<RunDetail>(`/api/runs/${runId}`);
export const audioUrlOf = (runId: string) => `${BASE}/api/runs/${runId}/audio`;
export const fetchMetrics = () => get<Metrics>("/api/metrics");
export const fetchAttestation = (runId: string) =>
  get<Attestation>(`/api/runs/${runId}/attestation`);

export async function startRun(input: {
  judgeKey: string;
  org: string;
  phone: string;
  claims: Record<string, string>;
  consent: boolean;
}): Promise<{ run_id: string }> {
  const response = await fetch(`${BASE}/internal/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Attest-Key": input.judgeKey,
    },
    body: JSON.stringify({
      phone: input.phone,
      org: input.org,
      claims: input.claims,
      consent: input.consent,
    }),
  });
  if (response.status === 403) throw new Error("That key was not accepted.");
  if (response.status === 503) throw new Error("Live calling is not enabled on this deployment.");
  if (response.status === 429) {
    throw new Error(
      (await response.json()).detail ?? "The live demo budget is spent.",
    );
  }
  if (response.status === 422) {
    const detail = (await response.json()).detail;
    throw new Error(
      typeof detail === "string" ? detail : "Phone must be E.164, like +15550101234.",
    );
  }
  if (!response.ok) throw new Error(`Run creation failed (${response.status}).`);
  return (await response.json()) as { run_id: string };
}

export function transcriptOf(detail: RunDetail): TranscriptTurn[] {
  for (const recipient of detail.payload?.recipients ?? []) {
    for (const attempt of recipient.attempts ?? []) {
      if (attempt.transcript_turns?.length) return attempt.transcript_turns;
    }
  }
  return [];
}
