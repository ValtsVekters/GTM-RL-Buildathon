"""Minimal JSON-over-HTTP helper shared by the LLM router and the tools."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

TIMEOUT_SECONDS = 30

# (method, url, headers, json_body) -> parsed JSON, or text when the reply isn't JSON.
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], Any]


class ProviderError(Exception):
    """A provider call failed. status 0 means the network failed before any reply."""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def request_json(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"User-Agent": "gtm-engine-worker", "Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        raise ProviderError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(0, str(exc)) from exc
    try:
        return json.loads(raw)
    except ValueError:
        return raw
