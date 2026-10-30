"use client";

import { useState } from "react";
import type { Lead, Person } from "@/lib/research";
import { hostOf } from "@/lib/research";

const ENRICHMENT: Record<Lead["enrichment"], string> = {
  enriched: "Emails checked",
  skipped: "Emails checked for tier A only",
  no_credits: "Out of Hunter credits",
  failed: "Email lookup unavailable",
  pending: "Emails not checked yet",
};

const EMAIL_STATUS: Record<Person["email_status"], string> = {
  valid: "bg-moss-soft text-moss",
  risky: "bg-highlighter/40 text-ink",
  unknown: "bg-rule/60 text-muted",
};

function TierBadge({ tier }: { tier: Lead["tier"] }) {
  const style =
    tier === "A" ? "bg-moss text-white" : tier === "B" ? "border border-moss text-moss" : "border border-rule text-muted";
  return (
    <span className={`inline-flex size-8 shrink-0 items-center justify-center rounded-md font-semibold ${style}`}>
      <span className="sr-only">Tier </span>
      {tier}
    </span>
  );
}

function CopyEmail({ email }: { email: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(email);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="text-sm text-muted underline decoration-rule underline-offset-4 hover:text-ink"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function LeadDetail({ lead }: { lead: Lead }) {
  return (
    <div className="grid gap-6 border-t border-rule px-4 pb-5 pt-4 md:grid-cols-2">
      <div className="flex flex-col gap-4">
        {lead.why_fit && <p>{lead.why_fit}</p>}
        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted">Website</dt>
          <dd>
            <a href={lead.source_url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">
              {lead.domain}
            </a>
          </dd>
          {lead.found_via && hostOf(lead.found_via) !== lead.domain && (
            <>
              <dt className="text-muted">Found through</dt>
              <dd>
                <a href={lead.found_via} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">
                  {hostOf(lead.found_via)}
                </a>
              </dd>
            </>
          )}
          <dt className="text-muted">Pages read</dt>
          <dd className="flex flex-col">
            {(lead.evidence_urls.length ? lead.evidence_urls : [lead.source_url]).map((url) => (
              <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="truncate underline underline-offset-4">
                {new URL(url).pathname === "/" ? "Home page" : new URL(url).pathname}
              </a>
            ))}
          </dd>
        </dl>

        <div>
          <h4 className="mb-2 font-semibold">People</h4>
          {lead.people.length === 0 ? (
            <p className="text-sm text-muted">No named people on the pages read.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {lead.people.map((p) => (
                <li key={p.name} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-medium">{p.name}</span>
                  {p.title && <span className="text-sm text-muted">{p.title}</span>}
                  {p.email && (
                    <span className="flex items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-sm ${EMAIL_STATUS[p.email_status]}`}>
                        {p.email} ({p.email_status})
                      </span>
                      <CopyEmail email={p.email} />
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <div>
          <h4 className="mb-2 font-semibold">What the site says</h4>
          {lead.signals.length === 0 ? (
            <p className="text-sm text-muted">No buying moment found on the pages read.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {lead.signals.map((s) => (
                <li key={s.signal}>
                  <p className="text-sm text-muted">{s.signal}</p>
                  <blockquote className="font-quote text-lg italic leading-snug">
                    <span className="evidence">{s.quote}</span>
                  </blockquote>
                </li>
              ))}
            </ul>
          )}
        </div>
        {lead.review_notes.length > 0 && (
          <div>
            <h4 className="mb-1 font-semibold text-plum">Removed by the reviewer</h4>
            <ul className="list-disc pl-5 text-sm text-plum">
              {lead.review_notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function LeadList({ leads, dropped }: { leads: Lead[]; dropped: Lead[] }) {
  const [open, setOpen] = useState<string | null>(leads[0]?.domain ?? null);
  const [tier, setTier] = useState<"all" | Lead["tier"]>("all");
  const shown = tier === "all" ? leads : leads.filter((l) => l.tier === tier);

  return (
    <section aria-labelledby="leads-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="leads-heading" className="text-xl font-semibold tracking-tight">
            {leads.length} lead{leads.length === 1 ? "" : "s"} ready for your review
          </h2>
          <p className="text-muted">Every quote and person below was found on the company&apos;s own website.</p>
        </div>
        <div className="flex rounded-md border border-rule bg-panel p-1" role="group" aria-label="Filter by tier">
          {(["all", "A", "B", "C"] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tier === t}
              onClick={() => setTier(t)}
              className={`rounded px-3 py-1 text-sm font-medium ${tier === t ? "bg-ink text-paper" : "text-muted hover:text-ink"}`}
            >
              {t === "all" ? "All" : `Tier ${t}`}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 && <p className="text-muted">No leads in this tier.</p>}
      <ul className="flex flex-col gap-2">
        {shown.map((lead) => {
          const isOpen = open === lead.domain;
          return (
            <li key={lead.domain} className="rounded-md border border-rule bg-panel">
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : lead.domain)}
                className="flex w-full items-center gap-4 px-4 py-3 text-left"
              >
                <TierBadge tier={lead.tier} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-lg font-semibold">{lead.company}</span>
                  <span className="block truncate text-sm text-muted">
                    {lead.industry ? `${lead.industry}, ` : ""}
                    {lead.domain}
                  </span>
                </span>
                <span className="hidden w-40 flex-col gap-1 sm:flex">
                  <span className="text-sm tabular-nums">Fit {lead.fit_score}/100</span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-rule" aria-hidden>
                    <span className="block h-full bg-moss" style={{ width: `${lead.fit_score}%` }} />
                  </span>
                </span>
                <span className="hidden w-44 text-sm text-muted md:block">
                  {lead.people.length} {lead.people.length === 1 ? "person" : "people"}, {lead.signals.length} quote
                  {lead.signals.length === 1 ? "" : "s"}
                  <br />
                  {ENRICHMENT[lead.enrichment]}
                </span>
                <span aria-hidden className={`text-muted transition-transform ${isOpen ? "rotate-180" : ""}`}>
                  ▾
                </span>
              </button>
              {isOpen && <LeadDetail lead={lead} />}
            </li>
          );
        })}
      </ul>

      {dropped.length > 0 && (
        <details className="rounded-md border border-rule bg-panel px-4 py-3">
          <summary className="cursor-pointer font-medium text-plum">
            {dropped.length} compan{dropped.length === 1 ? "y" : "ies"} dropped by the reviewer
          </summary>
          <ul className="mt-3 flex flex-col gap-2">
            {dropped.map((lead) => (
              <li key={lead.domain} className="flex flex-wrap justify-between gap-x-4 text-sm">
                <span className="font-medium">{lead.company}</span>
                <span className="text-plum">{lead.review_notes.join("; ")}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
