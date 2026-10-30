"""Response cache, so repeating a request never spends free-tier quota twice."""

import hashlib
import json
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, root: Path | None):
        """root=None keeps the cache in memory only (fixture runs and tests)."""
        self.root = root
        self._memory: dict[str, Any] = {}
        if root:
            root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(namespace: str, payload: Any) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return f"{namespace}-{hashlib.sha256(blob.encode()).hexdigest()[:32]}"

    def get(self, key: str) -> Any | None:
        if key in self._memory:
            return self._memory[key]
        if self.root:
            path = self.root / f"{key}.json"
            if path.exists():
                value = json.loads(path.read_text(encoding="utf-8"))
                self._memory[key] = value
                return value
        return None

    def set(self, key: str, value: Any) -> None:
        self._memory[key] = value
        if self.root:
            (self.root / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
