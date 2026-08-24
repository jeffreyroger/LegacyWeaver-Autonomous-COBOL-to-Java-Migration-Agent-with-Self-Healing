"""Regression test for the M1 prompt-completeness gap (Change 4, 2026-08-07):
real-world testing found the model kept translating a paragraph's trailing
MOVE ... TO RL-*/WRITE statements literally (`rl.id = ar.id; ...
reportLine.write();`) even though those are scaffold-owned -- the prompt
told it which fields exist but never which trailing statements to drop.
"""

from pathlib import Path

from weaver.agent.data_context import build_context
from weaver.agent.prompt import WORKED_EXAMPLE, WORKED_EXAMPLE_STRAIGHT_LINE, build_synthesis_prompt
from weaver.agent.scaffold import java_signature as scaffold_java_signature
from weaver.agent.segment import segment
from weaver.cobol.frontend import load_program, to_scaffold_spec

JAVA_SIGNATURE = "static void processRecord(AccountRecord ar, WorkingStorage ws)"


def _process_record_paragraph():
    src = Path("fixtures/cobol/interest.cob").read_text()
    paragraphs = {p.identifier: p for p in segment(src)}
    return paragraphs["PROCESS-RECORD"]


def test_prompt_lists_scaffold_owned_trailing_statements_verbatim():
    paragraph = _process_record_paragraph()
    ctx = build_context(paragraph)
    prompt = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE)

    assert "Statements you must NOT translate" in prompt
    for expected_line in (
        "ADD WS-INTEREST TO WS-TOTAL-INTEREST",
        "MOVE AR-ID       TO RL-ID",
        "MOVE AR-TYPE     TO RL-TYPE",
        "MOVE AR-BALANCE  TO RL-BALANCE",
        "MOVE WS-INTEREST TO RL-INTEREST",
        "MOVE AR-DORMANT  TO RL-DORMANT",
        "WRITE REPORT-LINE.",
    ):
        assert expected_line in prompt, f"missing line: {expected_line!r}"


def test_semantic_rules_never_name_a_real_accessor():
    """Found 2026-08-23 debugging fixtures/cobol/multiprog/root.cob's
    synthesis: SEMANTIC_RULES used to illustrate rules 3/4 with interest.cob's
    OWN real accessor names (`ar.dormant()`, `ar.isPremium()`) -- granite-
    code:20b latched onto those as if they were real available accessors
    for ANY program and hallucinated them into ROOT's translation, which
    has neither a REDEFINES field nor a condition name at all. The rule
    text must never contain a real accessor name from any fixture."""
    paragraph = _process_record_paragraph()
    ctx = build_context(paragraph)
    prompt = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE)
    for real_accessor in ("ar.dormant()", "ar.isPremium()", "ar.isDormant()"):
        assert real_accessor not in prompt.split("Field table")[0], (
            f"{real_accessor!r} must not appear in the rules/instructions section"
        )


def test_straight_line_worked_example_used_for_a_paragraph_with_no_conditional():
    """A paragraph with no IF/EVALUATE (fixtures/cobol/multiprog/root.cob's
    PROCESS-RECORD: two unconditional CALLs and MOVEs) must get the
    straight-line worked example, not the if/else-shaped one -- found
    2026-08-23: showing an if/else example to an unconditional paragraph
    reliably made the model invent a nonexistent condition and wrap
    unrelated straight-line logic in it."""
    model = load_program(Path("fixtures/cobol/multiprog/root.cob"))
    spec = to_scaffold_spec(model)
    src = Path("fixtures/cobol/multiprog/root.cob").read_text(encoding="utf-8")
    paragraph = {p.identifier: p for p in segment(src)}["PROCESS-RECORD"]
    ctx = build_context(paragraph, spec)
    sig = scaffold_java_signature(spec)

    prompt = build_synthesis_prompt(paragraph, ctx, sig, spec)
    assert "COMPUTE-SURCHARGE" in prompt  # the straight-line example's fictitious paragraph
    assert "COMPUTE-PENALTY" not in prompt  # the if/else example must not also appear


