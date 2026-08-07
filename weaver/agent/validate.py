"""Constrain and validate synthesized output — Step M2.

Never let malformed model output reach the compiler. Two layers:
1. JSON-schema conformance (the grammar constraint on the request already
   does most of this -- Ollama's `format` field -- this is the receipt
   check).
2. A static rejection pass over the returned body: forbidden types/calls,
   and references to identifiers outside the supplied context.

On failure, callers regenerate (up to twice) rather than trying to repair
malformed text -- regenerating is cheaper and more reliable than patching
syntax (plan's explicit instruction).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FORBIDDEN_PATTERNS = {
    "float type": re.compile(r"\bfloat\b"),
    "double type": re.compile(r"\bdouble\b"),
    "Math.round": re.compile(r"Math\.round\b"),
    "RoundingMode.HALF_UP/HALF_EVEN/HALF_DOWN/CEILING/UP": re.compile(
        r"RoundingMode\.(HALF_UP|HALF_EVEN|HALF_DOWN|CEILING|UP)\b"
    ),
    "ROUNDED-style .setScale without explicit DOWN": re.compile(
        r"\.setScale\(\s*\d+\s*\)"  # setScale(int) alone defaults to UNNECESSARY/throws, but
    ),                                # any setScale call must name its RoundingMode explicitly.
}


class ValidationError(ValueError):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class SynthesizedBody:
    method_body: str
    assumptions: list[str]


def parse_response(raw_text: str) -> SynthesizedBody:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValidationError("malformed JSON", str(e)) from e

    if not isinstance(data, dict):
        raise ValidationError("response is not a JSON object")
    missing = {"method_body", "assumptions"} - data.keys()
    if missing:
        raise ValidationError("missing required keys", str(sorted(missing)))
    if not isinstance(data["method_body"], str):
        raise ValidationError("method_body is not a string")
    if not isinstance(data["assumptions"], list):
        raise ValidationError("assumptions is not a list")

    return SynthesizedBody(method_body=data["method_body"], assumptions=list(data["assumptions"]))


def static_reject(body: SynthesizedBody, allowed_identifiers: set[str]) -> None:
    """Raise ValidationError if the body violates a hard prohibition."""
    for reason, pattern in _FORBIDDEN_PATTERNS.items():
        if pattern.search(body.method_body):
            raise ValidationError("forbidden construct", reason)

    referenced = set(re.findall(r"\b[a-z][a-zA-Z0-9]*\.[a-zA-Z][a-zA-Z0-9]*\b", body.method_body))
    java_keywords_prefixes = {"java.", "System.", "BigDecimal.", "RoundingMode."}
    for ref in referenced:
        if any(ref.startswith(p) for p in java_keywords_prefixes):
            continue
        base = ref.split(".", 1)[0]
        if base not in allowed_identifiers:
            raise ValidationError("reference outside supplied context", ref)
