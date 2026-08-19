"""ProgramGraph data model + query surface — GRAPH_PLAN.md M3.

Fulfils SRS FR-2.1 (dependency graph), FR-2.2 (migration ordering), and
FR-2.3 (plan exposure via to_json()) -- all three previously unimplemented
(there was no weaver/agent/graph.py before this). Assembles callgraph.py's
(M1) PERFORM/CALL edges and dataflow.py's (M2) read/write sets, attaching
the paragraph identity neither of those modules bakes in themselves.

Serialization follows Report.to_json()/RunSpec.to_dict()'s existing
convention: an explicit payload dict, never raw dataclasses.asdict() on
anything holding a set (JSON has no set type; asdict() would silently
produce something non-round-trippable).
"""

from __future__ import annotations

import json
from pathlib import Path

from weaver.agent.graph import CallEdge, PerformEdge, from_paragraphs
from weaver.agent.segment import Paragraph, segment
from weaver.cobol.dataflow import ReadWriteSet

INTEREST_COB = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "interest.cob"


def _paragraph(identifier: str, source: str) -> Paragraph:
    return Paragraph(identifier=identifier, start_line=1, end_line=1, source=source)


def test_from_paragraphs_builds_a_perform_edge():
    paragraphs = [
        _paragraph("MAIN-PARA", "MAIN-PARA.\n    PERFORM PROCESS-RECORD.\n"),
        _paragraph("PROCESS-RECORD", "PROCESS-RECORD.\n    MOVE AR-ID TO RL-ID.\n"),
    ]
    graph = from_paragraphs("TEST", paragraphs)

    assert graph.performs == (PerformEdge(source="MAIN-PARA", target="PROCESS-RECORD", kind="SIMPLE"),)


def test_from_paragraphs_builds_a_call_edge():
    paragraphs = [_paragraph("MAIN-PARA", 'MAIN-PARA.\n    CALL "SUBPROG".\n')]
    graph = from_paragraphs("TEST", paragraphs)

    assert graph.calls == (CallEdge(source="MAIN-PARA", program="SUBPROG"),)


def test_from_paragraphs_attaches_read_write_sets_per_paragraph():
    paragraphs = [_paragraph("P", "P.\n    MOVE AR-ID TO RL-ID.\n")]
    graph = from_paragraphs("TEST", paragraphs)

    assert graph.read_write_sets["P"] == ReadWriteSet("P", frozenset({"AR-ID"}), frozenset({"RL-ID"}))


def test_callees_and_callers_query_the_perform_graph():
    paragraphs = [
        _paragraph("MAIN-PARA", "MAIN-PARA.\n    PERFORM PROCESS-RECORD.\n"),
        _paragraph("PROCESS-RECORD", "PROCESS-RECORD.\n    MOVE AR-ID TO RL-ID.\n"),
    ]
    graph = from_paragraphs("TEST", paragraphs)

    assert graph.callees("MAIN-PARA") == ["PROCESS-RECORD"]
    assert graph.callers("PROCESS-RECORD") == ["MAIN-PARA"]
    assert graph.callees("PROCESS-RECORD") == []
    assert graph.callers("MAIN-PARA") == []


def test_readers_of_and_writers_of_query_the_field_access_sets():
    paragraphs = [
        _paragraph("A", "A.\n    MOVE X TO Y.\n"),
        _paragraph("B", "B.\n    MOVE Y TO Z.\n"),
    ]
    graph = from_paragraphs("TEST", paragraphs)

    assert graph.writers_of("Y") == ["A"]
    assert graph.readers_of("Y") == ["B"]
    assert graph.writers_of("Z") == ["B"]
    assert graph.readers_of("X") == ["A"]
    assert graph.readers_of("Q") == []


def test_topological_order_is_leaf_first_on_a_perform_chain():
    """PROCESS-RECORD performs nothing and is performed by MAIN-PARA -- it
    is the leaf and must come first, matching SRS FR-2.2's "leaf-first"
    wording."""
    paragraphs = [
        _paragraph("MAIN-PARA", "MAIN-PARA.\n    PERFORM PROCESS-RECORD.\n"),
        _paragraph("PROCESS-RECORD", "PROCESS-RECORD.\n    MOVE AR-ID TO RL-ID.\n"),
    ]
    graph = from_paragraphs("TEST", paragraphs)

    order = graph.topological_order()

    assert order == [["PROCESS-RECORD"], ["MAIN-PARA"]]


def test_topological_order_collapses_a_perform_cycle_into_one_composite_unit():
    """A performs B and B performs A -- neither is ever a leaf. FR-2.2:
    'Cycles shall be collapsed into a single composite Migration Unit and
    flagged.'"""
    paragraphs = [
        _paragraph("A", "A.\n    PERFORM B.\n"),
        _paragraph("B", "B.\n    PERFORM A.\n"),
    ]
    graph = from_paragraphs("TEST", paragraphs)

    order = graph.topological_order()

    assert len(order) == 1
    assert set(order[0]) == {"A", "B"}


def test_to_json_round_trips_through_to_dict():
    paragraphs = [
        _paragraph("MAIN-PARA", "MAIN-PARA.\n    PERFORM PROCESS-RECORD.\n"),
        _paragraph("PROCESS-RECORD", "PROCESS-RECORD.\n    MOVE AR-ID TO RL-ID.\n"),
    ]
    graph = from_paragraphs("TEST", paragraphs)

    payload = json.loads(graph.to_json())

    assert payload["program_id"] == "TEST"
    assert set(payload["paragraphs"]) == {"MAIN-PARA", "PROCESS-RECORD"}
    assert payload["performs"] == [
        {"source": "MAIN-PARA", "target": "PROCESS-RECORD", "kind": "SIMPLE", "thru_target": None}
    ]
    assert payload["read_write_sets"]["PROCESS-RECORD"]["reads"] == ["AR-ID"]
    assert payload["read_write_sets"]["PROCESS-RECORD"]["writes"] == ["RL-ID"]


def test_real_fixture_interest_cob_graph():
    """Grounds the assembled graph in the same real fixture M1/M2 were
    hand-verified against."""
    source = INTEREST_COB.read_text(encoding="utf-8")
    paragraphs = segment(source)

    graph = from_paragraphs("INTEREST", paragraphs)

    assert graph.callees("MAIN-PARA") == ["PROCESS-RECORD"]
    assert graph.topological_order() == [["PROCESS-RECORD"], ["MAIN-PARA"]]