def test_if_else_worked_example_used_for_a_paragraph_with_a_conditional():
    """interest.cob's PROCESS-RECORD has real IFs -- must keep getting the
    original if/else worked example, unchanged (byte-identical prompt,
    pinned by tests/test_cobol_frontend.py)."""
    paragraph = _process_record_paragraph()
    ctx = build_context(paragraph)
    prompt = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE)
    assert "COMPUTE-PENALTY" in prompt
    assert "COMPUTE-SURCHARGE" not in prompt
    assert WORKED_EXAMPLE in prompt
    assert WORKED_EXAMPLE_STRAIGHT_LINE not in prompt


def test_extra_context_is_appended_when_supplied():
    paragraph = _process_record_paragraph()
    ctx = build_context(paragraph)
    prompt = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE, extra_context="MARKER-TEXT-XYZ")
    assert "MARKER-TEXT-XYZ" in prompt


def test_extra_context_absent_by_default_is_byte_identical():
    """extra_context="" (the default) must not change a single byte of the
    prompt -- LeafOrchestrator is the only caller that ever sets it."""
    paragraph = _process_record_paragraph()
    ctx = build_context(paragraph)
    with_default = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE)
    with_explicit_empty = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE, extra_context="")
    assert with_default == with_explicit_empty


def test_prohibitions_omit_accumulator_bullet_when_there_is_no_accumulator():
    """spec.accumulator_field == "" (fixtures/cobol/multiprog/root.cob has
    no running total) used to render as the malformed "write to ws. --
    the generated main loop owns that accumulation" (found 2026-08-23) --
    the bullet, and the matching mention in the scaffold-owned-statements
    section, must be omitted entirely instead."""
    model = load_program(Path("fixtures/cobol/multiprog/root.cob"))
    spec = to_scaffold_spec(model)
    assert spec.accumulator_field == ""
    src = Path("fixtures/cobol/multiprog/root.cob").read_text(encoding="utf-8")
    paragraph = {p.identifier: p for p in segment(src)}["PROCESS-RECORD"]
    ctx = build_context(paragraph, spec)
    sig = scaffold_java_signature(spec)

    prompt = build_synthesis_prompt(paragraph, ctx, sig, spec)
    assert "write to ws." not in prompt
    assert "ws.)" not in prompt


def test_prompt_does_not_flag_ws_interest_or_applied_rate_as_scaffold_owned():
    # WS-APPLIED-RATE and WS-INTEREST are the paragraph's own outputs
    # (accessor ws.appliedRate / ws.interest) -- only WS-TOTAL-INTEREST
    # (the accumulator) and the RL-*/TL-* report fields are scaffold-owned.
    paragraph = _process_record_paragraph()
    ctx = build_context(paragraph)
    prompt = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE)

    owned_section = prompt.split("Statements you must NOT translate")[1].split("COBOL paragraph source")[0]
    assert "TO WS-APPLIED-RATE" not in owned_section
    assert "TO WS-INTEREST" not in owned_section


def test_repair_prompt_also_lists_scaffold_owned_statements():
    from weaver.agent.repair_model import build_repair_prompt

    paragraph = _process_record_paragraph()
    prompt = build_repair_prompt(
        paragraph, JAVA_SIGNATURE, "ws.interest = ar.balance;",
        "TRUNCATION", None, None, [],
    )
    assert "Statements you must NOT translate" in prompt
    assert "WRITE REPORT-LINE." in prompt


def test_prompt_omits_scaffold_owned_section_when_paragraph_has_none():
    from weaver.agent.segment import Paragraph

    paragraph = Paragraph(
        identifier="SIMPLE-PARA",
        source="       SIMPLE-PARA.\n           MOVE AR-RATE TO WS-APPLIED-RATE.\n",
        start_line=1,
        end_line=2,
    )
    ctx = build_context(paragraph)
    prompt = build_synthesis_prompt(paragraph, ctx, JAVA_SIGNATURE)
    assert "Statements you must NOT translate" not in prompt
