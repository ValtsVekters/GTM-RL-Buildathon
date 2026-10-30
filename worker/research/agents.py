"""The five research agents.

Each one sees only the slice of the job it needs (its run() arguments are that
slice), runs its tool before its model, and returns a plain result to the
planner. The reviewer and the enricher use no model at all, so they cost no tokens.
"""

import ipaddress
import json
import re
from collections import Counter
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

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
source_url is the URL of the result that names the company; a directory or listicle is fine.
domain is the company's own website domain (like acme.com), never the directory's. Leave it empty if unknown.
industry must be one of the ICP industries."""

READER_SYSTEM = """You read one company's own web page and extract sales facts about that company only.
Reply with one JSON object: {"people":[{"name":str,"title":str}],"signals":[{"signal":str,"quote":str}]}
name is a person's name, not a job title. Only include people who work at the company.
Each quote must be copied word for word from the page. Prefer people whose titles match the target personas."""

# Directories, review sites and social networks: good for finding companies, never
# evidence about one. A candidate whose "own" domain is one of these is dropped.
AGGREGATOR_HOSTS = (
    "clutch.co", "goodfirms.co", "tracxn.com", "crunchbase.com", "linkedin.com", "facebook.com",
    "instagram.com", "x.com", "twitter.com", "youtube.com", "wikipedia.org", "yelp.com", "glassdoor.com",
    "indeed.com", "zoominfo.com", "apollo.io", "g2.com", "capterra.com", "trustpilot.com", "medium.com",
)


def domain_of(value: str) -> str:
    host = urlparse(value if "//" in value else f"//{value}").hostname or ""
    return host.rstrip(".").removeprefix("www.")


def is_aggregator(domain: str) -> bool:
    return any(domain == host or domain.endswith(f".{host}") for host in AGGREGATOR_HOSTS)


def _public_host(domain: str) -> bool:
    """A dotted hostname, not an IP literal or a single label such as localhost."""
    if "." not in domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
        return False
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return True
    return False


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
        # Capping the list keeps the reply inside the model's output limit (an uncapped
        # list of 25 results was cut off mid-JSON) and spends fewer tokens.
        system = (f"{SCOUT_SYSTEM}\nReturn at most {max_leads} candidates, best fit first. "
                  "Keep why_fit under 15 words.")
        reply, source = self.llm.complete_json(
            LLMRequest("scout", "bulk", system, f"ICP: {json.dumps(brief)}\nResults:\n{digest}")
        )
        candidates = reply.get("candidates", [])
        # A site that several candidates were found on is a directory, so it can't be any one company's own site.
        cited = Counter(domain_of(c.get("source_url", "")) for c in candidates)
        directory_hosts = {host for host, count in cited.items() if count > 1}
        leads: list[Lead] = []
        seen_domains: set[str] = set()
        for cand in candidates:
            company, url = cand.get("company", ""), cand.get("source_url", "")
            if url not in results:
                self._drop(company, "source is not a search result", url)
                continue
            domain = domain_of(cand.get("domain") or "")
            # A model-written domain becomes a fetch target, so it must be a public hostname that
            # either came back from the search or carries the company's name.
            searched = domain in {domain_of(u) for u in results} or _host_names(company, domain)
            if not (domain and searched and _public_host(domain)) or is_aggregator(domain) or domain in directory_hosts:
                domain = self._find_website(company, directory_hosts)
            if not domain:
                self._drop(company, "no company website found", url)
            elif domain in seen_domains:
                self._drop(company, f"duplicate of another candidate on {domain}", url)
            else:
                seen_domains.add(domain)
                # Evidence comes from the company's own site: the search result itself when it
                # is on that site, otherwise the homepage. A directory only helps find it.
                own_page = url if domain_of(url) == domain else f"https://{domain}"
                leads.append(Lead(company=company, domain=domain, source_url=own_page, found_via=url,
                                  industry=cand.get("industry", ""), why_fit=cand.get("why_fit", "")))
                if len(leads) >= max_leads:
                    break
        self.emit(Event(self.name, "model", f"{len(leads)} candidates with their own websites via {source}"))
        return leads

    def _drop(self, company: str, reason: str, source_url: str) -> None:
        self.emit(Event(self.name, "drop", f"dropped {company}: {reason}", {"source_url": source_url, "reason": reason}))

    def _find_website(self, company: str, directory_hosts: set[str]) -> str:
        """One search for the company's own site. A hit counts only when its host carries the
        company's name, so a directory or a namesake page is never taken as the company."""
        try:
            hits = self.tools.search(f'"{company}" official website')
        except TOOL_ERRORS as exc:
            self.emit(Event(self.name, "error", f"{company}: website lookup failed ({exc})"))
            return ""
        for hit in hits:
            domain = domain_of(hit.url)
            if (domain and _public_host(domain) and not is_aggregator(domain) and domain not in directory_hosts
                    and _host_names(company, domain)):
                self.emit(Event(self.name, "tool", f"{company}: own website is {domain}"))
                return domain
        return ""


