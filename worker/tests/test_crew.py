from dataclasses import replace

from research.agents import (MarketScout, PageReader, Reviewer, looks_like_error_page, pick_extra_pages,
                             same_site_links)
from research.crew import ResearchCrew
from research.ledger import DEFAULT_QUOTAS, Ledger
from research.llm import FixtureLLM, LLMRequest
from research.models import Lead, Person, SearchResult
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
    assert [lead.company for lead in result.leads] == [
        "Pulse Arena Esports", "IronCore Gyms", "Riga Desk Club", "Northwind Cowork"]
    assert [lead.company for lead in result.dropped] == ["Baltic Dev Hub", "Tallinn Esports Hub"]
    assert all(lead.review == "awaiting_approval" for lead in result.leads)


def test_scout_drops_candidates_without_a_searched_source_or_own_website():
    drops = {e.message.split(":")[0].removeprefix("dropped "): e.data["reason"]
             for e in run_crew().events if e.kind == "drop" and e.agent == "Market scout"}
    assert drops == {
        "Global Snack Corp": "source is not a search result",
        "Kaunas Gaming Lab": "no company website found",  # gave the directory's own domain
        "Nordic Dev Studio": "no company website found",  # gave a review site's domain
    }


def test_scout_looks_up_a_missing_website_and_checks_its_host():
    class Reply:
        def complete_json(self, req):
            return {"candidates": [
                {"company": "Gym Eesti OÜ", "domain": "", "source_url": "https://dir.example/gyms"},
                {"company": "Ghost Corp", "domain": "", "source_url": "https://dir.example/gyms"},
            ]}, "stub"

    class Search:
        def search(self, query):
            if "official website" not in query:
                return [SearchResult("Gyms", "https://dir.example/gyms", "")]
            if "Gym Eesti" in query:  # an aggregator first, then a namesake-free company host
                return [SearchResult("x", "https://www.linkedin.com/company/gym-eesti", ""),
                        SearchResult("y", "https://www.gymeesti.ee/en", "")]
            return [SearchResult("z", "https://unrelated.example", "")]  # host doesn't name Ghost Corp

    events = []
    leads = MarketScout(Reply(), Search(), events.append).run({"industries": [{"name": "Gyms"}]}, 15)
    assert [(lead.company, lead.source_url, lead.found_via) for lead in leads] == [
        ("Gym Eesti OÜ", "https://gymeesti.ee", "https://dir.example/gyms")]
    assert any(e.message == "dropped Ghost Corp: no company website found" for e in events)


def test_lead_found_in_a_directory_is_read_from_its_own_site():
    riga = by_company(run_crew())["Riga Desk Club"]
    assert riga.source_url == "https://rigadeskclub.example"
    assert riga.found_via == "https://baltic-directory.example/coworking-riga"


def test_reader_follows_same_site_team_page_only():
    riga = by_company(run_crew())["Riga Desk Club"]
    # The partner link is on another domain and the news page doesn't exist: neither is evidence.
    assert riga.evidence_urls == ["https://rigadeskclub.example", "https://rigadeskclub.example/team"]
    # Martins and the Tartu opening appear only on the team page, so they verify against it.
    assert [p.name for p in riga.people] == ["Anna Liepa", "Martins Kalns"]
    assert [s.signal for s in riga.signals] == ["opening a new location"]
    assert (riga.fit_score, riga.tier) == (70, "A")


def test_reader_skips_guessed_about_page_that_is_a_404():
    class Site:
        def read(self, url):
            if url == "https://gymeesti.ee":
                return "Paketid. Treeni kõikides jõusaalides üle Eesti."  # no links: You.com strips menus
            return "[Liigu sisu juurde](https://gymeesti.ee/about#content) veateade 404 oled eksinud teelt."

    class NoModel:
        def complete_json(self, req):
            assert "veateade" not in req.user  # the 404 page never reaches the model
            return {"people": [], "signals": []}, "stub"

    events = []
    pages, _, _ = PageReader(NoModel(), Site(), events.append).run(
        "https://gymeesti.ee", "gymeesti.ee", "Gym Eesti OÜ", ["Gym Owner"])
    assert list(pages) == ["https://gymeesti.ee"]
    assert any("error page, skipped" in e.message for e in events)
    assert not looks_like_error_page("x" * 2000 + " call 404 555")  # long real pages are kept


