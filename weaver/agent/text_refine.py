"""Text Processing Agent — migration-framework-spec.md §1, FR-10.1-10.3.

Hosted, opt-in refinement of an already-synthesized method body. Never a
synthesis path of its own -- deterministic scaffold + local synthesis stay
the default and only required path (CLAUDE.md rule 10). This module is
called at most once per unit, after synthesis and before compile, and its
output is re-verified through the exact same attribution path any other
body goes through -- it never gets to claim correctness on its own say-so.
"""

from __future__ import annotations

import requests

OPENAI_HOST = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

_REFINE_SYSTEM_PROMPT = (
    "You refine a single Java method body for style and clarity only. "
    "Do not change arithmetic, comparisons, control flow, or field names. "
    "Return only the method body text, no explanation, no markdown fences."
)


class TextRefinementError(RuntimeError):
    pass


def refine(body: str, *, model: str = DEFAULT_MODEL, api_key: str | None) -> str:
    if not api_key:
        raise TextRefinementError(
            "OPENAI_API_KEY is required when use_text_refinement=True"
        )
    response = requests.post(
        f"{OPENAI_HOST}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _REFINE_SYSTEM_PROMPT},
                {"role": "user", "content": body},
            ],
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise TextRefinementError(f"refinement request failed: {response.status_code} {response.text}")
    return response.json()["choices"][0]["message"]["content"]
