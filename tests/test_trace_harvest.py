"""Trace harvesting — GRAPH_PLAN.md M5.

`parse_trace()` is the pure, toolchain-free half: it turns captured stdout
(GnuCOBOL's DISPLAY output, which instrument.py's injected lines write to)
into `UnitFixture`s, independent of ever actually running an instrumented
binary. `harvest()` wraps `weaver.execution.run_oracle` around it and
necessarily needs a real compiled instrumented binary to exercise end to
end -- skipped here (no cobc in this environment), same boundary
test_instrument.py already draws.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weaver.agent.trace_harvest import UnitFixture, parse_trace

requires_cobc = pytest.mark.skipif(shutil.which("cobc") is None, reason="requires GnuCOBOL (cobc) on PATH")


def test_parses_one_complete_entry_exit_record():
    stdout = (
        'WEAVER-TRACE:PROCESS-RECORD:ENTRY:AR-ID=ACC0000001\n'
        'WEAVER-TRACE:PROCESS-RECORD:EXIT:RL-ID=ACC0000001\n'
    )
    fixtures = parse_trace(stdout)
    assert fixtures == [
        UnitFixture("PROCESS-RECORD", 0, {"AR-ID": "ACC0000001"}, {"RL-ID": "ACC0000001"})
    ]


def test_multiple_fields_per_phase_are_grouped_into_one_record():
    stdout = (
        "WEAVER-TRACE:P:ENTRY:A=1\n"
        "WEAVER-TRACE:P:ENTRY:B=2\n"
        "WEAVER-TRACE:P:EXIT:C=3\n"
        "WEAVER-TRACE:P:EXIT:D=4\n"
    )
    fixtures = parse_trace(stdout)
    assert fixtures == [UnitFixture("P", 0, {"A": "1", "B": "2"}, {"C": "3", "D": "4"})]


def test_multiple_records_increment_the_record_index_in_order():
    stdout = (
        "WEAVER-TRACE:P:ENTRY:A=first\n"
        "WEAVER-TRACE:P:EXIT:B=first-out\n"
        "WEAVER-TRACE:P:ENTRY:A=second\n"
        "WEAVER-TRACE:P:EXIT:B=second-out\n"
    )
    fixtures = parse_trace(stdout)
    assert [f.record_index for f in fixtures] == [0, 1]
    assert fixtures[0].input_state == {"A": "first"}
    assert fixtures[1].input_state == {"A": "second"}


def test_two_paragraphs_are_tracked_independently():
    stdout = (
        "WEAVER-TRACE:MAIN-PARA:ENTRY:X=1\n"
        "WEAVER-TRACE:MAIN-PARA:EXIT:Y=2\n"
        "WEAVER-TRACE:PROCESS-RECORD:ENTRY:A=3\n"
        "WEAVER-TRACE:PROCESS-RECORD:EXIT:B=4\n"
    )
    fixtures = parse_trace(stdout)
    ids = {f.paragraph_id for f in fixtures}
    assert ids == {"MAIN-PARA", "PROCESS-RECORD"}


def test_non_trace_lines_are_ignored():
    stdout = "some unrelated compiler or runtime noise\nWEAVER-TRACE:P:ENTRY:A=1\nWEAVER-TRACE:P:EXIT:B=2\n"
    fixtures = parse_trace(stdout)
    assert len(fixtures) == 1


def test_field_value_preserves_trailing_spaces_from_a_fixed_width_pic():
    """DISPLAY of a PIC X(16) field pads with trailing spaces -- these are
    real data (fixed-width comparison, CLAUDE.md rule 3), not noise to
    strip."""
    stdout = "WEAVER-TRACE:P:ENTRY:AR-ID=ACC0000001      \nWEAVER-TRACE:P:EXIT:RL-ID=X\n"
    fixtures = parse_trace(stdout)
    assert fixtures[0].input_state["AR-ID"] == "ACC0000001      "


def test_empty_stdout_produces_no_fixtures():
    assert parse_trace("") == []


@requires_cobc
def test_harvest_end_to_end_against_the_real_oracle(tmp_path):
    """The one check that needs GnuCOBOL: compile an instrumented
    interest.cob, run it against the real 200-record fixture, and confirm
    the harvested fixtures agree with the raw input bytes decoded through
    weaver.layout.INPUT_LAYOUT independently -- not just "harvest() ran
    without crashing," but "what it captured is actually correct."."""
    import subprocess

    from weaver.agent.graph import from_paragraphs
    from weaver.agent.instrument import instrument
    from weaver.agent.segment import segment
    from weaver.agent.trace_harvest import harvest
    from weaver.layout import INPUT_LAYOUT

    interest_cob = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "interest.cob"
    copybook_dir = interest_cob.parent / "copybooks"
    input_data = interest_cob.parent.parent / "data" / "accounts.dat"

    source = interest_cob.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)
    instrumented = instrument(source, paragraphs, graph, copybook_dir=copybook_dir)

    src_path = tmp_path / "interest_instrumented.cob"
    src_path.write_text(instrumented, encoding="utf-8")
    import shutil as _shutil
    _shutil.copy2(copybook_dir / "ACCOUNT-REC.cpy", tmp_path / "ACCOUNT-REC.cpy")
    proc = subprocess.run(["cobc", "-x", "interest_instrumented.cob"], cwd=tmp_path,
                           capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    binary = tmp_path / "interest_instrumented"
    fixtures = harvest(binary, tmp_path / "run", input_data, "interest.out")

    process_record_fixtures = [f for f in fixtures if f.paragraph_id == "PROCESS-RECORD"]
    assert len(process_record_fixtures) == 200  # one per input record

    ar_id_field = next(f for f in INPUT_LAYOUT if f.name == "AR-ID")
    ar_type_field = next(f for f in INPUT_LAYOUT if f.name == "AR-TYPE")
    raw_records = input_data.read_text(encoding="utf-8").splitlines()

    for i in (0, 42, 199):
        raw = raw_records[i]
        expected_id = raw[ar_id_field.offset:ar_id_field.offset + ar_id_field.width]
        expected_type = raw[ar_type_field.offset:ar_type_field.offset + ar_type_field.width]
        fx = process_record_fixtures[i]
        assert fx.record_index == i
        assert fx.input_state["AR-ID"] == expected_id
        assert fx.input_state["AR-TYPE"] == expected_type
        # WS-INTEREST is written by PROCESS-RECORD -- must actually be
        # present in the harvested output state, not just AR-* passthrough.
        assert "WS-INTEREST" in fx.output_state
