"""Phase Z1 acceptance tests (migration-framework-spec.md Section 2.1
Dynamic Mocking, Section 2.2's three-axis Parity Gate) -- real cobc/javac
compile, real run, over fixtures/cobol/mocked/billing.cob's one EXEC SQL
directive."""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from weaver.agent.mock_generator import default_mock_map, rewrite_cobol_source
from weaver.agent.mocked_verify import verify_mocked_subprogram
from weaver.cobol.mock_directives import UnsupportedMockDirectiveError, find_mock_directives
from weaver.cobol.subprogram import load_subprogram

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "mocked" / "billing.cob"

_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"
requires_full_stack = pytest.mark.skipif(
    not _have_cobc or shutil.which("javac") is None,
    reason="requires cobc (native or WEAVER_COBC_VIA_WSL=1) and javac on PATH",
)


def test_find_mock_directives_parses_the_real_fixture():
    model = load_subprogram(FIXTURE)
    directives = find_mock_directives(FIXTURE.read_text(encoding="utf-8"))
    assert len(directives) == 1
    assert directives[0].kind == "SQL"
    assert directives[0].verb == "SELECT"
    assert directives[0].signature == "SQL:SELECT:BL-ID-BL-TOTAL"


def test_unsupported_exec_kind_raises():
    source = "       MAIN-PARA.\n           EXEC DLI GU END-EXEC.\n"
    with pytest.raises(UnsupportedMockDirectiveError):
        find_mock_directives(source)


def test_mock_map_is_deterministic_across_calls():
    model = load_subprogram(FIXTURE)
    directives = find_mock_directives(FIXTURE.read_text(encoding="utf-8"))
    m1 = default_mock_map(directives)
    m2 = default_mock_map(directives)
    assert m1 == m2


def test_rewrite_replaces_exec_block_with_move_and_display():
    model = load_subprogram(FIXTURE)
    directives = find_mock_directives(FIXTURE.read_text(encoding="utf-8"))
    mock_map = default_mock_map(directives)
    full_source = FIXTURE.read_text(encoding="utf-8")
    rewritten = rewrite_cobol_source(full_source, directives, mock_map, paragraph_names=["MAIN-PARA"])
    procedure_division = rewritten.split("PROCEDURE DIVISION", 1)[1]
    assert "EXEC SQL" not in procedure_division
    assert "END-EXEC" not in procedure_division
    assert 'DISPLAY "STUB:SQL:SELECT:BL-ID-BL-TOTAL"' in rewritten
    assert 'DISPLAY "PARA:MAIN-PARA"' in rewritten


@requires_full_stack
def test_correct_candidate_matches_all_three_axes(tmp_path):
    model = load_subprogram(FIXTURE)
    correct_body = '        return WeaverMockRuntime.call("SQL:SELECT:BL-ID-BL-TOTAL");'
    result = verify_mocked_subprogram(model, correct_body, Decimal("123.45"), tmp_path)

    assert result.compiled, result.compile_error
    assert result.terminal_state_match
    assert result.paragraphs_hit_divergence is None
    assert result.stub_log_divergence is None
    assert result.all_axes_match
    assert "SQL:SELECT:BL-ID-BL-TOTAL" in result.oracle_trace[0] or any(
        "STUB:" in line for line in result.oracle_trace
    )


@requires_full_stack
def test_wrong_stub_call_flags_stub_log_divergence(tmp_path):
    model = load_subprogram(FIXTURE)
    # Candidate never calls the mock at all -- wrong terminal state AND a
    # real stub-log divergence (oracle has one STUB: line, candidate none).
    wrong_body = "        return java.math.BigDecimal.ZERO;"
    result = verify_mocked_subprogram(model, wrong_body, Decimal("123.45"), tmp_path)

    assert result.compiled, result.compile_error
    assert not result.terminal_state_match
    assert result.stub_log_divergence is not None
    assert result.stub_log_divergence.oracle_call == "SQL:SELECT:BL-ID-BL-TOTAL"
    assert result.stub_log_divergence.candidate_call is None


@requires_full_stack
def test_wrong_paragraph_trace_flags_paragraphs_hit_divergence(tmp_path):
    model = load_subprogram(FIXTURE)
    correct_body = '        return WeaverMockRuntime.call("SQL:SELECT:BL-ID-BL-TOTAL");'
    result = verify_mocked_subprogram(model, correct_body, Decimal("123.45"), tmp_path)
    assert result.paragraphs_hit_divergence is None  # sanity: matches when both sides trace MAIN-PARA

    from weaver.agent.parity_axes import compare_paragraphs_hit
    divergence = compare_paragraphs_hit(list(result.oracle_trace), ["PARA:SOME-OTHER-PARA"])
    assert divergence is not None
    assert divergence.only_in_oracle == ("MAIN-PARA",)
    assert divergence.only_in_candidate == ("SOME-OTHER-PARA",)
