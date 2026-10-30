from dataclasses import replace

from research.agents import Reviewer
from research.crew import ResearchCrew
from research.ledger import DEFAULT_QUOTAS, Ledger
from research.llm import FixtureLLM, LLMRequest
from research.models import Lead, Person
from research.run import FIXTURE_DIR
from research.tools import FixtureTools

PRODUCT = (FIXTURE_DIR / "product.txt").read_text(encoding="utf-8").strip()


class RecordingLLM(FixtureLLM):
    def __init__(self):
        super().__init__(FIXTURE_DIR)
        self.requests: list[LLMRequest] = []

    def complete_json(self, req):
        self.requests.append(req)
        return super().complete_json(req)


def run_crew(hunter_credits: int | None = None, llm=None):
    quotas = dict(DEFAULT_QUOTAS)
    if hunter_credits is not None:
        quotas["hunter"] = replace(quotas["hunter"], limit=hunter_credits)
    ledger = Ledger(None, quotas)
    crew = ResearchCrew(llm or FixtureLLM(FIXTURE_DIR), FixtureTools(FIXTURE_DIR, ledger), ledger)
    return crew.run(PRODUCT)


def by_company(result):
    return {lead.company: lead for lead in result.leads}


def test_keeps_only_leads_with_verified_sources():
    result = run_crew()
    assert [lead.company for lead in result.leads] == ["Pulse Arena Esports", "IronCore Gyms", "Northwind Cowork"]
    assert [lead.company for lead in result.dropped] == ["Baltic Dev Hub"]
    assert all(lead.review == "awaiting_approval" for lead in result.leads)


def test_scout_drops_candidate_whose_source_was_not_searched():
    drops = [e for e in run_crew().events if e.kind == "drop" and e.agent == "Market scout"]
    assert [e.data["source_url"] for e in drops] == ["https://globalsnack.example/press"]


def test_reviewer_removes_claim_not_on_source_page():
    ironcore = by_company(run_crew())["IronCore Gyms"]
    assert [s.signal for s in ironcore.signals] == ["opening a new location"]
    assert any("supplement" in note for note in ironcore.review_notes)


def test_reviewer_removes_person_not_on_source_page():
    # The reader fixture invents "Janis Berzins, Office Manager" for Northwind. Kept, that
    # persona match would lift Northwind to tier A and spend a Hunter credit.
    northwind = by_company(run_crew())["Northwind Cowork"]
    assert [p.name for p in northwind.people] == ["Ruta Kazlauskaite"]
    assert (northwind.tier, northwind.enrichment) == ("B", "skipped")


def test_reviewer_clears_title_not_on_source_page():
    lead = Lead("Pulse Arena Esports", "pulsearena.example", "https://p.example", "Esports organizations", "",
                people=[Person("Liga Ozola", "Chief Executive Officer")])
    [kept] = Reviewer(lambda event: None).run([lead], {"https://p.example": "Contact Liga Ozola, Head of Partnerships."})
    assert [(p.name, p.title) for p in kept.people] == [("Liga Ozola", "")]


def test_tiers_and_enrichment_follow_the_score():
    leads = by_company(run_crew())
    assert (leads["Pulse Arena Esports"].tier, leads["Pulse Arena Esports"].enrichment) == ("A", "enriched")
    assert (leads["Northwind Cowork"].tier, leads["Northwind Cowork"].enrichment) == ("B", "skipped")
    liga = leads["Pulse Arena Esports"].people[0]
    assert (liga.email, liga.email_status) == ("liga.ozola@pulsearena.example", "valid")
    assert all(p.email != "info@pulsearena.example" for p in leads["Pulse Arena Esports"].people)


def test_enrichment_blocks_when_hunter_credits_run_out():
    result = run_crew(hunter_credits=1)
    leads = by_company(result)
    assert leads["Pulse Arena Esports"].enrichment == "enriched"
    assert leads["IronCore Gyms"].enrichment == "no_credits"
    assert any(e.kind == "budget" and e.agent == "Contact enricher" for e in result.events)
    assert result.quota_left["hunter"] == 0


def test_agents_only_see_their_slice():
    llm = RecordingLLM()
    run_crew(llm=llm)
    scout = next(r for r in llm.requests if r.role == "scout")
    readers = [r for r in llm.requests if r.role == "reader"]
    assert PRODUCT not in scout.user and "personas" not in scout.user
    for req in readers:
        assert PRODUCT not in req.user
        other_urls = [r.fixture_key for r in readers if r is not req]
        assert not any(url in req.user for url in other_urls)
