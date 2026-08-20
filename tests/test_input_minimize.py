"""Phase Y1 acceptance tests (migration-framework-spec.md Section 2.2,
delta debugging / input minimization) -- weaver.agent.delta_debug.ddmin
(generic) and weaver.agent.input_minimize.minimize_divergent_records
(COBOL-specific adapter), the latter proven against a real, currently-
compiled candidate (attribution.verify_unit's own reference-plus-one-
corrupted-unit machinery -- the same real pipeline N1's own acceptance
test uses), never a fabricated result."""

import shutil
from pathlib import Path

import pytest

from weaver.agent.attribution import REFERENCE_BODY_PATH, verify_unit
from weaver.agent.delta_debug import ddmin
from weaver.agent.input_minimize import minimize_divergent_records
from weaver.agent.runspec import RunSpec


def test_ddmin_isolates_single_relevant_element():
    assert ddmin(list(range(30)), lambda xs: 17 in xs) == [17]


def test_ddmin_isolates_interacting_pair():
    result = ddmin(list(range(30)), lambda xs: len(set(xs) & {4, 21}) >= 2)
    assert set(result) == {4, 21}


def test_ddmin_handles_already_minimal_input():
    assert ddmin([5], lambda xs: True) == [5]
    assert ddmin([], lambda xs: False) == []


requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_minimize_divergent_records_against_real_compiled_candidate(tmp_path):
    spec = RunSpec.default()

    # Same deliberate corruption attribution.py's own __main__ acceptance
    # test uses: skip the dormant-record zero-out, so every dormant record
    # (not just one) gets a wrong RL-INTEREST -- multiple real divergences
    # on the same field, a genuine case for minimization rather than one
    # divergence trivially "already minimal".
    reference_body = REFERENCE_BODY_PATH.read_text(encoding="utf-8")
    corrupted = reference_body.replace(
        "ws.interest = java.math.BigDecimal.ZERO.setScale(2);",
        'ws.interest = new java.math.BigDecimal("999.99");  // deliberately wrong',
    )
    result = verify_unit("PROCESS-RECORD", corrupted, tmp_path / "attribution", spec=spec)
    assert result.compiled, result.compile_diagnostics
    assert result.build_dir is not None and result.build_dir.exists()

    divergent_indices = [d.record_index for d in result.report.divergences if d.field_name == "RL-INTEREST"]
    assert len(divergent_indices) > 1, "corruption should hit more than one dormant record"

    input_lines = spec.input_data.read_text(encoding="utf-8").splitlines()
    golden_lines = spec.golden_output.read_text(encoding="utf-8").splitlines()

    counterexample = minimize_divergent_records(
        "Scaffold", result.build_dir, input_lines, golden_lines,
        divergent_indices, "RL-INTEREST", spec.scaffold_spec.report_layout,
        tmp_path / "minimize",
        input_file_name=spec.scaffold_spec.input_file,
        output_file_name=spec.scaffold_spec.output_file,
    )

    assert len(counterexample.record_indices) == 1  # detail lines are independent -- proven-minimal is one record
    assert counterexample.record_indices[0] in divergent_indices
    assert counterexample.divergence.field_name == "RL-INTEREST"
    assert counterexample.records[0] == input_lines[counterexample.record_indices[0]]
