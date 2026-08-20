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
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from weaver.agent.cache import PromptCache

OLLAMA_HOST = "http://127.0.0.1:11434"  # loopback only -- J1 offline requirement
GROQ_HOST = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "granite-code:20b"  # matches runspec.py's DEFAULT_MODEL -- keep in sync, see that module's comment
FALLBACK_MODEL = "qwen2.5-coder:3b"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-20b"  # only models with Structured Outputs support (console.groq.com/docs/structured-outputs)
SEED = 42
TEMPERATURE = 0.0
TOP_P = 1.0
NUM_CTX = 4096
NUM_PREDICT = 768
# gpt-oss-20b is a reasoning model on Groq: hidden chain-of-thought tokens
# count against max_tokens before the visible JSON answer does. NUM_PREDICT
# is tuned for the local, non-reasoning Ollama model and is too small here --
# reusing it left no room for the answer, so Groq returned an empty
# completion and structured-output validation failed. Kept separate so this
# doesn't perturb the Ollama-path cache key or its determinism pin (J2).
GROQ_MAX_TOKENS = 4096
# Groq's free tier caps tokens-per-minute org-wide; a repair-loop unit can
# make several synthesis calls in quick succession and exceed it well
# within a single migrate run (found 2026-08-12: shipcost.cob's repair
# loop hit 429 on its second call). Groq's own 429 body names the exact
# cooldown ("Please try again in 19.4s") -- wait that out and retry rather
# than aborting the whole run.
GROQ_MAX_RETRIES = 3
_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)s")


def _groq_retry_delay(resp: "requests.Response") -> float:
    header = resp.headers.get("Retry-After")
    if header is not None:
        try:
            return float(header)
        except ValueError:
            pass
    match = _RETRY_AFTER_RE.search(resp.text)
    if match:
        return float(match.group(1))
    return 5.0


class OfflineViolationError(RuntimeError):
    pass


class InferenceError(RuntimeError):
    """A provider request failed to produce usable output (rate limit
    exhausted, malformed/unparseable completion, transport error, ...).

    Distinct from OfflineViolationError (a programming-error guard) so
    callers can treat it the same way they already treat a parsed-but-
    invalid response: log it, regenerate, and eventually escalate that one
    unit -- never let a single flaky request crash the whole migrate run.
    """


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
            "max_tokens": GROQ_MAX_TOKENS,
            "reasoning_effort": "low",
        }
        if request.schema is not None:
            schema = dict(request.schema)
            schema.setdefault("additionalProperties", False)
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "synthesis_response",
                    "schema": schema,
                    "strict": True,
                },
            }
        resp = None
        for attempt in range(GROQ_MAX_RETRIES + 1):
            resp = requests.post(
                f"{self.host}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=180,
            )
            if resp.status_code != 429 or attempt == GROQ_MAX_RETRIES:
                break
            time.sleep(_groq_retry_delay(resp) + 0.5)
        if not resp.ok:
            raise InferenceError(f"Groq request failed ({resp.status_code}): {resp.text}")
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
