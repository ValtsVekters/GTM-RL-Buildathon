"use client";

import { useEffect, useRef } from "react";
import type { AgentEvent } from "@/lib/research";
import { AGENTS } from "@/lib/research";

const ROLE: Record<(typeof AGENTS)[number], string> = {
  "ICP strategist": "Decides who to sell to",
  "Market scout": "Searches for matching companies",
  "Page reader": "Reads each company's own site",
  Reviewer: "Checks every claim against the pages",
  "Contact enricher": "Looks up emails for tier A",
};

const KIND_STYLE: Record<AgentEvent["kind"], string> = {
  tool: "text-ink",
  model: "text-ink",
  drop: "text-plum",
  flag: "text-plum",
  budget: "text-plum font-medium",
  error: "text-plum font-medium",
  done: "text-moss font-medium",
};

interface Props {
  events: AgentEvent[];
  running: boolean;
}

export function AgentTrack({ events, running }: Props) {
  const feedRef = useRef<HTMLOListElement>(null);
  const lastAgent = [...events].reverse().find((e) => AGENTS.includes(e.agent as (typeof AGENTS)[number]))?.agent;
  const activeIndex = lastAgent ? AGENTS.indexOf(lastAgent as (typeof AGENTS)[number]) : running ? 0 : -1;
  const finished = events.some((e) => e.kind === "done");

  useEffect(() => {
    const feed = feedRef.current;
    if (feed) feed.scrollTop = feed.scrollHeight;
  }, [events.length]);

  return (
    <section aria-label="Agent progress" className="flex flex-col gap-4">
      <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-rule bg-rule sm:grid-cols-5">
        {AGENTS.map((agent, i) => {
          const state = finished || i < activeIndex ? "done" : i === activeIndex && running ? "working" : "waiting";
          const count = events.filter((e) => e.agent === agent).length;
          return (
            <li
              key={agent}
              aria-current={state === "working" ? "step" : undefined}
              className={`relative flex flex-col gap-1 p-3 ${state === "working" ? "bg-moss-soft" : "bg-panel"}`}
            >
              <span className="flex items-baseline gap-2">
                <span
                  className={`text-sm tabular-nums ${state === "waiting" ? "text-muted" : "text-moss"}`}
                  aria-hidden
                >
                  {i + 1}
                </span>
                <span className={`font-semibold ${state === "waiting" ? "text-muted" : "text-ink"}`}>{agent}</span>
              </span>
              <span className="text-sm leading-snug text-muted">{ROLE[agent]}</span>
              <span className="text-xs text-muted">
                {state === "done" ? `Done, ${count} step${count === 1 ? "" : "s"}` : state === "working" ? "Working" : "Waiting"}
              </span>
              {state === "working" && (
                <span className="absolute inset-x-0 bottom-0 h-0.5 animate-pulse bg-moss motion-reduce:animate-none" />
              )}
            </li>
          );
        })}
      </ol>

      <ol
        ref={feedRef}
        aria-live="polite"
        className="max-h-64 overflow-y-auto rounded-md border border-rule bg-panel px-4 py-3 text-sm leading-relaxed"
      >
        {events.length === 0 && <li className="text-muted">Starting the first agent…</li>}
        {events.map((e, i) => (
          <li key={i} className="grid grid-cols-[8.5rem_1fr] gap-3 py-0.5">
            <span className="truncate text-muted">{e.agent}</span>
            <span className={`break-words ${KIND_STYLE[e.kind] ?? "text-ink"}`}>{e.message}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
