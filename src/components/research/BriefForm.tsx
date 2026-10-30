"use client";

import type { Mode, ResearchInput } from "@/lib/research";
import { SAMPLE_PRODUCT } from "@/lib/research";

interface Props {
  input: ResearchInput;
  running: boolean;
  onChange: (input: ResearchInput) => void;
  onRun: () => void;
  onStop: () => void;
}

const MODES: { value: Mode; label: string; help: string }[] = [
  {
    value: "demo",
    label: "Sample data",
    help: "Free and offline. Always researches the VectorMints example with fictional companies, whatever you type.",
  },
  {
    value: "live",
    label: "Live web",
    help: "Searches the real web for your description. Uses Parasail and You.com credits, about 20 seconds per run.",
  },
];

export function BriefForm({ input, running, onChange, onRun, onStop }: Props) {
  const tooShort = input.product.trim().length < 10;
  const mode = MODES.find((m) => m.value === input.mode)!;

  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (!tooShort && !running) onRun();
      }}
    >
      <div className="flex flex-col gap-3">
        <label htmlFor="product" className="text-3xl font-semibold leading-tight tracking-tight text-balance">
          What do you sell, and to whom?
        </label>
        <textarea
          id="product"
          rows={5}
          maxLength={1000}
          value={input.product}
          disabled={running}
          onChange={(e) => onChange({ ...input, product: e.target.value })}
          placeholder="Energy mints with caffeine + L-theanine, sold to offices and gyms in the Baltics."
          className="w-full resize-y rounded-md border border-rule bg-panel px-3 py-2.5 text-base leading-relaxed placeholder:text-muted/70 disabled:opacity-70"
        />
        <div className="flex items-center justify-between text-sm text-muted">
          <button
            type="button"
            disabled={running}
            onClick={() => onChange({ ...input, product: SAMPLE_PRODUCT })}
            className="underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink disabled:opacity-50"
          >
            Use the VectorMints example
          </button>
          <span aria-live="polite">{input.product.length}/1000</span>
        </div>
      </div>

      <fieldset className="flex flex-col gap-2" disabled={running}>
        <legend className="mb-2 text-sm font-medium">Where to look</legend>
        <div className="grid grid-cols-2 rounded-md border border-rule bg-panel p-1" role="radiogroup">
          {MODES.map((m) => (
            <label
              key={m.value}
              className={`cursor-pointer rounded px-3 py-2 text-center text-sm font-medium transition-colors ${
                input.mode === m.value ? "bg-ink text-paper" : "text-muted hover:text-ink"
              }`}
            >
              <input
                type="radio"
                name="mode"
                value={m.value}
                checked={input.mode === m.value}
                onChange={() => onChange({ ...input, mode: m.value })}
                className="sr-only"
              />
              {m.label}
            </label>
          ))}
        </div>
        <p className="text-sm leading-snug text-muted">{mode.help}</p>
      </fieldset>

      <fieldset className="flex items-center justify-between gap-4" disabled={running}>
        <legend className="sr-only">Number of leads</legend>
        <label htmlFor="max-leads" className="text-sm font-medium">
          Leads to find
        </label>
        <div className="flex items-center rounded-md border border-rule bg-panel">
          <button
            type="button"
            aria-label="Fewer leads"
            onClick={() => onChange({ ...input, max_leads: Math.max(1, input.max_leads - 1) })}
            className="px-3 py-1.5 text-lg leading-none text-muted hover:text-ink disabled:opacity-40"
            disabled={input.max_leads <= 1}
          >
            −
          </button>
          <input
            id="max-leads"
            type="number"
            min={1}
            max={15}
            value={input.max_leads}
            onChange={(e) =>
              onChange({ ...input, max_leads: Math.min(15, Math.max(1, Number(e.target.value) || 1)) })
            }
            className="w-10 border-x border-rule bg-transparent py-1.5 text-center tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
          />
          <button
            type="button"
            aria-label="More leads"
            onClick={() => onChange({ ...input, max_leads: Math.min(15, input.max_leads + 1) })}
            className="px-3 py-1.5 text-lg leading-none text-muted hover:text-ink disabled:opacity-40"
            disabled={input.max_leads >= 15}
          >
            +
          </button>
        </div>
      </fieldset>

      {running ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded-md border border-ink px-4 py-3 text-base font-semibold hover:bg-ink hover:text-paper"
        >
          Stop watching this run
        </button>
      ) : (
        <button
          type="submit"
          disabled={tooShort}
          className="rounded-md bg-moss px-4 py-3 text-base font-semibold text-white hover:bg-ink disabled:cursor-not-allowed disabled:bg-rule disabled:text-muted"
        >
          Find leads
        </button>
      )}
      {tooShort && !running && (
        <p className="-mt-3 text-sm text-muted">Write at least 10 characters about what you sell.</p>
      )}
    </form>
  );
}
