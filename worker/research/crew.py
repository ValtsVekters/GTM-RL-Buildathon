"""The planner: runs the five agents in order and hands each one only its slice.

Order matters for the free budget: the reviewer runs before scoring and
enrichment, so unverified leads never spend Hunter credits.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .agents import ContactEnricher, IcpStrategist, MarketScout, PageReader, Reviewer
from .ledger import Ledger
from .llm import LLM
from .models import Event, Lead
from .scoring import score_lead, tier_for
from .tools import Tools


@dataclass
class ResearchResult:
    icp: dict
    leads: list[Lead]
    dropped: list[Lead]
    events: list[Event]
    quota_left: dict[str, int]


def scout_brief(icp: dict) -> dict:
    """The part of the ICP the scout may see."""
    return {key: icp.get(key, []) for key in ("industries", "regions", "company_sizes", "triggers")}


class ResearchCrew:
    def __init__(self, llm: LLM, tools: Tools, ledger: Ledger,
                 on_event: Callable[[Event], None] | None = None, max_leads: int = 15):
        self.llm, self.tools, self.ledger = llm, tools, ledger
        self.on_event = on_event
        self.max_leads = max_leads

    def run(self, product: str) -> ResearchResult:
        events: list[Event] = []

        def emit(event: Event) -> None:
            events.append(event)
            if self.on_event:
                self.on_event(event)

        icp = IcpStrategist(self.llm, emit).run(product)
        leads = MarketScout(self.llm, self.tools, emit).run(scout_brief(icp), self.max_leads)

        personas = [p.get("title", "") for p in icp.get("personas", [])]
        reader = PageReader(self.llm, self.tools, emit)
        evidence: dict[str, str] = {}
        for lead in leads:
            page, lead.people, lead.signals = reader.run(lead.source_url, lead.company, personas)
            if page:
                evidence[lead.source_url] = page

        kept = Reviewer(emit).run(leads, evidence)
        for lead in kept:
            lead.fit_score = score_lead(lead, icp)
            lead.tier = tier_for(lead.fit_score)
        kept.sort(key=lambda lead: -lead.fit_score)

        enricher = ContactEnricher(self.tools, emit)
        for lead in kept:
            lead.enrichment, lead.people = enricher.run(lead.tier, lead.domain, lead.people)

        emit(Event("Planner", "done", f"{len(kept)} leads awaiting human approval, "
                                      f"{len(leads) - len(kept)} dropped"))
        dropped = [lead for lead in leads if lead.review == "dropped"]
        return ResearchResult(icp, kept, dropped, events, self.ledger.snapshot())
