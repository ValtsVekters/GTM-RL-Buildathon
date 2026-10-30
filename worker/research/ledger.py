"""Free-tier quota ledger: reserve each request before making it, refuse at the limit.

Windows reset per UTC day or per calendar month. Every attempt counts, failures
included, because some free tiers (OpenRouter) count failed requests too.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Quota:
    limit: int
    period: str  # day | month


# Kept a little under each free limit. Tavily and Hunter come from their official
# docs; the LLM numbers come from third-party summaries, so check each console.
DEFAULT_QUOTAS: dict[str, Quota] = {
    "groq:reason": Quota(900, "day"),
    "groq:bulk": Quota(10000, "day"),
    "gemini": Quota(200, "day"),
    "openrouter": Quota(45, "day"),
    "parasail": Quota(2000, "day"),  # paid credits: a spending guard, not a free limit
    "tavily": Quota(1000, "month"),
    "you": Quota(500, "day"),  # paid credits: a spending guard, not a free limit
    "jina": Quota(500, "day"),
    "hunter": Quota(50, "month"),
}


class QuotaExceeded(Exception):
    """The free allowance for this provider is used up for the current window."""


class Ledger:
    def __init__(
        self,
        path: Path | None,
        quotas: dict[str, Quota] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        """path=None keeps counts in memory only (fixture runs and tests)."""
        self.path = path
        self.quotas = dict(quotas or DEFAULT_QUOTAS)
        self._now = now or (lambda: datetime.now(UTC))
        self._counts: dict[str, int] = self._load()

    def _window(self, name: str) -> str:
        stamp = self._now()
        if self.quotas[name].period == "day":
            return f"{name}@{stamp:%Y-%m-%d}"
        return f"{name}@{stamp:%Y-%m}"

    def _load(self) -> dict[str, int]:
        if self.path and self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._counts, indent=1), encoding="utf-8")

    def used(self, name: str) -> int:
        return self._counts.get(self._window(name), 0)

    def remaining(self, name: str) -> int:
        return max(self.quotas[name].limit - self.used(name), 0)

    def reserve(self, name: str, amount: int = 1) -> None:
        quota = self.quotas[name]
        if self.used(name) + amount > quota.limit:
            raise QuotaExceeded(f"{name}: free quota used up ({quota.limit} per {quota.period})")
        window = self._window(name)
        self._counts[window] = self._counts.get(window, 0) + amount
        self._save()

    def snapshot(self) -> dict[str, int]:
        return {name: self.remaining(name) for name in self.quotas}
