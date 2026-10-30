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


def test_missing_hunter_key_spends_nothing(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    ledger = Ledger(None)
    with pytest.raises(ToolUnavailable):
        LiveTools(ledger, Cache(None), lambda *a: pytest.fail("no call expected")).find_contacts("x.example")
    assert ledger.used("hunter") == 0
