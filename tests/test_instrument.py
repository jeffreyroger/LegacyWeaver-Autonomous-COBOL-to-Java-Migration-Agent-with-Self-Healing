"""Source instrumentation — GRAPH_PLAN.md M4.

Derives an instrumented COBOL source variant that DISPLAYs read-set field
values at paragraph entry and write-set field values at paragraph exit,
per GRAPH_PLAN.md §4/Non-Negotiable Design Decision 1: this never touches
the oracle source that produces golden output -- `instrument()` returns a
*new* source string; the caller is responsible for compiling it to a
separately named binary (M5's job, and requires cobc, unavailable in this
environment -- see the compilation test at the bottom, skipped here).

Practical simplification versus GRAPH_PLAN.md's literal wording ("given a
ProgramModel + ProgramGraph"): only paragraph boundaries (segment()'s
Paragraph list) and read/write sets (ProgramGraph) are actually needed to
splice DISPLAY statements at paragraph entry/exit -- ProgramModel's other
fields (layouts, output filename, ...) are irrelevant to this transform,
so instrument() takes paragraphs + graph directly rather than a full
ProgramModel, keeping it independently testable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weaver.agent.graph import from_paragraphs
from weaver.agent.instrument import TRACE_PREFIX, instrument
from weaver.agent.segment import segment

INTEREST_COB = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "interest.cob"

requires_cobc = pytest.mark.skipif(shutil.which("cobc") is None, reason="requires GnuCOBOL (cobc) on PATH")


def test_instrument_injects_entry_display_for_reads_right_after_the_header():
    source = "       IDENTIFICATION DIVISION.\n       PROCEDURE DIVISION.\n       P.\n           MOVE AR-ID TO RL-ID.\n"
    paragraphs = segment(source)
    graph = from_paragraphs("TEST", paragraphs)

    result = instrument(source, paragraphs, graph)
    lines = result.splitlines()

    header_idx = next(i for i, l in enumerate(lines) if l.strip() == "P.")
    assert f'{TRACE_PREFIX}P:ENTRY:AR-ID=" AR-ID' in lines[header_idx + 1]


def test_instrument_injects_exit_display_for_writes_after_the_paragraph_body():
    source = "       IDENTIFICATION DIVISION.\n       PROCEDURE DIVISION.\n       P.\n           MOVE AR-ID TO RL-ID.\n"
    paragraphs = segment(source)
    graph = from_paragraphs("TEST", paragraphs)

    result = instrument(source, paragraphs, graph)

    assert f'{TRACE_PREFIX}P:EXIT:RL-ID=" RL-ID' in result


def test_instrument_preserves_original_statements_unmodified():
    """The instrumented source must be strictly additive -- every original
    line still appears, in its original relative order."""
    source = (
        "       IDENTIFICATION DIVISION.\n       PROCEDURE DIVISION.\n"
        "       P.\n           MOVE AR-ID TO RL-ID.\n"
        "       Q.\n           MOVE X TO Y.\n"
    )
    paragraphs = segment(source)
    graph = from_paragraphs("TEST", paragraphs)

    result_lines = instrument(source, paragraphs, graph).splitlines()
    original_lines = [l for l in source.splitlines() if l.strip()]

    filtered_result = [l for l in result_lines if l.strip()]
    # original lines must appear as a subsequence of the instrumented output
    it = iter(filtered_result)
    assert all(any(candidate == line for candidate in it) for line in original_lines)


def test_instrument_emits_no_display_for_a_paragraph_with_empty_read_write_sets():
    source = "       IDENTIFICATION DIVISION.\n       PROCEDURE DIVISION.\n       P.\n           PERFORM Q.\n       Q.\n           MOVE X TO Y.\n"
    paragraphs = segment(source)
    graph = from_paragraphs("TEST", paragraphs)

    result = instrument(source, paragraphs, graph)

    # P's own read/write set (MOVE/ADD/COMPUTE/IF/EVALUATE scope, M2) is
    # empty -- PERFORM is callgraph.py's concern, not a field access -- so
    # no DISPLAY should be emitted for P at all.
    assert f"{TRACE_PREFIX}P:" not in result


def _reconstructed_literals(result: str) -> str:
    """Join DISPLAY lines/continuations back into single logical strings,
    ignoring COBOL's column-72 physical line breaks -- assertions below
    check semantic content, not physical line layout."""
    joined = []
    for line in result.splitlines():
        stripped = line.strip()
        if stripped.startswith("DISPLAY") or (len(line) > 6 and line[6] == "-"):
            joined.append(stripped.lstrip("-"))
    return " ".join(joined)


def test_real_fixture_interest_cob_instruments_process_record():
    source = INTEREST_COB.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)

    result = instrument(source, paragraphs, graph)
    reconstructed = _reconstructed_literals(result)

    assert f"{TRACE_PREFIX}PROCESS-RECORD:ENTRY:AR-BALANCE=" in reconstructed
    assert f"{TRACE_PREFIX}PROCESS-RECORD:EXIT:RL-INTEREST=" in reconstructed


def test_no_physical_line_exceeds_the_fixed_format_column_limit():
    """The bug actually found by compiling under real GnuCOBOL (this
    environment has no cobc, so it was previously invisible): a long
    paragraph/field name pushed a DISPLAY line past column 72, which
    fixed-format COBOL silently truncates rather than erroring on --
    dropping the closing quote and corrupting every line after it."""
    source = INTEREST_COB.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)

    result = instrument(source, paragraphs, graph)

    # Comment lines (indicator column '*') are exempt from the 72-column
    # code limit and can legitimately run longer -- interest.cob's own
    # header comments already do. Only code lines matter here.
    code_lines = [l for l in result.splitlines() if not (len(l) > 6 and l[6] == "*")]
    assert all(len(line) <= 72 for line in code_lines), [l for l in code_lines if len(l) > 72]


def test_condition_name_declared_in_a_copybook_is_still_excluded():
    """AR-PREMIUM and AR-IS-DORMANT are declared inside ACCOUNT-REC.cpy,
    not inline in interest.cob -- found by actually compiling under
    GnuCOBOL, which rejected `DISPLAY AR-PREMIUM` ('condition-name not
    allowed here') because the first pass only scanned interest.cob's own
    text and never saw the copybook's 88-levels at all."""
    source = INTEREST_COB.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)
    copybook_dir = INTEREST_COB.parent / "copybooks"

    result = instrument(source, paragraphs, graph, copybook_dir=copybook_dir)

    assert f"{TRACE_PREFIX}PROCESS-RECORD:ENTRY:AR-PREMIUM=" not in result
    assert f"{TRACE_PREFIX}PROCESS-RECORD:ENTRY:AR-IS-DORMANT=" not in result
    # AR-TYPE (AR-PREMIUM's parent field) is a real data item and stays.
    assert f"{TRACE_PREFIX}PROCESS-RECORD:ENTRY:AR-TYPE=" in result


@requires_cobc
def test_instrumented_interest_cob_still_compiles(tmp_path):
    """The one check that actually needs GnuCOBOL. This is the honest
    boundary GRAPH_PLAN.md's M4 exit criterion draws: 'instrumented
    variant compiles under GnuCOBOL 3.x'."""
    import shutil as _shutil
    import subprocess

    source = INTEREST_COB.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)
    copybook_dir = INTEREST_COB.parent / "copybooks"
    instrumented = instrument(source, paragraphs, graph, copybook_dir=copybook_dir)

    copybook = copybook_dir / "ACCOUNT-REC.cpy"
    _shutil.copy2(copybook, tmp_path / copybook.name)

    src_path = tmp_path / "interest_instrumented.cob"
    src_path.write_text(instrumented, encoding="utf-8")
    proc = subprocess.run(["cobc", "-x", str(src_path)], cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
