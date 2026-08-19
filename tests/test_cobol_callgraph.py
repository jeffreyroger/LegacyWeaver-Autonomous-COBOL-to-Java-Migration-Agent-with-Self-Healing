"""PERFORM/CALL edge extraction — GRAPH_PLAN.md M1.

`weaver/cobol/procedure.py` already regex-scrapes MOVE/ADD/OPEN from
paragraph text (Steps U3/U5), returning statement-local dataclasses
(Move.source/target, Add.source/target) with no paragraph identity baked
in -- the caller pairs them with a paragraph id itself. This module
follows the same convention for PERFORM (paragraph-to-paragraph control
flow) and same-file CALL (literal program name), neither of which
weaver/cobol/ has ever extracted -- confirmed by the Explore-agent
research behind GRAPH_PLAN.md: segment.py only finds paragraph
*boundaries*, never relationships between them.

`performs()` is intentionally scoped to *known* paragraph identifiers
(passed in by the caller, e.g. segment()'s output) so that a bare
`PERFORM UNTIL ...` / `PERFORM VARYING ...` inline loop -- which is not a
call to another paragraph -- is never mistaken for one; the first token
after PERFORM in an inline loop is a keyword, not a paragraph name, and so
never matches a known identifier.
"""

from __future__ import annotations

from pathlib import Path

from weaver.agent.segment import segment
from weaver.cobol.callgraph import Call, Perform, calls, performs

INTEREST_COB = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "interest.cob"


def test_simple_perform_of_a_known_paragraph_is_an_edge():
    text = "MAIN-PARA.\n    PERFORM PROCESS-RECORD.\n"
    result = performs(text, known_paragraphs={"MAIN-PARA", "PROCESS-RECORD"})
    assert result == [Perform(target="PROCESS-RECORD", kind="SIMPLE")]


def test_perform_thru_produces_a_thru_edge():
    text = "MAIN-PARA.\n    PERFORM STEP-ONE THRU STEP-THREE.\n"
    result = performs(
        text, known_paragraphs={"MAIN-PARA", "STEP-ONE", "STEP-TWO", "STEP-THREE"},
    )
    assert result == [Perform(target="STEP-ONE", kind="THRU", thru_target="STEP-THREE")]


def test_perform_through_is_equivalent_to_thru():
    text = "MAIN-PARA.\n    PERFORM STEP-ONE THROUGH STEP-THREE.\n"
    result = performs(text, known_paragraphs={"MAIN-PARA", "STEP-ONE", "STEP-THREE"})
    assert result == [Perform(target="STEP-ONE", kind="THRU", thru_target="STEP-THREE")]


def test_perform_until_inline_loop_is_not_mistaken_for_a_paragraph_call():
    """PERFORM UNTIL/VARYING is an inline loop, not a call -- UNTIL/VARYING
    are never paragraph identifiers, so no edge should be produced."""
    text = "MAIN-PARA.\n    PERFORM UNTIL WS-EOF\n        READ ACCOUNT-FILE\n    END-PERFORM.\n"
    result = performs(text, known_paragraphs={"MAIN-PARA"})
    assert result == []


def test_perform_of_an_unknown_identifier_is_not_an_edge():
    """A PERFORM naming something that isn't in the known-paragraphs set
    (e.g. a mistyped label, or text taken out of context) must not
    fabricate an edge to a nonexistent target."""
    text = "MAIN-PARA.\n    PERFORM SOME-OTHER-PROGRAMS-PARAGRAPH.\n"
    result = performs(text, known_paragraphs={"MAIN-PARA"})
    assert result == []


def test_real_fixture_main_para_performs_process_record():
    """Grounds the extractor in a real, already-verified fixture rather
    than only synthetic text -- isolates MAIN-PARA's own body via the
    existing segment() the way a real caller would."""
    source = INTEREST_COB.read_text(encoding="utf-8")
    paragraphs = segment(source)
    known = {p.identifier for p in paragraphs}
    main_para = next(p for p in paragraphs if p.identifier == "MAIN-PARA")

    result = performs(main_para.source, known_paragraphs=known)

    assert Perform(target="PROCESS-RECORD", kind="SIMPLE") in result


def test_call_with_literal_program_name_is_an_edge():
    text = 'MAIN-PARA.\n    CALL "SUBPROG" USING WS-ARG.\n'
    result = calls(text)
    assert result == [Call(program="SUBPROG")]


def test_call_with_dynamic_identifier_target_is_skipped():
    """A CALL naming a variable (dynamic call target) is out of scope for
    this phase -- same-file CALL only models literal program names."""
    text = "MAIN-PARA.\n    CALL WS-PROGRAM-NAME.\n"
    result = calls(text)
    assert result == []
