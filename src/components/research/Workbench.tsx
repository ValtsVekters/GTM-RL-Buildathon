"use client";

import { useRef, useState } from "react";
import type { AgentEvent, ResearchInput, ResearchResult } from "@/lib/research";
import { runResearch, SAMPLE_PRODUCT } from "@/lib/research";
import { AgentTrack } from "./AgentTrack";
import { BriefForm } from "./BriefForm";
import { IcpPanel } from "./IcpPanel";
import { LeadList } from "./LeadList";

const QUOTA_LABELS: Record<string, string> = {
  parasail: "Parasail model calls today",
  you: "You.com searches and pages today",
  tavily: "Tavily searches this month",
  hunter: "Hunter email lookups this month",
  "groq:reason": "Groq large model calls today",
  "groq:bulk": "Groq small model calls today",
  gemini: "Gemini calls today",
  jina: "Jina page reads today",
};

export function Workbench() {
  const [input, setInput] = useState<ResearchInput>({ product: SAMPLE_PRODUCT, max_leads: 5, mode: "demo" });
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function run() {
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setEvents([]);
    setResult(null);
    setError(null);
    try {
      const res = await runResearch(input, (e) => setEvents((prev) => [...prev, e]), controller.signal);
      setResult(res);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  function stop() {
    abortRef.current?.abort();
    setError("You stopped watching. The run keeps going on the worker until it finishes, so a new run may wait a few seconds.");
  }

  const started = running || events.length > 0 || error !== null;

  return (
    <div className="mx-auto grid max-w-7xl gap-10 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(18rem,24rem)_1fr] lg:gap-14 lg:py-12">
      <aside className="flex flex-col gap-8 lg:sticky lg:top-8 lg:self-start">
        <header>
          <p className="text-lg font-semibold">GTM Engine</p>
          <p className="text-muted">Finds companies to sell to and checks every claim on their own website.</p>
        </header>
        <BriefForm input={input} running={running} onChange={setInput} onRun={run} onStop={stop} />
        {result && (
          <section aria-labelledby="quota-heading" className="border-t border-rule pt-6">
            <h2 id="quota-heading" className="mb-3 font-semibold">
              {input.mode === "demo" ? "Credits this sample run would leave" : "Free credits left"}
            </h2>
            <dl className="flex flex-col gap-1.5 text-sm">
              {Object.entries(result.quota_left)
                .filter(([name]) => name in QUOTA_LABELS)
                .map(([name, left]) => (
                  <div key={name} className="flex justify-between gap-4">
                    <dt className="text-muted">{QUOTA_LABELS[name]}</dt>
                    <dd className="tabular-nums">{left}</dd>
                  </div>
                ))}
            </dl>
          </section>
        )}
      </aside>

      <main className="flex min-w-0 flex-col gap-8">
        {!started && (
          <div className="flex min-h-80 flex-col justify-center gap-4 rounded-md border border-dashed border-rule p-8">
            <p className="max-w-xl text-2xl font-semibold leading-snug tracking-tight text-balance">
              Describe what you sell, then find leads.
            </p>
            <p className="max-w-xl text-muted">
              Five agents work in turn: one decides who to sell to, one searches for companies, one reads each
              company&apos;s own website, one checks every quote and name against those pages, and one looks up emails
              for the best fits. You&apos;ll watch them work here.
            </p>
          </div>
        )}

        {started && <AgentTrack events={events} running={running} />}

        {error && (
          <p role="alert" className="rounded-md border border-plum bg-plum-soft px-4 py-3 text-plum">
            {error}
          </p>
        )}

        {result && (
          <>
            <IcpPanel icp={result.icp} />
            <LeadList leads={result.leads} dropped={result.dropped} />
          </>
        )}
      </main>
    </div>
  );
}
