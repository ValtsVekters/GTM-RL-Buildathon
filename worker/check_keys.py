"""Check every free research provider key in ../.env with a read-only call.

Each check lists models or reads account usage, so no search, generation or
email lookup is made and no free-tier quota is spent. The one exception is
Jina without a key: it reads example.com once to prove keyless access works.

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


@dataclass(frozen=True)
class Provider:
    env: str
    name: str
    url: str
    auth: Callable[[str], dict[str, str]]
    summarize: Callable[[object], str]
    required: bool = True
    keyless_ok: bool = False


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _tavily_summary(data) -> str:
    acct = data["account"]
    return f"{acct.get('plan_usage')}/{acct.get('plan_limit')} credits used ({acct.get('current_plan')})"


def _hunter_summary(data) -> str:
    info = data["data"]
    return f"{info.get('plan_name')} plan, requests {json.dumps(info.get('requests'))}"


PROVIDERS = [
    Provider("GROQ_API_KEY", "Groq", "https://api.groq.com/openai/v1/models", _bearer,
             lambda d: f"{len(d['data'])} models available"),
    Provider("GEMINI_API_KEY", "Gemini", "https://generativelanguage.googleapis.com/v1beta/models",
             lambda k: {"x-goog-api-key": k},
             lambda d: f"{sum('flash' in m['name'] for m in d['models'])} Flash models available",
             required=False),
    Provider("OPENROUTER_API_KEY", "OpenRouter", "https://openrouter.ai/api/v1/key", _bearer,
             lambda d: f"free tier: {d['data'].get('is_free_tier')}, usage: {d['data'].get('usage')}",
             required=False),
    Provider("TAVILY_API_KEY", "Tavily", "https://api.tavily.com/usage", _bearer, _tavily_summary),
    Provider("JINA_API_KEY", "Jina Reader", "https://r.jina.ai/https://example.com", _bearer,
             lambda d: "reader works", required=False, keyless_ok=True),
    Provider("HUNTER_API_KEY", "Hunter", "https://api.hunter.io/v2/account",
             lambda k: {"X-API-KEY": k}, _hunter_summary),
]


def _get(url: str, headers: dict[str, str]) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "gtm-engine-keycheck", **headers})
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
        data = _get(provider.url, provider.auth(key) if key else {})
    except urllib.error.HTTPError as exc:
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
    failed_required = []
    for provider in PROVIDERS:
        ok, message = check(provider)
        tag = "required" if provider.required else "optional"
        print(f"{provider.name:<12} [{tag}] {message}")
        if provider.required and not ok:
            failed_required.append(provider.name)
    if failed_required:
        print(f"\nNot ready: {', '.join(failed_required)}")
        return 1
    print("\nAll required providers ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
