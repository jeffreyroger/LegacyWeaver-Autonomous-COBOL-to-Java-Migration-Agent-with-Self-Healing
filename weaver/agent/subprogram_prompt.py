"""Subprogram synthesis prompt design — Phase X4
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md).

A small, parallel prompt builder for the narrow subprogram shape Phase X1
parses. `weaver/agent/prompt.py`'s `build_synthesis_prompt` is deeply tied
to a file-based `ScaffoldSpec` (report/totals fields, `ar`/`ws` accessors)
and is not reusable here -- this module is the subprogram-shaped
counterpart, following the same output contract (`SYNTHESIS_SCHEMA`:
`{"method_body": ..., "assumptions": [...]}`, `weaver/agent/prompt.py`)
so `weaver.agent.validate.parse_response`/`auto_qualify`/`static_reject`
are reused unchanged.
"""

from __future__ import annotations

from weaver.cobol.naming import java_field_name, java_method_name
from weaver.cobol.subprogram import SubprogramModel


def java_signature(model: SubprogramModel) -> str:
    input_name = java_field_name(model.input_param.name)
    method_name = java_method_name(model.paragraph_id)
    return f"static java.math.BigDecimal {method_name}(java.math.BigDecimal {input_name})"


def allowed_identifiers(model: SubprogramModel) -> set[str]:
    return {java_field_name(model.input_param.name)}


def _overflow_truncation_rule(model: SubprogramModel, next_rule_number: int) -> str:
    """COBOL's PIC clause is a fixed-width store, not an arbitrary-precision
    one: a COMPUTE with no ON SIZE ERROR clause silently drops high-order
    digits when the true result doesn't fit, rather than raising or
    saturating (equivalent to reducing the scaled integer value modulo
    10^total_digits). java.math.BigDecimal never does this on its own --
    a naive `a.multiply(b)` is exact, unbounded precision, and diverges
    from the real oracle on any witness large enough to overflow. Only
    emitted when the paragraph itself has no ON SIZE ERROR clause (a
    paragraph that does have one needs different, not-yet-modeled
    handling -- out of scope here, not claimed)."""
    if "ON SIZE ERROR" in model.paragraph_source.upper():
        return ""
    out = model.output_params[0]
    total_digits = out.width
    scale = out.decimal_scale
    return f"""
{next_rule_number}. This paragraph has no ON SIZE ERROR clause, so COBOL's real
   fixed-point overflow behavior applies: the output field holds at most
   {total_digits} total digits ({total_digits - scale} integer, {scale} fraction).
   COBOL does NOT raise an error or saturate on overflow -- it silently
   discards high-order digits, keeping only the low-order {total_digits}
   digits of the scaled result. You MUST apply this truncation to your
   final result before returning it, unconditionally, using exactly this
   pattern (adjust the computation on the first line to this paragraph's
   actual logic, keep the truncation lines as-is):

   java.math.BigDecimal result = /* your computed value, unscaled/untruncated */;
   java.math.BigInteger scaledValue = result.movePointRight({scale}).toBigIntegerExact();
   java.math.BigInteger modulus = java.math.BigInteger.TEN.pow({total_digits});
   java.math.BigInteger truncated = scaledValue.remainder(modulus);
   return new java.math.BigDecimal(truncated).movePointLeft({scale});

   Every witness, including ones whose mathematical result plainly exceeds
   {total_digits - scale} integer digits, must go through this exact
   truncation -- the real compiled oracle truncates them too, so an answer
   that looks "obviously correct" without it (e.g. plain a.multiply(b))
   will diverge on large witnesses."""


def build_subprogram_prompt(model: SubprogramModel) -> str:
    input_name = java_field_name(model.input_param.name)
    signature = java_signature(model)
    overflow_rule = _overflow_truncation_rule(model, next_rule_number=6)

    return f"""\
You are translating one COBOL subprogram paragraph into a Java method body.

RULES (absolute, follow exactly):
1. Use only exact decimal arithmetic (java.math.BigDecimal). Never float
   or double, anywhere.
2. COBOL COMPUTE truncates toward zero by default -- there is no ROUNDED
   clause in this paragraph, so do not round; use exact BigDecimal
   arithmetic that matches truncation, not banker's/half-up rounding.
3. The only variable available to you is `{input_name}` (a
   java.math.BigDecimal, already holding the paragraph's linkage-section
   input value). Do not reference any other field, class, or static
   member beyond `{input_name}` and java.math.* types.
4. Your method must `return` a java.math.BigDecimal -- the paragraph's
   COBOL linkage-section output value.
5. Do not include the method signature, braces, or any surrounding
   class/method declaration -- only the statements that go inside the
   method body.{overflow_rule}

METHOD SIGNATURE (for context only -- do not repeat it in your answer):
{signature}

COBOL SOURCE (the paragraph to translate):
{model.paragraph_source}

OUTPUT CONTRACT:
Respond with a JSON object exactly of the shape:
{{"method_body": "<the Java statements>", "assumptions": ["<any assumption you made>"]}}
"""


__all__ = ["allowed_identifiers", "build_subprogram_prompt", "java_signature"]
