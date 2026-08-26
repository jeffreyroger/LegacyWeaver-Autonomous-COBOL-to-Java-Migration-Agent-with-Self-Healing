"""Multi-program (leaf-first DAG) backend dispatch, added 2026-08-26.

Companion to tests/test_backend_service.py's single-program suite -- same
stand-in-orchestrator approach (no real cobc/javac needed), but exercising
RunManager's LeafOrchestrator branch: directory-vs-file request
validation, the `programs` key on GET /runs/{id}, the two nested
units/code and divergences routes, and the disclosed resume/escalation
gaps for a multi-program run (CLAUDE.md rule 12).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
import backend.runs as runs_module
from backend.app import app
from backend.runs import RunManager
from weaver.agent.orchestrator import UnitResult
from weaver.agent.runspec import RunSpec
from weaver.report import Report

FAKE_PROGRAM_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FAKE-FILE ASSIGN TO "fake.dat".
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNIT-A.
       UNIT-A.
           STOP RUN.
"""


@dataclass
class FakeLeafOrchestrator:
    program_dir: Path
    base_spec: RunSpec
    orchestrator_factory: object = None
    work_root: Path = None
    run_dir: Path = None
    on_event: object = None
    cancel_requested: threading.Event | None = None
    results_lock: threading.Lock | None = None
    resume_committed: dict | None = None
    program_results: dict = field(default_factory=dict, init=False)

    # Set per-test before POSTing the run, so unit_code's
    # resolve_source_file() has a real file to read.
    source_path: Path | None = None
    # Set per-test to make run() produce an escalated unit instead of a
    # committed one, and/or a subprogram-shaped result instead of a
    # file-based one -- exercises _decide_escalation_multi_program's two
    # kind branches without a real cobc/javac round trip.
    escalate: bool = False
    kind: str = "file_based"  # "file_based" | "subprogram"

    def run(self):
        status = "escalated" if FakeLeafOrchestrator.escalate else "committed"
        if FakeLeafOrchestrator.kind == "subprogram":
            from weaver.agent.subprogram_orchestrator import SubprogramUnitResult

            result = SubprogramUnitResult(program_id="UNIT-A", status=status, final_body="// ok",
                                           model_calls=1, duration_seconds=0.1)
        else:
            report = Report(unit_id="Scaffold", total_records=1, exit_codes_match=True)
            result = UnitResult(unit_id="UNIT-A", status=status, final_body="// ok",
                                 model_calls=1, memory_hit=False, duration_seconds=0.1,
                                 last_report=report if status == "committed" else None)
        self.program_results["PROGA"] = {"UNIT-A": result}
        if self.on_event is not None:
            self.on_event({"program": "PROGA", "composite_id": "PROGA::UNIT-A", "unit": "UNIT-A",
                            "node": "commit", "action": "accept", "duration_seconds": 0.1, "outcome": "ok"})
        return self.program_results

    def resolve_source_file(self, program_name: str) -> Path:
        return FakeLeafOrchestrator.source_path

    def _persist_state(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _patch_orchestrator(monkeypatch, tmp_path):
    FakeLeafOrchestrator.escalate = False
    FakeLeafOrchestrator.kind = "file_based"
    monkeypatch.setattr(runs_module, "LeafOrchestrator", FakeLeafOrchestrator)
    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(app_module, "_check_toolchain", lambda: (True, "ok"))
    manager = runs_module.RunManager()
    monkeypatch.setattr(app_module, "run_manager", manager)
    yield
    for record in list(manager._runs.values()):
        thread = getattr(record, "thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
            assert not thread.is_alive(), f"run {record.run_id} did not finish"


@pytest.fixture
def client():
    return TestClient(app)


def _wait_terminal(client, run_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/runs/{run_id}").json()
        if state["lifecycle"] in {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}:
            return state
        time.sleep(0.02)
    raise TimeoutError(f"run {run_id} did not reach a terminal state within {timeout}s")


def _leaf_first_payload(program_dir: Path, **overrides) -> dict:
    payload = dict(cobol_source=str(program_dir), data_file="fixtures/data/multiprog/accounts.dat",
                    leaf_first=True, seed=1, model_name="m", model_digest="d")
    payload.update(overrides)
    return payload


def test_leaf_first_requires_a_directory_not_a_file(client):
    resp = client.post("/runs", json=_leaf_first_payload(Path("fixtures/cobol/interest.cob")))
    assert resp.status_code == 400
    assert resp.json()["error_class"] == "INVALID_REQUEST"


def test_a_directory_source_requires_leaf_first_true(client, tmp_path):
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    resp = client.post("/runs", json=dict(
        cobol_source=str(program_dir), data_file="fixtures/data/multiprog/accounts.dat", leaf_first=False,
    ))
    assert resp.status_code == 400
    assert resp.json()["error_class"] == "INVALID_REQUEST"


def test_leaf_first_run_completes_with_a_programs_key(client, tmp_path):
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    resp = client.post("/runs", json=_leaf_first_payload(program_dir))
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    state = _wait_terminal(client, run_id)
    assert state["lifecycle"] == "COMPLETED"
    assert {u["composite_id"] for u in state["units"]} == {"PROGA::UNIT-A"}

    assert state["programs"] is not None
    assert len(state["programs"]) == 1
    assert state["programs"][0]["program"] == "PROGA"
    assert state["programs"][0]["committed_count"] == 1
    assert state["programs"][0]["units"][0]["unit_id"] == "UNIT-A"


def test_single_program_run_still_has_programs_null(client):
    """The single-program path (backend.runs.Orchestrator, unaffected by
    this change) must keep programs: null -- an existing client reading
    only `units` sees no new required field."""
    resp = client.post("/runs", json=dict(
        cobol_source="fixtures/cobol/interest.cob", data_file="fixtures/data/interest.dat",
        seed=1, model_name="m", model_digest="d",
    ))
    run_id = resp.json()["run_id"]
    state = client.get(f"/runs/{run_id}").json()
    assert state["programs"] is None


def test_nested_unit_code_route(client, tmp_path):
    source_path = tmp_path / "proga.cob"
    source_path.write_text(FAKE_PROGRAM_SOURCE, encoding="utf-8")
    FakeLeafOrchestrator.source_path = source_path

    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.get(f"/runs/{run_id}/programs/PROGA/units/UNIT-A/code")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cobol"]["source_path"] == str(source_path)
    assert "UNIT-A" in body["cobol"]["text"]
    assert body["java"]["body"] == "// ok"


def test_nested_divergences_route(client, tmp_path):
    source_path = tmp_path / "proga.cob"
    source_path.write_text(FAKE_PROGRAM_SOURCE, encoding="utf-8")
    FakeLeafOrchestrator.source_path = source_path

    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.get(f"/runs/{run_id}/programs/PROGA/divergences/UNIT-A")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "file_based"
    assert body["total_records"] == 1


def test_flat_units_route_404s_for_a_multi_program_unit_without_a_program(client, tmp_path):
    """The bare, single-program /units/{unit_id}/code route has no
    program dimension -- for a multi-program run it must not silently
    guess which program UNIT-A belongs to."""
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.get(f"/runs/{run_id}/units/UNIT-A/code")
    assert resp.status_code == 404


def test_resume_requires_the_interrupted_lifecycle_for_a_leaf_first_run(client, tmp_path):
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)  # COMPLETED, not INTERRUPTED

    resp = client.post(f"/runs/{run_id}/resume")
    assert resp.status_code == 400
    assert resp.json()["error_class"] == "INVALID_REQUEST"


def test_resume_skips_an_already_committed_program(client, tmp_path):
    """DAG-level resume (2026-08-26): a program whose every unit already
    committed in the interrupted attempt is adopted as-is, never re-run --
    reflected here as FakeLeafOrchestrator.run() being invoked a second
    time (real dispatch would skip constructing a fresh nested Orchestrator
    for PROGA entirely; this fake's run() is the outer LeafOrchestrator
    itself, so the real skip-vs-rerun distinction is covered at the agent
    level by tests/test_leaf_orchestrator_backend_hooks.py -- this test's
    job is only to prove the backend WIRES resume through instead of
    rejecting it)."""
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    record = app_module.run_manager.get_run(run_id)
    record.lifecycle = "INTERRUPTED"

    resp = client.post(f"/runs/{run_id}/resume")
    assert resp.status_code == 200
    state = _wait_terminal(client, run_id)
    assert state["lifecycle"] == "COMPLETED"
    assert {u["composite_id"] for u in state["units"]} == {"PROGA::UNIT-A"}


def test_flat_escalation_route_is_ambiguous_for_a_multi_program_run(client, tmp_path):
    """The bare /escalations/{unit_id}/decision route has no program
    dimension -- for a multi-program run it must refuse rather than guess
    which program's UNIT-A is meant (real escalation decisions for a
    multi-program run use the nested route below)."""
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.post(f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"})
    assert resp.status_code == 400
    assert resp.json()["error_class"] == "INVALID_REQUEST"


def test_nested_escalation_reject_does_not_reverify(client, tmp_path):
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    FakeLeafOrchestrator.escalate = True
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.post(f"/runs/{run_id}/programs/PROGA/escalations/UNIT-A/decision",
                        json={"decision": "reject"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"unit_id": "UNIT-A", "program": "PROGA", "decision": "reject",
                     "verified": False, "committed": False}


def test_nested_escalation_accept_commits_a_verified_file_based_unit(client, tmp_path, monkeypatch):
    source_path = tmp_path / "proga.cob"
    source_path.write_text(FAKE_PROGRAM_SOURCE, encoding="utf-8")
    FakeLeafOrchestrator.source_path = source_path
    FakeLeafOrchestrator.escalate = True
    FakeLeafOrchestrator.kind = "file_based"

    from weaver.agent.attribution import AttributionResult

    def fake_verify_unit(unit_id, candidate_body, work_dir, *, spec=None):
        report = Report(unit_id=unit_id, total_records=1, exit_codes_match=True)
        return AttributionResult(unit_id=unit_id, report=report, classifications=[],
                                  compiled=True, compile_diagnostics=None)

    monkeypatch.setattr(runs_module, "verify_unit", fake_verify_unit)
    monkeypatch.setattr(runs_module, "program_profile", lambda *a, **k: None)

    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.post(f"/runs/{run_id}/programs/PROGA/escalations/UNIT-A/decision",
                        json={"decision": "accept"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True
    assert body["committed"] is True
    assert body["divergence_count"] == 0

    record = app_module.run_manager.get_run(run_id)
    assert record.orchestrator.program_results["PROGA"]["UNIT-A"].status == "committed"


def test_nested_escalation_accept_reverifies_a_subprogram_unit_via_verify_subprogram(client, tmp_path, monkeypatch):
    """A subprogram-shaped escalated unit is re-verified through
    verify_subprogram (the real oracle-vs-candidate parity check), not
    verify_unit -- the whole point of Step B10's kind branch."""
    source_path = tmp_path / "leaf_a.cob"
    source_path.write_text(
        Path("fixtures/cobol/multiprog/leaf_a.cob").read_text(encoding="utf-8"), encoding="utf-8",
    )
    FakeLeafOrchestrator.source_path = source_path
    FakeLeafOrchestrator.escalate = True
    FakeLeafOrchestrator.kind = "subprogram"

    from weaver.agent.subprogram_verify import SubprogramVerifyResult

    calls = []

    def fake_verify_subprogram(model, candidate_body, witnesses, work_dir):
        calls.append((model.program_id, candidate_body, list(witnesses)))
        return SubprogramVerifyResult(compiled=True, divergences=())

    monkeypatch.setattr("weaver.agent.subprogram_verify.verify_subprogram", fake_verify_subprogram)

    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.post(f"/runs/{run_id}/programs/PROGA/escalations/UNIT-A/decision",
                        json={"decision": "accept"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True
    assert body["divergence_count"] == 0
    assert len(calls) == 1
    assert calls[0][0] == "LEAF-A"

    record = app_module.run_manager.get_run(run_id)
    assert record.orchestrator.program_results["PROGA"]["UNIT-A"].status == "committed"


def test_nested_escalation_rejects_a_non_escalated_unit(client, tmp_path):
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_id = client.post("/runs", json=_leaf_first_payload(program_dir)).json()["run_id"]
    _wait_terminal(client, run_id)  # committed, not escalated

    resp = client.post(f"/runs/{run_id}/programs/PROGA/escalations/UNIT-A/decision",
                        json={"decision": "accept"})
    assert resp.status_code == 400
    assert resp.json()["error_class"] == "INVALID_REQUEST"
