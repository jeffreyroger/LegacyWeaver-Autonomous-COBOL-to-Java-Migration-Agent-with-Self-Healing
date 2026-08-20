"""Cross-program CALL-resolution prompt — Phase X7
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md).

`weaver/agent/prompt.py`'s `build_synthesis_prompt` is the hardened,
8-fixture path -- this module never modifies it. It wraps that same
function's output with an additive context block describing already-
migrated leaf subprogram classes on the candidate's classpath, so a
paragraph containing a real `CALL "<NAME>" USING <in> <out>` statement
(`ROOT.cob`'s `PROCESS-RECORD`) can be told what Java method that call
resolves to, instead of the model guessing at the subprogram's own logic.

`allowed_identifiers_with_calls` is the matching widened identifier set
for `weaver.agent.validate.static_reject` -- `weaver/agent/synthesize.py`'s
`ALLOWED_IDENTIFIERS = {"ar", "ws"}` constant is untouched; this is a
parallel, opt-in path used only for a program with real external calls.
"""

from __future__ import annotations

from weaver.agent.data_context import DataContext
from weaver.agent.prompt import build_synthesis_prompt
from weaver.agent.scaffold import ScaffoldSpec
from weaver.agent.segment import Paragraph

BASE_ALLOWED_IDENTIFIERS = {"ar", "ws"}


def allowed_identifiers_with_calls(external_calls: dict[str, tuple[str, str]]) -> set[str]:
    return BASE_ALLOWED_IDENTIFIERS | {class_name for class_name, _sig in external_calls.values()}


def build_call_aware_prompt(paragraph: Paragraph, context: DataContext, java_signature: str,
                             spec: ScaffoldSpec, external_calls: dict[str, tuple[str, str]]) -> str:
    """`external_calls` maps the literal COBOL program name a `CALL`
    statement names (e.g. "LEAF-A") to (Java class name, that class's
    callable static method's full signature) -- e.g.
    `{"LEAF-A": ("LeafA", "static java.math.BigDecimal mainPara(java.math.BigDecimal input)")}`.
    """
    base = build_synthesis_prompt(paragraph, context, java_signature, spec)
    if not spec.accumulator_field:
        # prompt.py's _prohibitions() (hardened, untouched here) hardcodes
        # "write to ws.{accumulator_field}" -- with no accumulator (a
        # totals-optional program, Phase X7) that renders as the
        # nonsensical, misleading "write to ws." Strip it rather than
        # leave a broken instruction that risks the model reading it as
        # "never write to any ws field."
        base = base.replace(
            "- write to ws. -- the generated main loop owns that\n"
            "  accumulation; this paragraph only sets",
            "- write to any working-storage field not listed above; this "
            "paragraph sets",
        )
    call_lines = "\n".join(
        f'- `CALL "{program_name}" USING <input> <output>` translates to Java: '
        f"`<output accessor> = {class_name}.<method>(<input accessor>);` "
        f"-- {class_name}'s available method: {sig}"
        for program_name, (class_name, sig) in external_calls.items()
    )
    return f"""{base}

ADDITIONAL CONTEXT -- already-migrated external subprogram classes on your
classpath. The prohibition above against referencing a field "not listed
in the field table" does NOT apply to these classes -- they are not
COBOL fields, they are already-migrated Java classes you are expected to
call. Do not attempt to reimplement any subprogram's own logic yourself;
call its already-migrated Java method instead, and assign the result to
the matching working-storage accessor -- an empty method body is WRONG,
since it would leave those working-storage fields unset:
{call_lines}

Worked example of this exact pattern (a different, fictitious paragraph
and subprogram -- shown only to illustrate the required translation; do
not reuse its field or class names):

COBOL:
    APPLY-SURCHARGE.
        CALL "RATE-CALC" USING WS-BASE WS-SURCHARGE.

If RateCalc.compute(java.math.BigDecimal base) is the already-migrated
method, the correct Java body is exactly:
    ws.surcharge = RateCalc.compute(ws.base);

Correct JSON response for that example:
{{"method_body": "ws.surcharge = RateCalc.compute(ws.base);", "assumptions": []}}

Your answer must follow this exact pattern: one assignment statement per
CALL statement in the paragraph below, in the same order, using the
accessors and classes given above. Do not return an empty method_body.
"""


__all__ = ["allowed_identifiers_with_calls", "build_call_aware_prompt"]
