from datetime import UTC, datetime

import pytest

from research.cache import Cache
from research.ledger import Ledger, Quota, QuotaExceeded
from research.tools import LiveTools, ToolUnavailable


def clock(*stamp):
    return lambda: datetime(*stamp, tzinfo=UTC)


def test_reserve_refuses_at_the_limit():
    ledger = Ledger(None, {"hunter": Quota(2, "month")})
    ledger.reserve("hunter")
    ledger.reserve("hunter")
    with pytest.raises(QuotaExceeded):
        ledger.reserve("hunter")
    assert ledger.remaining("hunter") == 0


def test_monthly_quota_resets_next_month(tmp_path):
    path = tmp_path / "quota.json"
    october = Ledger(path, {"hunter": Quota(1, "month")}, clock(2026, 10, 31))
    october.reserve("hunter")
    assert Ledger(path, {"hunter": Quota(1, "month")}, clock(2026, 10, 31)).remaining("hunter") == 0
    assert Ledger(path, {"hunter": Quota(1, "month")}, clock(2026, 11, 1)).remaining("hunter") == 1


def test_search_is_cached_and_reserved_once(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    calls = []

    def transport(method, url, headers, body):
        calls.append(body["query"])
        return {"results": [{"title": "A", "url": "https://a.example", "content": "x"}, {"title": "no url"}]}

    ledger = Ledger(None)
    tools = LiveTools(ledger, Cache(None), transport)
    first = tools.search("gyms Estonia")
    second = tools.search("gyms Estonia")
    assert [r.url for r in first] == ["https://a.example"] == [r.url for r in second]
    assert calls == ["gyms Estonia"] and ledger.used("tavily") == 1


def test_search_falls_back_to_you_com_without_tavily_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("YOU_API_KEY", "you-test")
    calls = []

    def transport(method, url, headers, body):
        calls.append((url, headers.get("X-API-Key")))
        return {"results": {"web": [{"title": "Gym", "url": "https://gym.example", "description": "A gym",
                                     "snippets": ["Opens in Tartu"]}, {"title": "no url"}]}}

    ledger = Ledger(None)
    [hit] = LiveTools(ledger, Cache(None), transport).search("gyms Estonia")
    assert (hit.url, hit.content) == ("https://gym.example", "A gym Opens in Tartu")
    assert calls == [("https://ydc-index.io/v1/search", "you-test")]
    assert ledger.used("you") == 1 and ledger.used("tavily") == 0


def test_no_search_key_spends_nothing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("YOU_API_KEY", raising=False)
    ledger = Ledger(None)
    with pytest.raises(ToolUnavailable, match="TAVILY_API_KEY or YOU_API_KEY"):
        LiveTools(ledger, Cache(None), lambda *a: pytest.fail("no call expected")).search("x")
    assert ledger.snapshot() == Ledger(None).snapshot()


def test_read_uses_you_com_contents_without_jina_key(monkeypatch):
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.setenv("YOU_API_KEY", "you-test")

    def transport(method, url, headers, body):
        assert url == "https://ydc-index.io/v1/contents" and body["urls"] == ["https://gym.example"]
        return [{"url": "https://gym.example", "markdown": "# IronCore\nOur fifth location opens in Tartu."}]

    ledger = Ledger(None)
    tools = LiveTools(ledger, Cache(None), transport)
    assert "fifth location" in tools.read("https://gym.example")
    assert "fifth location" in tools.read("https://gym.example")  # second read is cached
    assert ledger.used("you") == 1 and ledger.used("jina") == 0


def test_read_reports_empty_you_com_page(monkeypatch):
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.setenv("YOU_API_KEY", "you-test")
    tools = LiveTools(Ledger(None), Cache(None), lambda *a: [{"url": "https://x.example", "markdown": ""}])
    with pytest.raises(ToolUnavailable, match="no page content"):
        tools.read("https://x.example")


def test_missing_hunter_key_spends_nothing(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    ledger = Ledger(None)
    with pytest.raises(ToolUnavailable):
        LiveTools(ledger, Cache(None), lambda *a: pytest.fail("no call expected")).find_contacts("x.example")
    assert ledger.used("hunter") == 0
