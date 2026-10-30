// Types mirror worker/research/models.py and crew.py; the stream format mirrors worker/main.py.

export type Mode = "demo" | "live";

export interface ResearchInput {
  product: string;
  max_leads: number;
  mode: Mode;
}

export interface AgentEvent {
  agent: string;
  kind: "tool" | "model" | "drop" | "flag" | "budget" | "error" | "done";
  message: string;
  data: Record<string, unknown>;
}

export interface Person {
  name: string;
  title: string;
  email: string;
  email_status: "valid" | "risky" | "unknown";
  email_confidence: number;
}

export interface Signal {
  signal: string;
  quote: string;
  verified: boolean;
}

export interface Lead {
  company: string;
  domain: string;
  source_url: string;
  industry: string;
  why_fit: string;
  found_via: string;
  evidence_urls: string[];
  people: Person[];
  signals: Signal[];
  fit_score: number;
  tier: "A" | "B" | "C";
  enrichment: "pending" | "enriched" | "skipped" | "no_credits" | "failed";
  review: "pending" | "awaiting_approval" | "dropped";
  review_notes: string[];
}

export interface Scored {
  confidence?: number;
}

export interface Icp {
  industries?: (Scored & { name: string; naics?: string })[];
  company_sizes?: string[];
  regions?: string[];
  personas?: (Scored & { title: string })[];
  triggers?: (Scored & { signal: string })[];
  expansions?: (Scored & { segment: string; reason: string })[];
}

export interface ResearchResult {
  icp: Icp;
  leads: Lead[];
  dropped: Lead[];
  events: AgentEvent[];
  quota_left: Record<string, number>;
}

type StreamLine =
  | { type: "event"; event: AgentEvent }
  | { type: "result"; result: ResearchResult }
  | { type: "error"; message: string };

export const AGENTS = ["ICP strategist", "Market scout", "Page reader", "Reviewer", "Contact enricher"] as const;

export const SAMPLE_PRODUCT =
  "Energy mints with caffeine + L-theanine, sold B2B to offices, gyms and esports teams in the Baltics.";

function describeError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d: { loc?: unknown[]; msg?: string }) => `${d.loc?.at(-1) ?? "input"}: ${d.msg}`).join("; ");
  }
  return `The research request failed (HTTP ${status}).`;
}

/** Starts a run and reports each agent step as it streams in. Resolves with the final result. */
export async function runResearch(
  input: ResearchInput,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<ResearchResult> {
  const res = await fetch("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(describeError(res.status, await res.json().catch(() => null)));
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let result: ResearchResult | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const msg = JSON.parse(line) as StreamLine;
      if (msg.type === "event") onEvent(msg.event);
      else if (msg.type === "result") result = msg.result;
      else throw new Error(msg.message);
    }
  }
  if (!result) throw new Error("The research run ended without a result.");
  return result;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
