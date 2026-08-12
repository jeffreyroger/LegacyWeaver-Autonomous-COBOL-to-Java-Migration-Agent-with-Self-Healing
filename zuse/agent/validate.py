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
    # setScale(int) alone defaults to UNNECESSARY/throws for a non-exact
    # value, so any setScale call must name its RoundingMode explicitly --
    # EXCEPT immediately after ZERO, where scale is unambiguous (there is
    # no direction to round zero in). Discovered via rigorous re-testing
    # 2026-08-07: the unqualified version rejected this project's own
    # hand-verified K3 reference body (`BigDecimal.ZERO.setScale(2)`).
    "ROUNDED-style .setScale without explicit DOWN": re.compile(
        r"(?<!ZERO)\.setScale\(\s*\d+\s*\)"
    ),
    # A single-argument .divide(x) throws ArithmeticException on any
    # non-terminating decimal (e.g. dividing by 365) -- it compiles clean
    # and crashes at runtime instead, which is worse than a compile error
    # because it silently produces zero output for the whole run (nothing
    # is written until the main loop finishes). Discovered via rigorous
    # re-testing 2026-08-07: a real, compiling, model-synthesized body hit
    # exactly this and every one of the 201 output lines came back empty.
    "single-argument .divide() (no scale/RoundingMode -- can throw ArithmeticException)": re.compile(
        r"\.divide\(\s*(?:new\s+java\.math\.BigDecimal\([^)]*\)|[A-Za-z_][A-Za-z0-9_.]*)\s*\)"
    ),
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


# Change 1 (real-world finding, 2026-08-07): the one real M4 unassisted-
# synthesis failure was purely mechanical -- the model wrote `BigDecimal`/
# `RoundingMode` instead of the fully-qualified `java.math.BigDecimal`/
# `java.math.RoundingMode` the scaffold requires (it declares no imports).
# That doesn't need a model call to fix; a deterministic rewrite does it
# with zero risk of changing behavior. Negative lookbehind avoids double-
# qualifying an already-correct `java.math.BigDecimal`.
_UNQUALIFIED_TYPE_RE = re.compile(r"(?<!java\.math\.)\b(BigDecimal|RoundingMode)\b")


def auto_qualify(body: str) -> tuple[str, list[str]]:
    """Rewrite bare BigDecimal/RoundingMode references to fully-qualified
    java.math.* form. Returns (possibly-rewritten body, list of type names
    that were rewritten -- empty if nothing changed).
    """
    changed: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        changed.append(m.group(1))
        return f"java.math.{m.group(1)}"

    return _UNQUALIFIED_TYPE_RE.sub(_sub, body), changed


def regeneration_hint(error: ValidationError) -> str:
    """Change 3: a precise, actionable instruction derived from the
    specific validation failure, instead of a generic "you were rejected"
    nudge. The vague version is what caused the observed repeated-hash
    escalation (N4) on 2026-08-07 -- two retries got the same non-specific
    feedback and produced near-identical wrong answers both times.
    """
    if error.reason == "malformed JSON":
        return "Return exactly one JSON object matching the output contract -- no prose, no markdown fence, nothing before or after the braces."
    if error.reason in ("missing required keys", "response is not a JSON object",
                          "method_body is not a string", "assumptions is not a list"):
        return 'Your JSON object must have exactly two keys: "method_body" (a string) and "assumptions" (a list of strings).'
    if error.reason == "forbidden construct":
        detail = error.detail
        # NOTE: order matters -- the .divide() detail string itself
        # contains the substring "RoundingMode" ("...no scale/RoundingMode
        # -- can throw..."), so the most specific checks must come first or
        # a divide defect silently gets the wrong hint. Discovered via
        # rigorous re-testing 2026-08-07: two live repair attempts got an
        # irrelevant HALF_UP-vs-DOWN hint for a missing-argument .divide()
        # defect and, unsurprisingly, made zero progress.
        if "divide" in detail:
            return ("A single-argument .divide(x) can throw ArithmeticException on a non-terminating "
                    "decimal. Always pass a scale and RoundingMode: .divide(x, 10, java.math.RoundingMode.DOWN), "
                    "or .divide(x, java.math.RoundingMode.DOWN) if the result's scale should match the dividend's.")
        if "float type" in detail or "double type" in detail:
            return "Replace float/double with java.math.BigDecimal -- binary floating point is forbidden."
        if "Math.round" in detail:
            return "Replace Math.round with an explicit .setScale(scale, java.math.RoundingMode.DOWN) call -- COBOL truncates by default."
        if "setScale" in detail:
            return "Every .setScale(...) call must explicitly name a RoundingMode, e.g. .setScale(2, java.math.RoundingMode.DOWN) -- never .setScale(n) alone."
        if "RoundingMode" in detail:
            return ("COBOL's default COMPUTE truncates toward zero, not round-half-up. Use "
                    "java.math.RoundingMode.DOWN everywhere, not HALF_UP/HALF_EVEN/HALF_DOWN/CEILING/UP, "
                    "unless the COBOL source explicitly says ROUNDED.")
        return f"Remove the forbidden construct: {detail}."
    if error.reason == "reference outside supplied context":
        return f"Remove the reference to {error.detail!r} -- only ar, ws, and the accessors already listed in the field table are available."
    return f"Fix this specific problem: {error}."


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
