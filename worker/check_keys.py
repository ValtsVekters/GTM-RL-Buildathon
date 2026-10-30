"""Check every research provider key in ../.env with a call that spends no quota.

Each check lists models, reads account usage, or sends an empty request that the
provider rejects only after accepting the key. The one exception is Jina without
a key: it reads example.com once to prove keyless access works.

The crew is ready when it has at least one working LLM, search and page reader.

Usage (from worker/): uv run python check_keys.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TIMEOUT_SECONDS = 15
REQUIRED = {"llm": "LLM", "search": "web search", "reader": "page reader"}


@dataclass(frozen=True)
class Provider:
    env: str
    name: str
    groups: tuple[str, ...]  # llm | search | reader | contacts
    url: str
    auth: Callable[[str], dict[str, str]]
    summarize: Callable[[object], str]
    method: str = "GET"
    body: dict | None = None
    accepted: tuple[int, ...] = ()  # error statuses that still prove the key was accepted
    keyless_ok: bool = False


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _tavily_summary(data) -> str:
    acct = data["account"]
    return f"{acct.get('plan_usage')}/{acct.get('plan_limit')} credits used ({acct.get('current_plan')})"


def _hunter_summary(data) -> str:
    info = data["data"]
    return f"{info.get('plan_name')} plan, requests {json.dumps(info.get('requests'))}"


def _parasail_summary(data) -> str:
    ids = [m.get("id", "") for m in data["data"]]
    model = os.getenv("PARASAIL_CHAT_MODEL", "parasail-qwen-3-next-80b-instruct")
    return f"{len(ids)} models, {model} {'listed' if model in ids else 'NOT listed'}"


PROVIDERS = [
    Provider("GROQ_API_KEY", "Groq", ("llm",), "https://api.groq.com/openai/v1/models", _bearer,
             lambda d: f"{len(d['data'])} models available"),
    Provider("PARASAIL_API_KEY", "Parasail", ("llm",), "https://api.parasail.io/v1/models", _bearer,
             _parasail_summary),
    Provider("GEMINI_API_KEY", "Gemini", ("llm",), "https://generativelanguage.googleapis.com/v1beta/models",
             lambda k: {"x-goog-api-key": k},
             lambda d: f"{sum('flash' in m['name'] for m in d['models'])} Flash models available"),
    Provider("OPENROUTER_API_KEY", "OpenRouter", ("llm",), "https://openrouter.ai/api/v1/key", _bearer,
             lambda d: f"free tier: {d['data'].get('is_free_tier')}, usage: {d['data'].get('usage')}"),
    Provider("TAVILY_API_KEY", "Tavily", ("search",), "https://api.tavily.com/usage", _bearer, _tavily_summary),
    # An empty search is refused with 422 once the key is accepted (403 for a bad key), so no search is run.
    Provider("YOU_API_KEY", "You.com", ("search", "reader"), "https://ydc-index.io/v1/search",
             lambda k: {"X-API-Key": k}, lambda d: "key accepted", method="POST", body={}, accepted=(422,)),
    Provider("JINA_API_KEY", "Jina Reader", ("reader",), "https://r.jina.ai/https://example.com", _bearer,
             lambda d: "reader works", keyless_ok=True),
    Provider("HUNTER_API_KEY", "Hunter", ("contacts",), "https://api.hunter.io/v2/account",
             lambda k: {"X-API-KEY": k}, _hunter_summary),
]


def _request(provider: Provider, headers: dict[str, str]) -> object:
    data = json.dumps(provider.body).encode() if provider.body is not None else None
    req = urllib.request.Request(provider.url, data=data, method=provider.method, headers={
        "User-Agent": "gtm-engine-keycheck", "Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        body = resp.read()
    try:
        return json.loads(body)
    except ValueError:
        return body.decode(errors="replace")


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode(errors="replace")
    except OSError:
        return ""
    try:
        data = json.loads(body)
    except ValueError:
        return body[:160]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return f"{err.get('message', '')} {json.dumps(err.get('details', ''))}"
    return str(data.get("message") or body[:160]) if isinstance(data, dict) else body[:160]


def check(provider: Provider) -> tuple[bool, str]:
    key = os.getenv(provider.env, "").strip()
    if not key and not provider.keyless_ok:
        return False, f"MISSING  set {provider.env} in .env"
    try:
        data = _request(provider, provider.auth(key) if key else {})
    except urllib.error.HTTPError as exc:
        if exc.code in provider.accepted:
            return True, "OK       key accepted"
        reason = _error_message(exc)
        # Gemini answers a bad key with 400 API_KEY_INVALID instead of 401.
        if exc.code in (401, 403) or "API_KEY_INVALID" in reason:
            if not key:
                return False, f"BLOCKED  keyless access refused, set {provider.env}: {reason[:160]}"
            return False, f"REJECTED HTTP {exc.code}: key is wrong, expired or revoked"
        if exc.code == 429:
            return True, "RATE-LIMITED (key accepted, quota busy)"
        return False, f"ERROR    HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, f"ERROR    network: {exc}"
    try:
        detail = provider.summarize(data)
    except (KeyError, TypeError, AttributeError):
        detail = "response shape changed; key accepted"
    return True, f"OK       {detail}" + ("" if key else " (keyless)")


def main() -> int:
    load_dotenv(ENV_FILE)
    working: set[str] = set()
    for provider in PROVIDERS:
        ok, message = check(provider)
        print(f"{provider.name:<12} [{'/'.join(provider.groups)}] {message}")
        if ok:
            working.update(provider.groups)
    missing = [label for group, label in REQUIRED.items() if group not in working]
    if "contacts" not in working:
        print("\nNote: no Hunter key, so tier-A leads get no email lookup.")
    if missing:
        print(f"Not ready: no working {', '.join(missing)}")
        return 1
    print("\nReady: the crew has a working LLM, search and page reader.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
