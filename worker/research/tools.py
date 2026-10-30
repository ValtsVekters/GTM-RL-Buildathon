"""Agent tools: web search (Tavily), page reading (Jina Reader), contacts (Hunter).

Each call goes through the cache first and reserves quota only on a cache miss.
"""

import json
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from .cache import Cache
from .http import ProviderError, Transport, request_json
from .ledger import Ledger, QuotaExceeded
from .models import SearchResult


class ToolUnavailable(Exception):
    """A tool can't run: no key, or the page can't be fetched."""


TOOL_ERRORS = (ToolUnavailable, QuotaExceeded, ProviderError)


class Tools(Protocol):
    def search(self, query: str) -> list[SearchResult]: ...
    def read(self, url: str) -> str: ...
    def find_contacts(self, domain: str) -> list[dict]: ...


def _require(env: str) -> str:
    value = os.getenv(env, "").strip()
    if not value:
        raise ToolUnavailable(f"{env} not set")
    return value


def _results(raw: dict) -> list[SearchResult]:
    return [
        SearchResult(r.get("title", ""), r["url"], r.get("content", ""))
        for r in raw.get("results", [])
        if r.get("url")
    ]


class LiveTools:
    def __init__(self, ledger: Ledger, cache: Cache, transport: Transport = request_json, page_chars: int = 4000):
        self.ledger = ledger
        self.cache = cache
        self.transport = transport
        self.page_chars = page_chars  # pages are cut short to save model tokens

    def search(self, query: str) -> list[SearchResult]:
        key = Cache.key("tavily", query)
        raw = self.cache.get(key)
        if raw is None:
            api_key = _require("TAVILY_API_KEY")
            self.ledger.reserve("tavily")  # basic search = 1 credit
            raw = self.transport("POST", "https://api.tavily.com/search", {"Authorization": f"Bearer {api_key}"},
                                 {"query": query, "max_results": 5, "search_depth": "basic"})
            self.cache.set(key, raw)
        return _results(raw)

    def read(self, url: str) -> str:
        key = Cache.key("jina", url)
        text = self.cache.get(key)
        if text is None:
            api_key = os.getenv("JINA_API_KEY", "").strip()
            self.ledger.reserve("jina")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            reply = self.transport("GET", f"https://r.jina.ai/{url}", headers, None)
            text = reply if isinstance(reply, str) else json.dumps(reply)
            self.cache.set(key, text)
        return text[: self.page_chars]

    def find_contacts(self, domain: str) -> list[dict]:
        key = Cache.key("hunter", domain)
        raw = self.cache.get(key)
        if raw is None:
            api_key = _require("HUNTER_API_KEY")
            self.ledger.reserve("hunter")
            raw = self.transport("GET", f"https://api.hunter.io/v2/domain-search?domain={quote(domain)}&limit=5",
                                 {"X-API-KEY": api_key}, None)
            self.cache.set(key, raw)
        return raw.get("data", {}).get("emails", [])


class FixtureTools:
    """Offline tools backed by saved files. They still reserve quota, so the
    budget limits (such as running out of Hunter credits) can be shown offline."""

    def __init__(self, fixture_dir: Path, ledger: Ledger):
        self.ledger = ledger
        self._search = self._load(fixture_dir / "search.json")
        self._pages = self._load(fixture_dir / "pages.json")
        self._contacts = self._load(fixture_dir / "hunter.json")

    @staticmethod
    def _load(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def search(self, query: str) -> list[SearchResult]:
        self.ledger.reserve("tavily")
        return _results({"results": self._search.get(query, self._search.get("*", []))})

    def read(self, url: str) -> str:
        self.ledger.reserve("jina")
        if url not in self._pages:
            raise ToolUnavailable(f"HTTP 404 for {url}")
        return self._pages[url]

    def find_contacts(self, domain: str) -> list[dict]:
        self.ledger.reserve("hunter")
        return self._contacts.get(domain, [])
