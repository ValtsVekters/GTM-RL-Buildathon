import pytest

from research.cache import Cache
from research.http import ProviderError
from research.ledger import Ledger
from research.llm import LLMRequest, LLMRouter, LLMUnavailable, Route, parse_json

ROUTES = {
    "bulk": [
        Route("groq:bulk", "https://groq.test", "GROQ_API_KEY", "small"),
        Route("gemini", "https://gemini.test", "GEMINI_API_KEY", "flash"),
    ]
}
REQ = LLMRequest("scout", "bulk", "system", "user")


def reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GEMINI_API_KEY", "gem_test")


def test_falls_back_to_next_provider_on_rate_limit(keys):
    calls = []

    def transport(method, url, headers, body):
        calls.append(url)
        if url.startswith("https://groq.test"):
            raise ProviderError(429, "rate limited")
        return reply('{"ok": true}')

    ledger = Ledger(None)
    result, source = LLMRouter(ledger, Cache(None), ROUTES, transport).complete_json(REQ)
    assert result == {"ok": True}
    assert source == "gemini (flash)"
    assert len(calls) == 2
    assert ledger.used("groq:bulk") == 1 and ledger.used("gemini") == 1


def test_cached_reply_spends_no_quota(keys):
    calls = []

    def transport(method, url, headers, body):
        calls.append(url)
        return reply('{"ok": 1}')

    ledger = Ledger(None)
    router = LLMRouter(ledger, Cache(None), ROUTES, transport)
    router.complete_json(REQ)
    result, source = router.complete_json(REQ)
    assert (result, source) == ({"ok": 1}, "cache")
    assert len(calls) == 1 and ledger.used("groq:bulk") == 1


def test_no_keys_raises_without_spending_quota(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ledger = Ledger(None)
    with pytest.raises(LLMUnavailable, match="GROQ_API_KEY not set"):
        LLMRouter(ledger, Cache(None), ROUTES, lambda *a: pytest.fail("no call expected")).complete_json(REQ)
    assert ledger.used("groq:bulk") == 0


def test_parse_json_ignores_code_fences():
    assert parse_json('Sure!\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("no json here")
