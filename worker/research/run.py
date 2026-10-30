"""Run the research crew from the command line (from worker/).

  uv run python -m research.run --fixture                     offline, saved VectorMints data
  uv run python -m research.run --fixture --hunter-credits 1  shows enrichment blocked at 0 credits
  uv run python -m research.run "what you sell"               live, free-tier providers from ../.env
"""

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

from dotenv import load_dotenv

from .cache import Cache
from .crew import ResearchCrew
from .ledger import DEFAULT_QUOTAS, Ledger
from .llm import FixtureLLM, LLMRouter, LLMUnavailable
from .models import Event
from .tools import FixtureTools, LiveTools

WORKER_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "vectormints"
CACHE_DIR = WORKER_DIR / ".cache"


def print_event(event: Event) -> None:
    print(f"[{event.agent}] {event.kind:<6} {event.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the free-tier research crew.")
    parser.add_argument("product", nargs="?", help="what you sell, in one or two sentences")
    parser.add_argument("--fixture", action="store_true", help="run offline on saved VectorMints data")
    parser.add_argument("--max-leads", type=int, default=15)
    parser.add_argument("--hunter-credits", type=int, help="cap Hunter credits for this run, e.g. 1 to demo the block")
    parser.add_argument("--json", type=Path, help="also write the full result to this file")
    args = parser.parse_args(argv)

    quotas = dict(DEFAULT_QUOTAS)
    if args.hunter_credits is not None:
        quotas["hunter"] = replace(quotas["hunter"], limit=min(args.hunter_credits, quotas["hunter"].limit))

    if args.fixture:
        product = args.product or (FIXTURE_DIR / "product.txt").read_text(encoding="utf-8").strip()
        ledger = Ledger(None, quotas)
        llm, tools = FixtureLLM(FIXTURE_DIR), FixtureTools(FIXTURE_DIR, ledger)
    else:
        if not args.product:
            parser.error("give a product description, or use --fixture")
        load_dotenv(WORKER_DIR.parent / ".env")
        product = args.product
        ledger = Ledger(CACHE_DIR / "quota.json", quotas)
        cache = Cache(CACHE_DIR / "responses")
        llm, tools = LLMRouter(ledger, cache), LiveTools(ledger, cache)

    print(f"Product: {product}\n")
    try:
        result = ResearchCrew(llm, tools, ledger, on_event=print_event, max_leads=args.max_leads).run(product)
    except LLMUnavailable as exc:
        print(f"\nNo model available: {exc}\nRun check_keys.py to see which keys are missing.")
        return 1

    print("\nTier Score  Company                 Enrichment  Contacts")
    for lead in result.leads:
        contacts = ", ".join(f"{p.name} <{p.email or 'no email'}> {p.email_status}" for p in lead.people) or "none"
        print(f"  {lead.tier}  {lead.fit_score:>4}   {lead.company:<22}  {lead.enrichment:<10}  {contacts}")
    print(f"\nFree quota left: {result.quota_left}")
    if args.json:
        args.json.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Full result written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