class PageReader:
    name = "Page reader"

    def __init__(self, llm: LLM, tools: Tools, emit: Emit):
        self.llm, self.tools, self.emit = llm, tools, emit

    def run(self, source_url: str, domain: str, company: str,
            personas: list[str]) -> tuple[dict[str, str], list[Person], list[Signal]]:
        """Reads the source page plus up to two About/Team/News pages on the same site, then makes one
        model call over all of them. Returns ({url: text}, people, signals); {} means the source failed."""
        try:
            page = self.tools.read(source_url)
        except TOOL_ERRORS as exc:
            self.emit(Event(self.name, "error", f"{company}: source unreadable ({exc})"))
            return {}, [], []
        pages = {source_url: page}
        # Homepages rarely name staff or news. Only links on the company's own host are followed,
        # so text on a scraped page can't send the crew to another site.
        extras = pick_extra_pages(same_site_links(page, source_url, domain)) or [urljoin(source_url, "/about")]
        for url in extras:
            if url in pages:
                continue
            try:
                text = self.tools.read(url)
            except TOOL_ERRORS:
                self.emit(Event(self.name, "tool", f"{company}: {url} not available"))
                continue
            if looks_like_error_page(text):  # a guessed /about often lands on the site's 404 page
                self.emit(Event(self.name, "tool", f"{company}: {url} is an error page, skipped"))
                continue
            pages[url] = text
        self.emit(Event(self.name, "tool", f"read {len(pages)} page(s) on {domain}: {', '.join(pages)}"))
        body = "\n\n".join(f"--- {url}\n{text[:PAGE_PROMPT_CHARS]}" for url, text in pages.items())
        user = f"Target personas: {', '.join(personas)}\nCompany: {company}\nPages from the company's own site:\n{body}"
        try:
            reply, source = self.llm.complete_json(LLMRequest("reader", "bulk", READER_SYSTEM, user, source_url))
        except LLMUnavailable as exc:
            self.emit(Event(self.name, "error", f"{company}: no model available ({exc})"))
            return pages, [], []
        people = [Person(p["name"], p.get("title", "")) for p in reply.get("people", []) if p.get("name")]
        signals = [Signal(s["signal"], s.get("quote", "")) for s in reply.get("signals", []) if s.get("signal")]
        self.emit(Event(self.name, "model", f"{company}: {len(people)} people, {len(signals)} signals via {source}"))
        return pages, people, signals


PAGE_PROMPT_CHARS = 3000  # per page, so three pages stay near 2.5k tokens
# Path words for the extra pages, best group first: who works there, then what's new, then contacts.
EXTRA_PAGE_WORDS = (
    ("team", "people", "leadership", "management", "about", "meist", "par-mums", "apie"),
    ("news", "press", "blog", "uudised", "jaunumi", "naujienos"),
    ("contact", "kontakt"),
)


def same_site_links(page: str, source_url: str, domain: str) -> list[str]:
    """Markdown links on the page that stay on the company's own host."""
    links = []
    own_path = urlparse(source_url).path.rstrip("/")
    for href in re.findall(r"\]\(([^)\s]+)\)", page):
        url = urljoin(source_url, href).split("#")[0]
        # Same host only, and not the source page again (www. and a trailing slash don't make it new).
        if url.startswith(("https://", "http://")) and domain_of(url) == domain \
                and urlparse(url).path.rstrip("/") != own_path:
            links.append(url)
    return list(dict.fromkeys(links))


