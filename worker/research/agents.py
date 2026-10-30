"""The five research agents.

Each one sees only the slice of the job it needs (its run() arguments are that
slice), runs its tool before its model, and returns a plain result to the
planner. The reviewer and the enricher use no model at all, so they cost no tokens.
"""

import json
import re
from collections.abc import Callable
from urllib.parse import urlparse

from .ledger import QuotaExceeded
from .llm import LLM, LLMRequest, LLMUnavailable
from .models import Event, Lead, Person, SearchResult, Signal
from .tools import TOOL_ERRORS, Tools

Emit = Callable[[Event], None]

ICP_SYSTEM = """You are an ICP strategist for B2B sales. Reply with one JSON object:
{"industries":[{"name":str,"naics":str,"confidence":0-1}],"company_sizes":[str],"regions":[str],
"personas":[{"title":str,"confidence":0-1}],"triggers":[{"signal":str,"confidence":0-1}],
"expansions":[{"segment":str,"reason":str,"confidence":0-1}]}
Give 2-4 industries, 2-4 buyer personas, 2-4 trigger events and 2-3 expansion segments. Be concise."""

SCOUT_SYSTEM = """You pick B2B prospects out of web search results. Use only companies the results name.
Reply with one JSON object: {"candidates":[{"company":str,"domain":str,"source_url":str,"industry":str,"why_fit":str}]}
source_url must be the URL of the result that names the company. industry must be one of the ICP industries.
Skip directories and listicles that don't describe a single company."""

READER_SYSTEM = """You read one company web page and extract sales facts. Use only what the page says.
Reply with one JSON object: {"people":[{"name":str,"title":str}],"signals":[{"signal":str,"quote":str}]}
Each quote must be copied word for word from the page. Prefer people whose titles match the target personas."""


def domain_of(value: str) -> str:
    host = urlparse(value if "//" in value else f"//{value}").hostname or ""
    return host.removeprefix("www.")


def build_queries(icp: dict, limit: int = 5) -> list[str]:
    """Search queries built without a model call, to save tokens."""
    industries = [i["name"] for i in sorted(icp.get("industries", []), key=lambda i: -i.get("confidence", 0))]
    regions = icp.get("regions", []) or [""]
    queries = [f"{industry} companies {region}".strip() for industry in industries for region in regions[:1]]
    triggers = [t["signal"] for t in icp.get("triggers", [])]
    if industries and triggers:
        queries.append(f"{industries[0]} {triggers[0]} {regions[0]}".strip())
    return list(dict.fromkeys(queries))[:limit]


class IcpStrategist:
    name = "ICP strategist"

    def __init__(self, llm: LLM, emit: Emit):
        self.llm, self.emit = llm, emit

    def run(self, product: str) -> dict:
        icp, source = self.llm.complete_json(LLMRequest("icp", "reason", ICP_SYSTEM, f"Product: {product}"))
        names = [i.get("name") for i in icp.get("industries", [])]
        self.emit(Event(self.name, "model", f"ICP drafted via {source}: {', '.join(names)}", {"icp": icp}))
        return icp


class MarketScout:
    name = "Market scout"

    def __init__(self, llm: LLM, tools: Tools, emit: Emit):
        self.llm, self.tools, self.emit = llm, tools, emit

    def run(self, brief: dict, max_leads: int) -> list[Lead]:
        """brief holds industries, regions, sizes and triggers only, never the product pitch."""
        results: dict[str, SearchResult] = {}
        for query in build_queries(brief):
            try:
                hits = self.tools.search(query)
            except TOOL_ERRORS as exc:
                kind = "budget" if isinstance(exc, QuotaExceeded) else "error"
                self.emit(Event(self.name, kind, f"search stopped: {exc}"))
                break
            for hit in hits:
                results.setdefault(hit.url, hit)
            self.emit(Event(self.name, "tool", f"searched '{query}': {len(hits)} results"))
        if not results:
            return []
        digest = "\n".join(f"- {r.url} | {r.title} | {r.content[:300]}" for r in results.values())
        reply, source = self.llm.complete_json(
            LLMRequest("scout", "bulk", SCOUT_SYSTEM, f"ICP: {json.dumps(brief)}\nResults:\n{digest}")
        )
        leads = []
        for cand in reply.get("candidates", []):
            url = cand.get("source_url", "")
            if url not in results:
                self.emit(Event(self.name, "drop", f"dropped {cand.get('company')}: source is not a search result",
                                {"source_url": url}))
                continue
            leads.append(Lead(company=cand.get("company", ""), domain=domain_of(cand.get("domain") or url),
                              source_url=url, industry=cand.get("industry", ""), why_fit=cand.get("why_fit", "")))
            if len(leads) >= max_leads:
                break
        self.emit(Event(self.name, "model", f"{len(leads)} candidates with sources via {source}"))
        return leads


