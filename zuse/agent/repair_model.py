"""Model-assisted repair — Step N3.

Handles the defect classes that genuinely require interpretation:
TRUNCATION, CONTROL_FLOW, and COMPILE_ERROR (a fourth "class" -- a failed
compile, not a `DefectClass` value, but it needs the same treatment: model
sees the error and tries again). Every previous attempt and why it failed
is included every time -- the plan's most common repair-loop bug is
omitting this and getting the same wrong answer back from a temperature-0
model.
"""

from __future__ import annotations

from dataclasses import dataclass

from zuse.agent.prompt import _accessor, _pic_description, _scaffold_owned_lines
from zuse.agent.scaffold import (
    INTEREST_SPEC,
    ScaffoldSpec,
    ws_accessors,
    ws_cobol_name,
)
from zuse.agent.segment import Paragraph
from zuse.classification import Classification, DefectClass
from zuse.comparison import Divergence

STRATEGY_HINTS = {
    DefectClass.TRUNCATION: (
        "The delta is within one unit of the field's declared scale. COBOL's "
        "default COMPUTE truncates toward zero (RoundingMode.DOWN), never "
        "rounds. Check every intermediate BigDecimal operation -- a stray "
        "RoundingMode other than DOWN, or a missing setScale before a value "
        "is used downstream, both produce exactly this signature."
    ),
    DefectClass.CONTROL_FLOW: (
        "One side took a different branch than the other (a value is zero "
        "on one side and not the other, or a record is missing). Re-check "
        "which condition-name accessor (e.g. ar.isDormant(), ar.isPremium()) "
        "gates which branch, and that every branch of the COBOL IF/ELSE is "
        "represented."
    ),
    "COMPILE_ERROR": (
        "The body did not compile. Only java.math.BigDecimal, "
        "java.math.RoundingMode, and the accessors on ar/ws are available; "
        "there are no import statements in the scaffold, so every type must "
        "be fully qualified (java.math.BigDecimal, not BigDecimal)."
    ),
}


def _field_table(spec: ScaffoldSpec) -> str:
    """Every ar./ws. accessor available to a repair attempt, with its exact
    Java syntax (field vs. method). The repair loop has no DataContext
    (unlike synthesis), so this lists the full scaffold surface rather than
    just the fields one paragraph reads/writes -- real-world testing
    (shipcost.cob, 2026-08-12) showed the model thrashing between
    `ar.weight` and `ar.weight()` across repair attempts because the repair
    prompt never stated which one the scaffold actually generates.
    """
    lines = []
    for name, accessor in sorted(ws_accessors(spec).items()):
        lines.append(f"- {name}: working storage, accessor {accessor}")
    for f in spec.input_layout:
        lines.append(
            f"- {f.name}: {_pic_description(f)}, accessor {_accessor(f.name, spec)}"
        )
    for c in spec.condition_names:
        lines.append(
            f'- {c.java_name}(): true when {c.parent_field} == "{c.true_value}"'
        )
    return "\n".join(lines) or "(none)"


@dataclass
class RepairAttempt:
    attempt_number: int
    body: str
    outcome: str  # e.g. "compile_error", "still diverges: TRUNCATION on record 91", "regression"
    diagnostics: str | None = None


def build_repair_prompt(
    paragraph: Paragraph,
    java_signature: str,
    current_body: str,
    defect_class: DefectClass | str,
    classification: Classification | None,
    failing_divergence: Divergence | None,
    attempts: list[RepairAttempt],
    spec: ScaffoldSpec = INTEREST_SPEC,
) -> str:
    strategy_hint = STRATEGY_HINTS.get(
        defect_class, "Diagnose from the evidence below."
    )

    evidence_lines = ["The current method body:", "```java", current_body, "```", ""]

    if failing_divergence is not None:
        evidence_lines += [
            f"Failing input record (verbatim): {failing_divergence.causing_input_record!r}",
            f"Oracle value:     {failing_divergence.oracle_value!r}",
            f"Candidate value:  {failing_divergence.candidate_value!r}",
            f"Delta:            {failing_divergence.numeric_delta}",
            f"Field:            {failing_divergence.field_name}",
            "",
        ]
    if classification is not None:
        evidence_lines += [
            f"Defect classification: {classification.defect_class.value} "
            f"(confidence {classification.confidence})",
            "",
        ]

    history_lines = ["Every previous attempt for this unit, and why it failed:"]
    if not attempts:
        history_lines.append("(none -- this is the first repair attempt)")
    else:
        for a in attempts:
            history_lines.append(f"--- Attempt {a.attempt_number} ---")
            history_lines.append(a.body)
            history_lines.append(f"Outcome: {a.outcome}")
            if a.diagnostics:
                history_lines.append(f"Diagnostics: {a.diagnostics}")
    history = "\n".join(history_lines)

    owned_lines = _scaffold_owned_lines(paragraph, spec)
    if owned_lines:
        owned_list = "\n".join(f"    {line}" for line in owned_lines)
        scaffold_owned_section = f"""\
Statements you must NOT translate -- these populate the output record
and/or the running total, which the generated main loop already does
outside this method:
{owned_list}

"""
    else:
        scaffold_owned_section = ""

    return f"""\
You are repairing a Java method body that failed verification against a
COBOL oracle. This is a repair, not a fresh translation -- take the
evidence below seriously; do not repeat a previous attempt.

Strategy hint: {strategy_hint}

{chr(10).join(evidence_lines)}
Originating COBOL paragraph ({paragraph.identifier}):
```
{paragraph.source}
```

Field table -- the exact accessor syntax for every field/condition on
ar/ws (do not guess between a plain field and a method call):
{_field_table(spec)}

{scaffold_owned_section}{history}

The method body must fit this signature (return only the statements that
go inside it):
{java_signature}

Respond with exactly one JSON object, nothing else:
{{
  "method_body": "<the corrected Java statements, as a single string>",
  "assumptions": ["<any assumption you made, if none: empty list>"]
}}
"""