_ERROR_PAGE_MARKERS = ("404", "not found", "page does not exist", "page doesn't exist",
                       "ei eksisteeri", "nav atrasta", "nerastas", "nerasta")


def looks_like_error_page(text: str) -> bool:
    """A short page that says it's missing. Long pages are kept even if "404" appears in them."""
    low = text.lower()
    return len(text) < 1500 and any(marker in low for marker in _ERROR_PAGE_MARKERS)


def pick_extra_pages(links: list[str], limit: int = 2) -> list[str]:
    picked: list[str] = []
    for words in EXTRA_PAGE_WORDS:
        match = next((u for u in links if u not in picked and any(w in urlparse(u).path.lower() for w in words)), None)
        if match:
            picked.append(match)
        if len(picked) >= limit:
            break
    return picked


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


_LEGAL_SUFFIXES = {"oü", "ou", "as", "sia", "uab", "ltd", "llc", "inc", "gmbh", "ab", "oy", "plc", "co", "corp"}


def _name_words(company: str) -> list[str]:
    return [w for w in re.sub(r"[^\w\s-]", " ", company.lower()).split() if w not in _LEGAL_SUFFIXES]


def _names_company(company: str, text: str) -> bool:
    """True when the page names the company: its full name without legal suffix, or its first two words."""
    words = _name_words(company)
    if not words:
        return False
    return " ".join(words) in text or " ".join(words[:2]) in text


def _host_names(company: str, domain: str) -> bool:
    """True when the domain (minus its TLD) carries the company name, e.g. "Gym Eesti OÜ" -> gymeesti.ee."""
    label = domain.rsplit(".", 1)[0].replace(".", "").replace("-", "")
    words = [w.replace("-", "") for w in _name_words(company)]
    if not words:
        return False
    return "".join(words) in label or (len(words[0]) >= 4 and words[0] in label)


_PARKED_PHRASES = ("domain is for sale", "buy this domain", "domain may be for sale", "this domain is parked")


def _page_problem(lead: Lead, text: str) -> str:
    """Why this page can't count as the company's own, or "" when it can. Homepages often carry the
    brand only in a logo, so a host that carries the company's name also counts, unless it's parked."""
    if any(phrase in text for phrase in _PARKED_PHRASES):
        return "source page is a parked or for-sale domain"
    if _names_company(lead.company, text) or _host_names(lead.company, domain_of(lead.source_url)):
        return ""
    return "source page does not name the company"


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
            problem = _page_problem(lead, _normalize(page))
            if problem:
                lead.review = "dropped"
                lead.review_notes.append(problem)
                self.emit(Event(self.name, "drop", f"dropped {lead.company}: {problem}"))
                continue
            # Quotes and people may come from any page the reader fetched on the company's site.
            text = _normalize(" ".join(evidence.get(url, "") for url in lead.evidence_urls or [lead.source_url]))
            for signal in lead.signals:
                signal.verified = bool(signal.quote) and _normalize(signal.quote) in text
                if not signal.verified:
                    lead.review_notes.append(f"removed unsupported claim: {signal.signal}")
                    self.emit(Event(self.name, "flag", f"{lead.company}: '{signal.signal}' is not on the pages read"))
            lead.signals = [s for s in lead.signals if s.verified]
            lead.people = self._verified_people(lead, text)
            lead.review = "awaiting_approval"
            kept.append(lead)
        return kept

    def _verified_people(self, lead: Lead, text: str) -> list[Person]:
        """People raise the fit score and so decide who spends Hunter credits: a name
        must be on the source page, and a title that isn't there earns no persona points."""
        verified = []
        for person in lead.people:
            if _normalize(person.name) not in text:
                lead.review_notes.append(f"removed person not on source page: {person.name}")
                self.emit(Event(self.name, "flag", f"{lead.company}: {person.name} is not on the pages read"))
                continue
            if person.title and _normalize(person.title) not in text:
                lead.review_notes.append(f"cleared title not on source page: {person.name}, {person.title}")
                person.title = ""
            verified.append(person)
        return verified


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