class PageReader:
    name = "Page reader"

    def __init__(self, llm: LLM, tools: Tools, emit: Emit):
        self.llm, self.tools, self.emit = llm, tools, emit

    def run(self, source_url: str, company: str, personas: list[str]) -> tuple[str, list[Person], list[Signal]]:
        """Returns (page text, people, signals). Empty page text means the source couldn't be read."""
        try:
            page = self.tools.read(source_url)
        except TOOL_ERRORS as exc:
            self.emit(Event(self.name, "error", f"{company}: source unreadable ({exc})"))
            return "", [], []
        self.emit(Event(self.name, "tool", f"read {source_url} ({len(page)} chars)"))
        user = f"Target personas: {', '.join(personas)}\nCompany: {company}\nPage {source_url}:\n{page}"
        try:
            reply, source = self.llm.complete_json(LLMRequest("reader", "bulk", READER_SYSTEM, user, source_url))
        except LLMUnavailable as exc:
            self.emit(Event(self.name, "error", f"{company}: no model available ({exc})"))
            return page, [], []
        people = [Person(p["name"], p.get("title", "")) for p in reply.get("people", []) if p.get("name")]
        signals = [Signal(s["signal"], s.get("quote", "")) for s in reply.get("signals", []) if s.get("signal")]
        self.emit(Event(self.name, "model", f"{company}: {len(people)} people, {len(signals)} signals via {source}"))
        return page, people, signals


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


class Reviewer:
    """Checks every lead against the evidence the crew actually fetched."""

    name = "Reviewer"

    def __init__(self, emit: Emit):
        self.emit = emit

    def run(self, leads: list[Lead], evidence: dict[str, str]) -> list[Lead]:
        kept = []
        for lead in leads:
            page = evidence.get(lead.source_url, "")
            if not page:
                lead.review = "dropped"
                lead.review_notes.append("source page could not be read")
                self.emit(Event(self.name, "drop", f"dropped {lead.company}: source could not be verified"))
                continue
            text = _normalize(page)
            for signal in lead.signals:
                signal.verified = bool(signal.quote) and _normalize(signal.quote) in text
                if not signal.verified:
                    lead.review_notes.append(f"removed unsupported claim: {signal.signal}")
                    self.emit(Event(self.name, "flag", f"{lead.company}: '{signal.signal}' is not on the source page"))
            lead.signals = [s for s in lead.signals if s.verified]
            lead.review = "awaiting_approval"
            kept.append(lead)
        return kept


_EMAIL_STATUS = {"valid": "valid", "accept_all": "risky"}


class ContactEnricher:
    """Spends Hunter credits on tier-A leads only (50 a month on the free plan)."""

    name = "Contact enricher"

    def __init__(self, tools: Tools, emit: Emit):
        self.tools, self.emit = tools, emit

    def run(self, tier: str, domain: str, people: list[Person]) -> tuple[str, list[Person]]:
        if tier != "A":
            return "skipped", people
        try:
            emails = self.tools.find_contacts(domain)
        except QuotaExceeded as exc:
            self.emit(Event(self.name, "budget", f"{domain}: enrichment blocked, {exc}"))
            return "no_credits", people
        except TOOL_ERRORS as exc:
            self.emit(Event(self.name, "error", f"{domain}: lookup failed ({exc})"))
            return "failed", people
        by_name = {p.name.lower(): p for p in people}
        for entry in emails:
            name = f"{entry.get('first_name') or ''} {entry.get('last_name') or ''}".strip()
            if not name or not entry.get("value"):
                continue  # generic inboxes like info@ are no use for outreach
            person = by_name.get(name.lower()) or Person(name, entry.get("position") or "")
            person.email = entry["value"]
            person.email_status = _EMAIL_STATUS.get((entry.get("verification") or {}).get("status"), "unknown")
            person.email_confidence = int(entry.get("confidence") or 0)
            if name.lower() not in by_name:
                people.append(person)
                by_name[name.lower()] = person
        found = sum(1 for p in people if p.email)
        self.emit(Event(self.name, "tool", f"{domain}: {found} named contacts with email"))
        return "enriched", people
