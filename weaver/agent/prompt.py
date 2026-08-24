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

import re

from weaver.agent.data_context import DataContext
from weaver.agent.scaffold import (
    ConditionName,
    INTEREST_SPEC,
    ScaffoldSpec,
    ws_accessors,
    ws_cobol_name,
    ws_scaffold_owned,
)
from weaver.agent.segment import Paragraph
from weaver.layout import Field

_TO_TARGET_RE = re.compile(r"\bTO\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
_WRITE_RE = re.compile(r"^\s*WRITE\b", re.IGNORECASE)


def _scaffold_owned_targets(spec: ScaffoldSpec) -> set[str]:
    """Names the scaffold's generated main loop owns: report/totals output
    fields (constructed via ScaffoldSpec.report_ctor_map / totals_ctor_map,
    never by the paragraph method) and the accumulator working-storage
    field. A paragraph's COBOL source routinely ends with the
    MOVE ... TO RL-*/TL-* and WRITE statements that populate those records --
    real-world testing (2026-08-07) showed the model translates those
    statements literally (e.g. `rl.id = ar.id; ... reportLine.write();`)
    because the prompt told it what fields exist but never which trailing
    statements belong to the scaffold, not the paragraph.
    """
    return {f.name for f in spec.report_layout} | {f.name for f in spec.totals_layout} | ws_scaffold_owned(spec)


def _scaffold_owned_lines(paragraph: Paragraph, spec: ScaffoldSpec = INTEREST_SPEC) -> list[str]:
    """Lines in this paragraph's source that MOVE/ADD into a scaffold-owned
    target (a report/totals field or accumulator) or WRITE a record --
    these are performed by the generated main loop and must not be
    reproduced in the returned method body.
    """
    owned_targets = _scaffold_owned_targets(spec)
    owned_lines = []
    for line in paragraph.source.splitlines():
        target_match = _TO_TARGET_RE.search(line)
        if target_match and target_match.group(1).upper() in owned_targets:
            owned_lines.append(line.strip())
        elif _WRITE_RE.match(line):
            owned_lines.append(line.strip())
    return owned_lines


def _accessor(name: str, spec: ScaffoldSpec) -> str:
    accessors = ws_accessors(spec)
    if name in accessors:
        return accessors[name]
    field = {f.name: f for f in spec.input_layout}.get(name)
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
3. If, and only if, a field in the field table below is described as a
   REDEFINES accessor, read it only through that exact accessor method --
   never re-derived, never treated as a separate field. If no field below
   is described that way, this rule does not apply to this paragraph.
4. If, and only if, the condition-name table below is non-empty, evaluate
   each listed condition only through its exact accessor method shown
   there -- never by comparing the parent field to a literal string
   yourself. If that table says "(none)", this paragraph has no condition
   names available at all -- do not invent, assume, or reference one.
"""

WORKED_EXAMPLE = """\
Worked example (a different, fictitious paragraph -- shown only to
illustrate the required style; do not reuse its logic or field names):

COBOL:
    COMPUTE-PENALTY.
        IF AC-OVERDUE
            COMPUTE WS-PENALTY = AC-BALANCE * 0.02
        ELSE
            MOVE ZERO TO WS-PENALTY
        END-IF.

Correct Java body for that example, respecting every rule above:
    if (ac.isOverdue()) {
        ws.penalty = ac.balance.multiply(new java.math.BigDecimal("0.02"))
            .setScale(2, java.math.RoundingMode.DOWN);
    } else {
        ws.penalty = java.math.BigDecimal.ZERO.setScale(2);
    }

Correct JSON response for that example:
{"method_body": "if (ac.isOverdue()) {\\n    ws.penalty = ac.balance.multiply(new java.math.BigDecimal(\\"0.02\\")).setScale(2, java.math.RoundingMode.DOWN);\\n} else {\\n    ws.penalty = java.math.BigDecimal.ZERO.setScale(2);\\n}", "assumptions": []}

Notice: every BigDecimal/RoundingMode reference is fully qualified as
java.math.BigDecimal / java.math.RoundingMode (the scaffold declares no
imports, so an unqualified type name will not compile), every setScale
call names DOWN explicitly, and the condition is read through its boolean
accessor, never a string comparison.
"""

# Found 2026-08-23 (fixtures/cobol/multiprog/root.cob, a paragraph with no
# IF/EVALUATE at all -- just unconditional assignments): showing an
# if/else-shaped worked example unconditionally, even to a paragraph with
# no conditional logic of its own, reliably made the model invent a
# nonexistent condition (`ar.isInvalid()` or similar) and wrap unrelated
# straight-line logic in it anyway -- the worked example's SHAPE, not just
# its wording, is a strong prior. build_synthesis_prompt now picks this
# straight-line variant whenever the paragraph itself has no IF/EVALUATE,
# so the shown style always matches the target paragraph's own structure.
WORKED_EXAMPLE_STRAIGHT_LINE = """\
Worked example (a different, fictitious paragraph -- shown only to
illustrate the required style; do not reuse its logic or field names):

COBOL:
    COMPUTE-SURCHARGE.
        COMPUTE WS-SURCHARGE = AC-BALANCE * 0.02.
        ADD 1 TO WS-SURCHARGE.

Correct Java body for that example, respecting every rule above:
    ws.surcharge = ac.balance.multiply(new java.math.BigDecimal("0.02"))
        .setScale(2, java.math.RoundingMode.DOWN);
    ws.surcharge = ws.surcharge.add(java.math.BigDecimal.ONE);

Correct JSON response for that example:
{"method_body": "ws.surcharge = ac.balance.multiply(new java.math.BigDecimal(\\"0.02\\")).setScale(2, java.math.RoundingMode.DOWN);\\nws.surcharge = ws.surcharge.add(java.math.BigDecimal.ONE);", "assumptions": []}

Notice: this paragraph has no IF/EVALUATE, so its Java translation has no
conditional either -- do NOT add an if/else, a condition check, or any
branch that isn't in the actual COBOL paragraph you are translating below.
Every BigDecimal/RoundingMode reference is fully qualified as
java.math.BigDecimal / java.math.RoundingMode (the scaffold declares no
imports, so an unqualified type name will not compile), and every
setScale call names DOWN explicitly.
"""

_CONDITIONAL_RE = re.compile(r"\b(IF|EVALUATE)\b", re.IGNORECASE)


def _join_and(items: list[str]) -> str:
    """['a', 'b'] -> 'a and b'; ['a', 'b', 'c'] -> 'a, b and c'.

    The S1 generalization replaced the hand-written "and" with a plain
    ", ".join, which changed a reviewed prompt sentence incidentally rather
    than deliberately. The prompt is hashed into the model cache key (J4),
    so its wording is a behavioural input, not formatting -- restored here
    and pinned by tests/test_cobol_frontend.py.
    """
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _prohibitions(spec: ScaffoldSpec) -> str:
    settable = _join_and(
        [f"ws.{a.split('.')[-1]}" for a in sorted(ws_accessors(spec).values())]
    ) or "(none)"
    # A program with no running-total accumulator (e.g. a per-record report
    # with no TOTALS line) has spec.accumulator_field == "" -- the bullet
    # below used to render as the malformed "write to ws. -- ..." in that
    # case (found 2026-08-23 while debugging ROOT.cob's synthesis prompt).
    # Omit the bullet entirely rather than describe a field that doesn't exist.
    accumulator_bullet = (
        f"- write to ws.{spec.accumulator_field} -- the generated main loop owns that\n"
        f"  accumulation; this paragraph only sets {settable}\n"
        if spec.accumulator_field else ""
    )
    return f"""\
Prohibitions -- the returned body must not:
- declare or reference any field not listed in the field table below
- declare a helper method, inner class, or import
- modify any scaffold class (AccountRecord, ReportLine, TotalsLine,
  WorkingStorage, CobolEdit) -- you may only call the accessors it exposes
- use float, double, Math.round, or any ROUNDED-style rounding call
{accumulator_bullet}"""


OUTPUT_CONTRACT = """\
Output contract -- respond with exactly one JSON object, nothing else
(no prose, no markdown code fence):
{
  "method_body": "<the Java statements to run inside the method body, as a single string>",
  "assumptions": ["<any assumption you made, if none: empty list>"]
}
"""


def build_synthesis_prompt(paragraph: Paragraph, context: DataContext, java_signature: str,
                            spec: ScaffoldSpec = INTEREST_SPEC, extra_context: str = "") -> str:
    owned = ws_scaffold_owned(spec)
    accessors = ws_accessors(spec)
    # COBOL WS name -> declared scale, so the field table states each
    # field's own scale instead of interest.cob's two WS fields' scales
    # (5 and 2) baked in as literal text -- see 2026-08-12 audit.
    ws_scales = {ws_cobol_name(f.java_name): f.scale for f in spec.ws_fields}
    input_accessors = {f.name: f for f in spec.input_layout}
    field_lines = []
    for name in context.read_fields + context.written_fields:
        if name in owned:
            continue
        if name in accessors:
            scale = ws_scales.get(name)
            scale_desc = f"scale {scale}" if scale is not None else "scale per WorkingStorageField declaration"
            field_lines.append(
                f"- {name}: working storage, exact decimal {scale_desc}, accessor {_accessor(name, spec)}")
            continue
        field = input_accessors.get(name)
        if field is None:
            continue
        field_lines.append(f"- {name}: {_pic_description(field)}, accessor {_accessor(name, spec)}")
    field_table = "\n".join(sorted(set(field_lines))) or "(none)"

    condition_lines = [
        f'- {c.java_name}(): true when {c.parent_field} == "{c.true_value}"'
        for c in context.condition_names
    ]
    condition_table = "\n".join(condition_lines) or "(none)"

    owned_lines = _scaffold_owned_lines(paragraph, spec)
    if owned_lines:
        owned_list = "\n".join(f"    {line}" for line in owned_lines)
        # spec.accumulator_field is "" for a program with no running total
        # (e.g. fixtures/cobol/multiprog/root.cob) -- "writing to ws." with
        # nothing after the dot is a real, found-2026-08-23 wording bug for
        # that case; only mention the accumulator when one actually exists.
        accumulator_mention = (
            f" and/or the running total, which the generated main loop already does"
            f"\noutside this method (see the prohibition above against writing to"
            f"\nws.{spec.accumulator_field})"
            if spec.accumulator_field else ""
        )
        scaffold_owned_section = f"""\
Statements you must NOT translate -- the paragraph source below includes
the following statements verbatim, but they populate the output record{accumulator_mention}.
Omit every one of these from your returned body:
{owned_list}

"""
    else:
        scaffold_owned_section = ""

    if extra_context:
        extra_context_section = f"""\
{extra_context}

"""
    else:
        extra_context_section = ""

    worked_example = WORKED_EXAMPLE if _CONDITIONAL_RE.search(paragraph.source) else WORKED_EXAMPLE_STRAIGHT_LINE

    return f"""\
{ROLE}

{SEMANTIC_RULES}
{worked_example}
{extra_context_section}Field table for this paragraph's context:
{field_table}

Condition names in scope:
{condition_table}

The method body must fit this signature (do not repeat the signature in
your answer -- return only the statements that go inside it):
{java_signature}

{_prohibitions(spec)}
{scaffold_owned_section}COBOL paragraph source, verbatim ({paragraph.identifier}, lines {paragraph.start_line}-{paragraph.end_line}):
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

    src = Path("fixtures/cobol/interest.cob").read_text(encoding="utf-8")
    paragraphs = {p.identifier: p for p in segment(src)}
    pr = paragraphs["PROCESS-RECORD"]
    ctx = build_context(pr)
    prompt = build_synthesis_prompt(pr, ctx, "static void processRecord(AccountRecord ar, WorkingStorage ws)")
    print(prompt)
    print(f"\n--- prompt length: {len(prompt)} chars ---")
