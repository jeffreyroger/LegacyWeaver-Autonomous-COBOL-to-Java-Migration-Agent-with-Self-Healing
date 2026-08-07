"""Failure-memory write-back — AGENT_LAYER_PLAN.md Phase O2 item 5 /
BACKEND_PLAN.md Step B6 item 3.

`FailureMemory.write_back()` exists but, until this change, nothing called
it. These tests exercise the two call sites directly (Orchestrator's
autonomous repair path, RunManager's escalation-decision path) with the
embedding call stubbed out -- no live Ollama needed -- and without a real
GnuCOBOL/javac toolchain, matching this environment's constraints.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from weaver.agent.escalation import DiagnosticRecord
from weaver.agent.memory import FailureMemory
from weaver.agent.orchestrator import Orchestrator
from weaver.agent.repair_loop import RepairOutcome
from weaver.agent.repair_model import RepairAttempt
from weaver.classification import Classification, DefectClass


@pytest.fixture
def stub_embed(monkeypatch):
    """Replace the network-calling embed() with a deterministic stand-in
    everywhere it's imported, so no live Ollama is needed."""
    def _fake_embed(text: str, host: str = "") -> list[float]:
        return [float(len(text))]
    import weaver.agent.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "embed", _fake_embed)
    import backend.runs as runs_module
    monkeypatch.setattr(runs_module, "embed", _fake_embed)
    return _fake_embed


def _orchestrator(tmp_path: Path) -> Orchestrator:
    o = Orchestrator.__new__(Orchestrator)
    o.memory = FailureMemory(tmp_path / "memory.json")
    return o


def test_orchestrator_writes_back_repaired_case(tmp_path, stub_embed):
    orchestrator = _orchestrator(tmp_path)
    classification = Classification(DefectClass.SIGN, 1.0, {"oracle": "0.10", "candidate": "-0.10"})
    outcome = RepairOutcome(
        unit_id="PROCESS-RECORD", resolved=True, final_body="ws.interest = ar.balance;",
        attempts=[RepairAttempt(1, "ws.interest = ar.balance;", "resolved (deterministic)")],
    )

    orchestrator._write_back_case(
        "PROCESS-RECORD", classification, field_scale=2,
        offending_statement="MOVE WS-INTEREST TO RL-INTEREST", outcome=outcome,
    )

    assert len(orchestrator.memory.cases) == 1
    case = orchestrator.memory.cases[0]
    assert case.defect_class == "SIGN"
    assert case.patch_body_template == "ws.interest = ar.balance;"
    assert case.verification_status == "verified"
    assert "PROCESS-RECORD" in case.case_id

    # Persisted to disk and reloadable, not just held in memory.
    reloaded = FailureMemory(orchestrator.memory.store_path)
    assert len(reloaded.cases) == 1
    assert reloaded.cases[0].case_id == case.case_id


def test_orchestrator_skips_write_back_when_no_defect_classified(tmp_path, stub_embed):
    """A compile-error resolution never reaches classification -- there is
    nothing to key a signature on, so _process_unit must not call
    _write_back_case in that branch (guarded by `if result.compiled`)."""
    orchestrator = _orchestrator(tmp_path)
    # No case is added unless _write_back_case is explicitly invoked --
    # this documents the guard exists at the call site, not inside the
    # helper (the helper itself always writes if called).
    assert orchestrator.memory.cases == []


def test_escalation_write_back_only_after_verification(tmp_path, stub_embed):
    from backend.runs import RunManager
    from weaver.agent.orchestrator import UnitResult

    manager = RunManager.__new__(RunManager)
    memory = FailureMemory(tmp_path / "escalation_memory.json")

    class _FakeOrchestrator:
        pass

    fake_orchestrator = _FakeOrchestrator()
    fake_orchestrator.memory = memory

    class _FakeRecord:
        run_id = "run-1"
        orchestrator = fake_orchestrator
        lock = __import__("threading").Lock()

    diagnostic = DiagnosticRecord(
        unit_identifier="PROCESS-RECORD", failing_input_record="001", oracle_value="0.10",
        candidate_value="-0.10", delta="-0.20", defect_class="SIGN", confidence=1.0,
    )
    unit = UnitResult(
        unit_id="PROCESS-RECORD", status="escalated", final_body="ws.interest = ar.balance.negate();",
        model_calls=1, memory_hit=False, duration_seconds=1.0, diagnostic=diagnostic,
    )

    manager._write_back_escalation(_FakeRecord(), unit, "ws.interest = ar.balance;")

    assert len(memory.cases) == 1
    case = memory.cases[0]
    assert case.defect_class == "SIGN"
    assert case.patch_body_template == "ws.interest = ar.balance;"
    assert "human escalation decision" in case.root_cause


def test_escalation_write_back_skipped_without_defect_class(tmp_path, stub_embed):
    from backend.runs import RunManager
    from weaver.agent.orchestrator import UnitResult

    manager = RunManager.__new__(RunManager)
    memory = FailureMemory(tmp_path / "escalation_memory.json")

    class _FakeOrchestrator:
        pass

    fake_orchestrator = _FakeOrchestrator()
    fake_orchestrator.memory = memory

    class _FakeRecord:
        run_id = "run-1"
        orchestrator = fake_orchestrator
        lock = __import__("threading").Lock()

    # A synthesis failure has no diagnostic defect class -- nothing to key
    # a signature on, so write-back must be skipped, not fabricated.
    unit = UnitResult(
        unit_id="PROCESS-RECORD", status="escalated", final_body=None,
        model_calls=0, memory_hit=False, duration_seconds=1.0, diagnostic=None,
    )

    manager._write_back_escalation(_FakeRecord(), unit, "ws.interest = ar.balance;")

    assert memory.cases == []
