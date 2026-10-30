"use client";

import { useState } from "react";
import type { Icp } from "@/lib/research";

function Confidence({ value }: { value?: number }) {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <span className="flex items-center gap-2" title={`${pct}% confidence`}>
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-rule" aria-hidden>
        <span className="block h-full rounded-full bg-moss" style={{ width: `${pct}%` }} />
      </span>
      <span className="w-9 text-right text-sm tabular-nums text-muted">{pct}%</span>
    </span>
  );
}

function ScoredList({ title, items }: { title: string; items: { label: string; confidence?: number }[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ul className="flex flex-col gap-1.5">
        {items.map((item) => (
          <li key={item.label} className="flex items-center justify-between gap-4">
            <span>{item.label}</span>
            <Confidence value={item.confidence} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function IcpPanel({ icp }: { icp: Icp }) {
  const [choices, setChoices] = useState<Record<string, "accepted" | "dismissed">>({});
  const where = [...(icp.regions ?? []), ...(icp.company_sizes ?? [])].join(", ");

  return (
    <section aria-labelledby="icp-heading" className="flex flex-col gap-6 rounded-md border border-rule bg-panel p-5">
      <div>
        <h2 id="icp-heading" className="text-xl font-semibold tracking-tight">
          Who to sell to
        </h2>
        {where && <p className="mt-1 text-muted">{where}</p>}
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <ScoredList
          title="Industries"
          items={(icp.industries ?? []).map((i) => ({ label: i.name, confidence: i.confidence }))}
        />
        <ScoredList
          title="Buyers"
          items={(icp.personas ?? []).map((p) => ({ label: p.title, confidence: p.confidence }))}
        />
        <ScoredList
          title="Buying moments"
          items={(icp.triggers ?? []).map((t) => ({ label: t.signal, confidence: t.confidence }))}
        />
      </div>

      {(icp.expansions ?? []).length > 0 && (
        <div>
          <h3 className="mb-1 font-semibold">Segments worth testing</h3>
          <p className="mb-3 text-sm text-muted">Accept the ones you want the next run to include.</p>
          <ul className="flex flex-col divide-y divide-rule border-y border-rule">
            {icp.expansions!.map((x) => {
              const choice = choices[x.segment];
              return (
                <li
                  key={x.segment}
                  className={`flex flex-wrap items-center justify-between gap-3 py-3 ${choice === "dismissed" ? "opacity-50" : ""}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{x.segment}</p>
                    <p className="text-sm text-muted">{x.reason}</p>
                  </div>
                  <Confidence value={x.confidence} />
                  <div className="flex gap-2">
                    {(["accepted", "dismissed"] as const).map((c) => (
                      <button
                        key={c}
                        type="button"
                        aria-pressed={choice === c}
                        onClick={() => setChoices((prev) => ({ ...prev, [x.segment]: c }))}
                        className={`rounded-md border px-3 py-1 text-sm font-medium ${
                          choice === c
                            ? c === "accepted"
                              ? "border-moss bg-moss text-white"
                              : "border-plum bg-plum-soft text-plum"
                            : "border-rule text-muted hover:border-ink hover:text-ink"
                        }`}
                      >
                        {c === "accepted" ? "Accept" : "Dismiss"}
                      </button>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
