"""weaver/agent/result_view.py -- the shared UnitResult/SubprogramUnitResult
normalizer added for multi-program (leaf-first) backend/CLI runs
(2026-08-26). Pure functions, no toolchain needed.
"""

from __future__ import annotations

import json

from weaver.agent.escalation import DiagnosticRecord
from weaver.agent.orchestrator import UnitResult
from weaver.agent.result_view import (
    all_committed,
    composite_id,
    divergence_source,
    normalize_divergence_report,
    normalize_program_results,
    normalize_unit_result,
    result_kind,
    split_composite,
)
from weaver.agent.subprogram_orchestrator import SubprogramUnitResult
from weaver.agent.subprogram_verify import SubprogramDivergence, SubprogramVerifyResult
from weaver.report import Report


def test_composite_id_round_trips():
    cid = composite_id("ROOT", "PROCESS-RECORD")
    assert cid == "ROOT::PROCESS-RECORD"
    assert split_composite(cid) == ("ROOT", "PROCESS-RECORD")


def test_composite_id_is_bare_unit_id_when_no_program():
    assert composite_id(None, "PROCESS-RECORD") == "PROCESS-RECORD"
    assert composite_id("", "PROCESS-RECORD") == "PROCESS-RECORD"
    assert split_composite("PROCESS-RECORD") == (None, "PROCESS-RECORD")


def test_normalize_unit_result_file_based():
    result = UnitResult(
        unit_id="PROCESS-RECORD", status="committed", final_body="ws.x = 1;",
        model_calls=2, memory_hit=True, duration_seconds=1.5,
    )
    d = normalize_unit_result(result, program_name="ROOT")
    assert d["unit_id"] == "PROCESS-RECORD"
    assert d["composite_id"] == "ROOT::PROCESS-RECORD"
    assert d["program"] == "ROOT"
    assert d["kind"] == "file_based"
    assert d["status"] == "committed"
    assert d["memory_hit"] is True
    assert d["diagnostic"] is None
    assert d["escalation_reason"] is None
    assert result_kind(result) == "file_based"


def test_normalize_unit_result_subprogram_renders_absent_fields_honestly():
    result = SubprogramUnitResult(
        program_id="BILLING", status="committed", final_body="return x;",
        model_calls=1, duration_seconds=0.9,
    )
    d = normalize_unit_result(result, program_name="BILLING")
    assert d["unit_id"] == "BILLING"
    assert d["composite_id"] == "BILLING::BILLING"
    assert d["kind"] == "subprogram"
    # A subprogram unit has no memory/diagnostic concept at all -- never a
    # fabricated True/record, always the honest empty value.
    assert d["memory_hit"] is False
    assert d["diagnostic"] is None
    assert result_kind(result) == "subprogram"


def test_normalize_unit_result_preserves_a_real_diagnostic():
    diag = DiagnosticRecord(
        unit_identifier="PROCESS-RECORD", failing_input_record="x",
        oracle_value="1.23", candidate_value="1.24", delta="0.01",
        defect_class="SCALE", confidence=0.9,
    )
    result = UnitResult(
        unit_id="PROCESS-RECORD", status="escalated", final_body=None,
        model_calls=3, memory_hit=False, duration_seconds=2.0, diagnostic=diag,
    )
    d = normalize_unit_result(result)
    assert d["diagnostic"]["defect_class"] == "SCALE"


def test_normalize_program_results_flattens_with_composite_keys():
    program_results = {
        "LEAF-A": {"LEAF-A": SubprogramUnitResult(
            program_id="LEAF-A", status="committed", final_body="x", model_calls=1, duration_seconds=0.1,
        )},
        "ROOT": {"PROCESS-RECORD": UnitResult(
            unit_id="PROCESS-RECORD", status="committed", final_body="x",
            model_calls=1, memory_hit=False, duration_seconds=0.1,
        )},
    }
    flat = normalize_program_results(program_results)
    assert set(flat) == {"LEAF-A::LEAF-A", "ROOT::PROCESS-RECORD"}
    assert flat["ROOT::PROCESS-RECORD"]["program"] == "ROOT"


def test_all_committed_true_only_when_every_unit_of_every_program_committed():
    committed_result = UnitResult(unit_id="U", status="committed", final_body="x",
                                   model_calls=1, memory_hit=False, duration_seconds=0.1)
    escalated_result = UnitResult(unit_id="U", status="escalated", final_body=None,
                                   model_calls=1, memory_hit=False, duration_seconds=0.1)

    assert all_committed({"A": {"U": committed_result}, "B": {"U": committed_result}}) is True
    assert all_committed({"A": {"U": committed_result}, "B": {"U": escalated_result}}) is False
    assert all_committed({}) is False  # nothing to have verified is not a success


def test_normalize_divergence_report_file_based_passes_report_json_through():
    report = Report(unit_id="Scaffold", total_records=3, exit_codes_match=True)
    d = normalize_divergence_report(report)
    assert d["kind"] == "file_based"
    assert d["total_records"] == 3
    # Byte-identical to Report.to_json() plus the kind tag -- never reshaped.
    reparsed = json.loads(report.to_json())
    reparsed["kind"] = "file_based"
    assert d == reparsed


def test_normalize_divergence_report_subprogram_uses_witness_shape():
    result = SubprogramVerifyResult(
        compiled=True,
        divergences=(SubprogramDivergence(witness_input=1, oracle_output=2, candidate_output=3),),
    )
    d = normalize_divergence_report(result)
    assert d["kind"] == "subprogram"
    assert d["divergence_count"] == 1
    assert d["divergences"][0] == {"witness_input": 1, "oracle_output": 2, "candidate_output": 3}


def test_normalize_divergence_report_none_is_none():
    assert normalize_divergence_report(None) is None


def test_divergence_source_prefers_last_report_falls_back_to_verify_result():
    report = Report(unit_id="Scaffold", total_records=1, exit_codes_match=True)
    file_based = UnitResult(unit_id="U", status="committed", final_body="x",
                             model_calls=1, memory_hit=False, duration_seconds=0.1, last_report=report)
    assert divergence_source(file_based) is report

    verify_result = SubprogramVerifyResult(compiled=True)
    subprogram = SubprogramUnitResult(program_id="P", status="committed", final_body="x",
                                       model_calls=1, duration_seconds=0.1, verify_result=verify_result)
    assert divergence_source(subprogram) is verify_result

    none_yet = UnitResult(unit_id="U", status="escalated", final_body=None,
                           model_calls=1, memory_hit=False, duration_seconds=0.1)
    assert divergence_source(none_yet) is None
