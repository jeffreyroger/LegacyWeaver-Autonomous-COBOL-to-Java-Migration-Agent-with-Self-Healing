"""Prompt-hash cache — Step J4.

Every model interaction is cached by a hash of the full request payload
(model, seed, every parameter, complete prompt). Any change to any of
those must miss the cache. Doubles as the demo replay mechanism: replay
mode serves only from cache and raises loudly on a miss rather than
silently falling through to inference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any


class ReplayMissError(RuntimeError):
    """Raised in replay mode when a request has no cached response."""


def request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class PromptCache:
    cache_dir: Path
    replay_only: bool = False

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        key = request_hash(payload)
        path = self._path(key)
        if not path.exists():
            if self.replay_only:
                raise ReplayMissError(
                    f"replay mode: no cached response for request hash {key} "
                    f"(payload keys: {sorted(payload.keys())})"
                )
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, payload: dict[str, Any], response: dict[str, Any]) -> str:
        key = request_hash(payload)
        self._path(key).write_text(json.dumps(response, indent=2, sort_keys=True), encoding="utf-8")
        return key

    def call_count(self) -> int:
        return sum(1 for _ in self.cache_dir.glob("*.json"))
