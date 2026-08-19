"""Per-paragraph read/write field-set extraction — GRAPH_PLAN.md M2.

Scope, per GRAPH_PLAN.md §4: MOVE, ADD, COMPUTE, and IF/EVALUATE
conditions. Nothing walks WRITE/READ/OPEN (those are file I/O, already
covered by procedure.py's open_modes()) or PERFORM (that's callgraph.py's
job, M1) -- dataflow.py answers "which fields does this paragraph's own
business logic touch," not "what does it call" or "what file does it
read."

The `PROCESS-RECORD` case is hand-verified against `interest.cob`'s source
by paper trace, the same discipline GRAPH_PLAN.md's M2 exit criteria
requires (mirroring the retired oracle_hand_verification.md's approach,
now inlined here since that file no longer exists).
"""

from __future__ import annotations

from pathlib import Path

from weaver.cobol.dataflow import ReadWriteSet, read_write_set

INTEREST_COB = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "interest.cob"


def test_move_reads_source_and_writes_target():
    text = "P.\n    MOVE AR-ID TO RL-ID.\n"
    rw = read_write_set("P", text)
    assert rw.reads == frozenset({"AR-ID"})
    assert rw.writes == frozenset({"RL-ID"})


def test_move_of_a_figurative_constant_is_not_a_read():
    """MOVE ZERO TO X -- ZERO is a figurative constant, not a field; only
    X is written, and there is no corresponding field read."""
    text = "P.\n    MOVE ZERO TO WS-INTEREST.\n"
    rw = read_write_set("P", text)
    assert rw.reads == frozenset()
    assert rw.writes == frozenset({"WS-INTEREST"})


def test_add_without_giving_reads_and_writes_the_target():
    """ADD a TO b: b is both read (accumulator's current value) and
    written (the new total)."""
    text = "P.\n    ADD WS-INTEREST TO WS-TOTAL-INTEREST.\n"
    rw = read_write_set("P", text)
    assert rw.reads == frozenset({"WS-INTEREST", "WS-TOTAL-INTEREST"})
    assert rw.writes == frozenset({"WS-TOTAL-INTEREST"})


def test_compute_reads_expression_identifiers_and_writes_target():
    text = "P.\n    COMPUTE WS-INTEREST = AR-BALANCE * WS-APPLIED-RATE / 365.\n"
    rw = read_write_set("P", text)
    assert rw.reads == frozenset({"AR-BALANCE", "WS-APPLIED-RATE"})
    assert rw.writes == frozenset({"WS-INTEREST"})
    # 365 is a numeric literal, never a field.
    assert "365" not in rw.reads


def test_if_condition_identifier_is_a_read():
    text = "P.\n    IF AR-PREMIUM\n        MOVE AR-RATE TO WS-APPLIED-RATE\n    END-IF.\n"
    rw = read_write_set("P", text)
    assert "AR-PREMIUM" in rw.reads


def test_paragraph_header_itself_contributes_no_reads_or_writes():
    text = "PROCESS-RECORD.\n    MOVE AR-ID TO RL-ID.\n"
    rw = read_write_set("PROCESS-RECORD", text)
    assert rw.reads == frozenset({"AR-ID"})
    assert rw.writes == frozenset({"RL-ID"})


def test_process_record_hand_verified_against_the_real_fixture():
    """Full-paragraph paper trace of PROCESS-RECORD in interest.cob,
    verified statement by statement against the source shown in
    fixtures/cobol/interest.cob -- this is the M2 acceptance discipline
    GRAPH_PLAN.md requires."""
    source = INTEREST_COB.read_text(encoding="utf-8")
    from weaver.agent.segment import segment

    process_record = next(p for p in segment(source) if p.identifier == "PROCESS-RECORD")

    rw = read_write_set("PROCESS-RECORD", process_record.source)

    expected_reads = {
        "AR-PREMIUM", "AR-RATE", "AR-IS-DORMANT", "AR-BALANCE", "WS-APPLIED-RATE",
        "WS-INTEREST", "WS-TOTAL-INTEREST", "AR-ID", "AR-TYPE", "AR-DORMANT",
    }
    expected_writes = {
        "WS-APPLIED-RATE", "WS-INTEREST", "WS-TOTAL-INTEREST",
        "RL-ID", "RL-TYPE", "RL-BALANCE", "RL-INTEREST", "RL-DORMANT",
    }

    assert rw == ReadWriteSet("PROCESS-RECORD", frozenset(expected_reads), frozenset(expected_writes))
