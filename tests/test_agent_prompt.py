"""Regression test for the M1 prompt-completeness gap (Change 4, 2026-08-07):
real-world testing found the model kept translating a paragraph's trailing
MOVE ... TO RL-*/WRITE statements literally (`rl.id = ar.id; ...
reportLine.write();`) even though those are scaffold-owned -- the prompt
told it which fields exist but never which trailing statements to drop.
"""

from pathlib import Path

from weaver.agent.data_context import build_context
from weaver.agent.prompt import build_synthesis_prompt
from weaver.agent.segment import segment

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
