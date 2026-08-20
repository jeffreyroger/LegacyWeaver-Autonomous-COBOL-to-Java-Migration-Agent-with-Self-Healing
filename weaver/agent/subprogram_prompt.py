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


def build_subprogram_prompt(model: SubprogramModel) -> str:
    input_name = java_field_name(model.input_param.name)
    signature = java_signature(model)

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
   method body.

METHOD SIGNATURE (for context only -- do not repeat it in your answer):
{signature}

COBOL SOURCE (the paragraph to translate):
{model.paragraph_source}

OUTPUT CONTRACT:
Respond with a JSON object exactly of the shape:
{{"method_body": "<the Java statements>", "assumptions": ["<any assumption you made>"]}}
"""


__all__ = ["allowed_identifiers", "build_subprogram_prompt", "java_signature"]
