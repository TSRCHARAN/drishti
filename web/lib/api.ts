// API client for the Drishti server.
// v1 is built for self-hosting: the browser talks to your own server directly,
// so the host/key live in NEXT_PUBLIC_* vars (fine on localhost; the hosted
// cloud version will proxy through a backend instead).

const HOST = process.env.NEXT_PUBLIC_DRISHTI_HOST ?? "http://localhost:8787";
const API_KEY = process.env.NEXT_PUBLIC_DRISHTI_API_KEY ?? "dev-key";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${HOST}${path}`, {
    headers: { "x-api-key": API_KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export interface TraceSummary {
  trace_id: string;
  name: string;
  session_id: string | null;
  start_time: number;
  duration_ms: number | null;
  span_count: number;
  llm_call_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  has_error: boolean;
}

export interface Span {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  span_type: "span" | "llm" | "tool";
  session_id: string | null;
  start_time: number;
  end_time: number | null;
  duration_ms: number | null;
  input: unknown;
  output: unknown;
  error: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  metadata: Record<string, unknown> | null;
}

export interface TraceDetail {
  trace_id: string;
  spans: Span[];
}

export interface Stats {
  traces: number;
  spans: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  by_model: {
    model: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
  }[];
}

export const api = {
  stats: () => get<Stats>("/api/v1/stats"),
  traces: (limit = 100) => get<TraceSummary[]>(`/api/v1/traces?limit=${limit}`),
  trace: (traceId: string) => get<TraceDetail>(`/api/v1/traces/${traceId}`),
};

// ---- formatting helpers ----

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function fmtCost(usd: number | null | undefined): string {
  if (usd == null || usd === 0) return "–";
  if (usd < 0.01) return `$${usd.toFixed(5)}`;
  return `$${usd.toFixed(3)}`;
}

export function fmtTime(epochMs: number): string {
  return new Date(epochMs).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function fmtInt(n: number | null | undefined): string {
  if (n == null) return "–";
  return n.toLocaleString();
}
