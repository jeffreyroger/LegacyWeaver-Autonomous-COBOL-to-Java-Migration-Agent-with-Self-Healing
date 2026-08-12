"""Local inference client — Steps J1/J2/J4.

Talks to the local Ollama daemon on loopback only. All determinism-relevant
parameters (model, seed, temperature, top_p, context window, prediction
cap) are pinned and sent on every request — some runtimes ignore a seed set
only at session level, so it is set per-call here (J2 common failure).

CI exception (CLAUDE.md rule 10): GitHub-hosted runners have no local model
runtime, so the `weaver` GitHub Action opts into `provider="groq"` via the
WEAVER_INFERENCE_PROVIDER env var. This is the only caller permitted to do
so -- local/CLI/backend/frontend runs default to "ollama" and stay offline.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from weaver.agent.cache import PromptCache

OLLAMA_HOST = "http://127.0.0.1:11434"  # loopback only -- J1 offline requirement
GROQ_HOST = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "qwen2.5-coder:7b"
FALLBACK_MODEL = "qwen2.5-coder:3b"
GROQ_DEFAULT_MODEL = "qwen/qwen3.6-27b"  # per console.groq.com/docs/models -- confirmed 2026-08-12
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
    seed: int = SEED

    def payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {
            "model": self.model,
            "prompt": self.prompt,
            "stream": False,
            "options": {
                "seed": self.seed,
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
    """Cache-first client: identical requests never hit the model twice.

    `provider="ollama"` (default) is the only path used locally/CLI/backend/
    frontend and keeps the loopback-only offline guarantee. `provider="groq"`
    exists solely for the CI workflow (see module docstring) and is never
    selected unless the caller explicitly opts in.
    """

    def __init__(self, cache_dir: Path, host: str = OLLAMA_HOST, replay_only: bool = False,
                 provider: str = "ollama"):
        if provider not in ("ollama", "groq"):
            raise ValueError(f"unknown inference provider: {provider}")
        self.provider = provider
        if provider == "ollama":
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

        if self.provider == "groq":
            data = self._generate_groq(request)
        else:
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

    def _generate_groq(self, request: InferenceRequest) -> dict[str, Any]:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise OfflineViolationError(
                "provider=groq requires GROQ_API_KEY in the environment (CI-only path)"
            )
        body: dict[str, Any] = {
            "model": request.model if request.model != DEFAULT_MODEL else GROQ_DEFAULT_MODEL,
            "messages": [{"role": "user", "content": request.prompt}],
            "seed": request.seed,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "max_tokens": NUM_PREDICT,
        }
        if request.schema is not None:
            schema = dict(request.schema)
            schema.setdefault("additionalProperties", False)
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "synthesis_response",
                    "schema": schema,
                },
            }
        resp = requests.post(
            f"{self.host}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=180,
        )
        if not resp.ok:
            raise RuntimeError(f"Groq request failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return {
            "response": choice["message"]["content"],
            "eval_count": usage.get("completion_tokens", 0),
            "eval_duration": int(usage.get("completion_time", 0) * 1e9),
        }


if __name__ == "__main__":
    import sys

    client = InferenceClient(cache_dir=Path("generated/model_cache"))
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Reply with exactly the word: pong"
    r = client.generate(InferenceRequest(prompt=prompt))
    print(json.dumps({"text": r.text, "tokens_per_second": r.tokens_per_second, "from_cache": r.from_cache}, indent=2))