def test_same_site_links_and_page_picking():
    page = ("[About](/about-us) [Blog](https://acme.example/blog/post-1) [Jobs](https://jobs.other.example/acme) "
            "[Home](https://www.acme.example/) [Contact](https://acme.example/contact#form) [Team](/team)")
    links = same_site_links(page, "https://acme.example/", "acme.example")
    assert links == ["https://acme.example/about-us", "https://acme.example/blog/post-1",
                     "https://acme.example/contact", "https://acme.example/team"]
    assert pick_extra_pages(links) == ["https://acme.example/about-us", "https://acme.example/blog/post-1"]


def test_reviewer_drops_parked_domain():
    tallinn = next(lead for lead in run_crew().dropped if lead.company == "Tallinn Esports Hub")
    assert tallinn.review_notes == ["source page is a parked or for-sale domain"]


def test_reviewer_accepts_own_host_when_page_text_lacks_the_name():
    def review(source_url):
        lead = Lead("Gym Eesti OÜ", "gymeesti.ee", source_url, "Gyms", "")
        return Reviewer(lambda event: None).run([lead], {source_url: "Paketid. Treeni kõikides jõusaalides."})

    assert len(review("https://gymeesti.ee")) == 1  # brand only in the logo, but the host names it
    assert review("https://tracxn.com/gyms") == []  # same text on a host that doesn't name it


def test_scout_never_fetches_an_unchecked_model_domain():
    bad_domains = ["127.0.0.1", "localhost", "169.254.169.254", "attacker.example"]

    class Reply:
        def complete_json(self, req):
            return {"candidates": [{"company": "Acme Mints", "domain": d, "source_url": "https://dir.example/x"}
                                   for d in bad_domains]}, "stub"

    class Search:
        def search(self, query):
            if "official website" in query:
                return [SearchResult("ip", "http://10.0.0.5/acme-mints", "")]  # IP literal, never accepted
            return [SearchResult("dir", "https://dir.example/x", "")]

    events = []
    assert MarketScout(Reply(), Search(), events.append).run({"industries": [{"name": "Mints"}]}, 15) == []
    assert sum("no company website found" in e.message for e in events) == len(bad_domains)


def test_scout_keeps_one_candidate_per_domain():
    class OneReplyLLM:
        def complete_json(self, req):
            return {"candidates": [
                {"company": "IronCore Gyms", "domain": "www.ironcoregyms.example", "source_url": "https://a.example/1"},
                {"company": "IronCore Gym Tartu", "domain": "ironcoregyms.example", "source_url": "https://a.example/2"},
            ]}, "stub"

    class TwoHits:
        def search(self, query):
            return [SearchResult("A", "https://a.example/1", ""), SearchResult("B", "https://a.example/2", "")]

    events = []
    leads = MarketScout(OneReplyLLM(), TwoHits(), events.append).run({"industries": [{"name": "Gyms"}]}, 15)
    assert [(lead.company, lead.source_url) for lead in leads] == [("IronCore Gyms", "https://ironcoregyms.example")]
    assert any("duplicate" in e.message for e in events)


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
    [kept] = Reviewer(lambda event: None).run([lead], {"https://p.example": "Pulse Arena Esports. Contact Liga Ozola, Head of Partnerships."})
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


def test_scout_asks_for_no_more_than_max_leads():
    llm = RecordingLLM()
    ledger = Ledger(None)
    ResearchCrew(llm, FixtureTools(FIXTURE_DIR, ledger), ledger, max_leads=3).run(PRODUCT)
    scout = next(r for r in llm.requests if r.role == "scout")
    assert "at most 3 candidates" in scout.system


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
