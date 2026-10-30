"""LLM access: free providers tried in order, behind the cache and the quota ledger.

Every agent asks for one JSON object. "reason" is the big model, used once per
run for the ICP; "bulk" is the small, cheap model for extraction.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .cache import Cache
from .http import ProviderError, Transport, request_json
from .ledger import Ledger, QuotaExceeded


@dataclass(frozen=True)
class LLMRequest:
    role: str  # agent asking: icp | scout | reader
    tier: str  # reason | bulk
    system: str
    user: str
    fixture_key: str = ""


@dataclass(frozen=True)
class Route:
    quota: str
    base_url: str
    key_env: str
    model: str


class LLMUnavailable(Exception):
    """Every route for a tier failed, ran out of quota, or had no key."""


class LLM(Protocol):
    def complete_json(self, req: LLMRequest) -> tuple[dict, str]: ...


GROQ_URL = "https://api.groq.com/openai/v1"
PARASAIL_URL = "https://api.parasail.io/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENROUTER_URL = "https://openrouter.ai/api/v1"


def default_routes() -> dict[str, list[Route]]:
    parasail = os.getenv("PARASAIL_CHAT_MODEL", "parasail-qwen-3-next-80b-instruct")
    fallbacks = [
        Route("parasail", PARASAIL_URL, "PARASAIL_API_KEY", parasail),
        Route("gemini", GEMINI_URL, "GEMINI_API_KEY", os.getenv("GEMINI_MODEL", "gemini-2.5-flash")),
    ]
    if os.getenv("OPENROUTER_MODEL"):
        fallbacks.append(Route("openrouter", OPENROUTER_URL, "OPENROUTER_API_KEY", os.environ["OPENROUTER_MODEL"]))
    reason = os.getenv("GROQ_REASON_MODEL", "llama-3.3-70b-versatile")
    bulk = os.getenv("GROQ_BULK_MODEL", "llama-3.1-8b-instant")
    return {
        "reason": [Route("groq:reason", GROQ_URL, "GROQ_API_KEY", reason), *fallbacks],
        "bulk": [Route("groq:bulk", GROQ_URL, "GROQ_API_KEY", bulk), *fallbacks],
    }


def parse_json(text: str) -> dict:
    """Take the JSON object out of a reply, ignoring code fences or chatter around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("reply contained no JSON object")
    return json.loads(match.group(0))


class LLMRouter:
    def __init__(
        self,
        ledger: Ledger,
        cache: Cache,
        routes: dict[str, list[Route]] | None = None,
        transport: Transport = request_json,
        max_tokens: int = 1200,
    ):
        self.ledger = ledger
        self.cache = cache
        self.routes = routes or default_routes()
        self.transport = transport
        self.max_tokens = max_tokens

    def complete_json(self, req: LLMRequest) -> tuple[dict, str]:
        """Return (reply, where it came from). Cached replies spend no quota."""
        key = Cache.key("llm", [req.tier, req.system, req.user])
        cached = self.cache.get(key)
        if cached is not None:
            return cached, "cache"
        failures = []
        for route in self.routes[req.tier]:
            api_key = os.getenv(route.key_env, "").strip()
            if not api_key:
                failures.append(f"{route.quota}: {route.key_env} not set")
                continue
            try:
                self.ledger.reserve(route.quota)
            except QuotaExceeded as exc:
                failures.append(str(exc))
                continue
            body = {
                "model": route.model,
                "temperature": 0.2,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.user}],
            }
            try:
                reply = self.transport("POST", f"{route.base_url}/chat/completions",
                                       {"Authorization": f"Bearer {api_key}"}, body)
                result = parse_json(reply["choices"][0]["message"]["content"])
            except ProviderError as exc:
                failures.append(f"{route.quota}: {exc}")
                continue
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                failures.append(f"{route.quota}: unusable reply ({exc})")
                continue
            self.cache.set(key, result)
            return result, f"{route.quota} ({route.model})"
        raise LLMUnavailable("; ".join(failures))


class FixtureLLM:
    """Offline stand-in that returns saved replies, so the crew runs without keys."""

    def __init__(self, fixture_dir: Path):
        self.dir = fixture_dir

    def complete_json(self, req: LLMRequest) -> tuple[dict, str]:
        replies = json.loads((self.dir / f"llm_{req.role}.json").read_text(encoding="utf-8"))
        reply = replies.get(req.fixture_key) if req.fixture_key else replies
        if reply is None:
            raise LLMUnavailable(f"no fixture reply for {req.role} {req.fixture_key}")
        return reply, "fixture"
