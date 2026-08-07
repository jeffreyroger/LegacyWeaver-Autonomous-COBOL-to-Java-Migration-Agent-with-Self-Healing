"""Local inference client — Steps J1/J2/J4.

Talks to the local Ollama daemon on loopback only. All determinism-relevant
parameters (model, seed, temperature, top_p, context window, prediction
cap) are pinned and sent on every request — some runtimes ignore a seed set
only at session level, so it is set per-call here (J2 common failure).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from weaver.agent.cache import PromptCache

OLLAMA_HOST = "http://127.0.0.1:11434"  # loopback only -- J1 offline requirement
DEFAULT_MODEL = "qwen2.5-coder:7b"
FALLBACK_MODEL = "qwen2.5-coder:3b"
SEED = 42
TEMPERATURE = 0.0
TOP_P = 1.0
NUM_CTX = 4096
NUM_PREDICT = 768


class OfflineViolationError(RuntimeError):
    pass


def _assert_loopback(host: str) -> None:
    if "127.0.0.1" not in host and "localhost" not in host:
        raise OfflineViolationError(f"refusing to call non-loopback host: {host}")


@dataclass
class InferenceRequest:
    prompt: str
    model: str = DEFAULT_MODEL
    schema: dict[str, Any] | None = None  # JSON schema for grammar-constrained output (M2)

    def payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {
            "model": self.model,
            "prompt": self.prompt,
            "stream": False,
            "options": {
                "seed": SEED,
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
                "num_ctx": NUM_CTX,
                "num_predict": NUM_PREDICT,
            },
        }
        if self.schema is not None:
            p["format"] = self.schema
        return p


@dataclass
class InferenceResponse:
    text: str
    eval_count: int
    eval_duration_ns: int
    from_cache: bool

    @property
    def tokens_per_second(self) -> float:
        if self.eval_duration_ns == 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1e9)


class InferenceClient:
    """Cache-first client: identical requests never hit the model twice."""

    def __init__(self, cache_dir: Path, host: str = OLLAMA_HOST, replay_only: bool = False):
        _assert_loopback(host)
        self.host = host
        self.cache = PromptCache(cache_dir, replay_only=replay_only)

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        payload = request.payload()
        cached = self.cache.get(payload)
        if cached is not None:
            return InferenceResponse(
                text=cached["response"],
                eval_count=cached.get("eval_count", 0),
                eval_duration_ns=cached.get("eval_duration", 0),
                from_cache=True,
            )

        resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        self.cache.put(payload, data)
        return InferenceResponse(
            text=data["response"],
            eval_count=data.get("eval_count", 0),
            eval_duration_ns=data.get("eval_duration", 0),
            from_cache=False,
        )


if __name__ == "__main__":
    import sys

    client = InferenceClient(cache_dir=Path("generated/model_cache"))
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Reply with exactly the word: pong"
    r = client.generate(InferenceRequest(prompt=prompt))
    print(json.dumps({"text": r.text, "tokens_per_second": r.tokens_per_second, "from_cache": r.from_cache}, indent=2))
