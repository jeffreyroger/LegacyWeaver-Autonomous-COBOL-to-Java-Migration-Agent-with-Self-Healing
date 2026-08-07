"""Synthesis prompt design — Step M1.

Ordering matters (constraints stated after the task get weaker adherence):
role, then semantic rules as absolutes, then field table, then condition
names, then the method signature, then prohibitions, then the paragraph
source, then the output contract. Every semantic rule here exists because
it is the rule a planted trap in fixtures/cobol/interest.cob depends on
(T1 truncation, T2 implied decimal, T3 REDEFINES, T4 88-level tiering) --
Dev A's review step (M1 acceptance test) is to confirm that mapping stays
true whenever this prompt changes.
"""

from __future__ import annotations

from weaver.agent.data_context import DataContext, WORKING_STORAGE_FIELDS
from weaver.agent.scaffold import ConditionName
from weaver.agent.segment import Paragraph
from weaver.layout import INPUT_LAYOUT, Field

# Java accessor for each known identifier, keyed by COBOL name. Working-
# storage targets the paragraph is allowed to mutate are listed separately
# from the ones the scaffold itself owns (WS-TOTAL-INTEREST: accumulated by
# the generated main loop, never by the paragraph -- see scaffold_spec.md
# §6). Exposing that boundary in the prompt is what keeps "no modification
# of the scaffold" enforceable rather than aspirational.
_WS_ACCESSORS = {
    "WS-APPLIED-RATE": "ws.appliedRate",
    "WS-INTEREST": "ws.interest",
}
_WS_SCAFFOLD_OWNED = {"WS-TOTAL-INTEREST", "WS-EOF-FLAG"}

_INPUT_ACCESSORS = {f.name: f for f in INPUT_LAYOUT}


def _accessor(name: str) -> str:
    if name in _WS_ACCESSORS:
        return _WS_ACCESSORS[name]
    field = _INPUT_ACCESSORS.get(name)
    if field is not None:
        if field.redefines is not None:
            java_name = "".join(
                w.capitalize() if i else w.lower()
                for i, w in enumerate(name.split("-")[1:])
            )
            return f"ar.{java_name}()"
        java_name = "".join(
            w.capitalize() if i else w.lower()
            for i, w in enumerate(name.split("-")[1:])
        )
        return f"ar.{java_name}"
    raise KeyError(name)


def _pic_description(field: Field) -> str:
    if not field.numeric:
        return f"alphanumeric, width {field.width}"
    sign = "signed" if field.signed else "unsigned"
    return f"numeric, {sign}, scale {field.decimal_scale} (exact decimal, java.math.BigDecimal)"


ROLE = (
    "You are translating a single COBOL paragraph into the body of one "
    "Java method. You are not translating the whole program -- only this "
    "one paragraph's logic."
)

SEMANTIC_RULES = """\
Semantic rules -- these are absolute, not stylistic preferences:
1. Arithmetic truncates toward zero unless the source explicitly says
   ROUNDED. This is COBOL's default and is the OPPOSITE of Java's usual
   rounding convention -- do not round-half-up.
2. All numeric values are exact decimal at their declared scale
   (java.math.BigDecimal). Binary floating point (float, double) is
   forbidden anywhere in the returned body.
3. A REDEFINES field reads the same bytes as its target and must be
   accessed only through the accessor method already provided for it
   (e.g. ar.dormant()) -- never re-derived, never treated as a separate
   field.
4. Condition names (88-levels) are evaluated only through the boolean
   accessor already provided for them (e.g. ar.isPremium()) -- never by
   comparing the parent field to a literal string yourself.
"""

PROHIBITIONS = """\
Prohibitions -- the returned body must not:
- declare or reference any field not listed in the field table below
- declare a helper method, inner class, or import
- modify any scaffold class (AccountRecord, ReportLine, TotalsLine,
  WorkingStorage, CobolEdit) -- you may only call the accessors it exposes
- use float, double, Math.round, or any ROUNDED-style rounding call
- write to ws.totalInterest -- the generated main loop owns that
  accumulation; this paragraph only sets ws.appliedRate and ws.interest
"""

OUTPUT_CONTRACT = """\
Output contract -- respond with exactly one JSON object, nothing else
(no prose, no markdown code fence):
{
  "method_body": "<the Java statements to run inside the method body, as a single string>",
  "assumptions": ["<any assumption you made, if none: empty list>"]
}
"""


def build_synthesis_prompt(paragraph: Paragraph, context: DataContext, java_signature: str) -> str:
    field_lines = []
    for name in context.read_fields + context.written_fields:
        if name in _WS_SCAFFOLD_OWNED:
            continue
        if name in _WS_ACCESSORS:
            field_lines.append(f"- {name}: working storage, exact decimal scale 5 or 2, accessor {_accessor(name)}")
            continue
        field = _INPUT_ACCESSORS.get(name)
        if field is None:
            continue
        field_lines.append(f"- {name}: {_pic_description(field)}, accessor {_accessor(name)}")
    field_table = "\n".join(sorted(set(field_lines))) or "(none)"

    condition_lines = [
        f'- {c.java_name}(): true when {c.parent_field} == "{c.true_value}"'
        for c in context.condition_names
    ]
    condition_table = "\n".join(condition_lines) or "(none)"

    return f"""\
{ROLE}

{SEMANTIC_RULES}
Field table for this paragraph's context:
{field_table}

Condition names in scope:
{condition_table}

The method body must fit this signature (do not repeat the signature in
your answer -- return only the statements that go inside it):
{java_signature}

{PROHIBITIONS}
COBOL paragraph source, verbatim ({paragraph.identifier}, lines {paragraph.start_line}-{paragraph.end_line}):
```
{paragraph.source}
```

{OUTPUT_CONTRACT}"""


SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "method_body": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["method_body", "assumptions"],
}


if __name__ == "__main__":
    from pathlib import Path

    from weaver.agent.data_context import build_context
    from weaver.agent.segment import segment

    src = Path("fixtures/cobol/interest.cob").read_text()
    paragraphs = {p.identifier: p for p in segment(src)}
    pr = paragraphs["PROCESS-RECORD"]
    ctx = build_context(pr)
    prompt = build_synthesis_prompt(pr, ctx, "static void processRecord(AccountRecord ar, WorkingStorage ws)")
    print(prompt)
    print(f"\n--- prompt length: {len(prompt)} chars ---")
