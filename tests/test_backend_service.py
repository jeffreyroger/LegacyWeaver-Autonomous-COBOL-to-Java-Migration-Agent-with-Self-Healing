"""BACKEND_PLAN.md Part VII conformance tests reachable without the
GnuCOBOL/Docker toolchain this environment lacks (`cobc` is not
installed here). These exercise the transport/lifecycle layer itself --
lifecycle states, the error contract, SSE forwarding, cancellation,
escalation verification, and the DC-5 metrics identity -- against a
stand-in Orchestrator so the test suite does not depend on toolchain
availability. A full offline migration run (§7.2) still requires a real
environment with cobc/javac/Docker and is NOT exercised here; that gap
is disclosed, not hidden (CLAUDE.md rule 12).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from weaver.atomic_json import write_json_atomic
import backend.runs as runs_module
from backend.app import app
from backend.runs import RunManager
from weaver.agent.orchestrator import UnitResult
from weaver.agent.runspec import RunSpec

# Captured before the autouse fixture below monkeypatches _check_toolchain
# for every test in this file -- the version-detection tests need the real
# implementation, not the transport-layer stand-in.
_real_check_toolchain = app_module._check_toolchain


@dataclass
class FakeOrchestrator:
    spec: RunSpec
    trace_path: Path
    state_path: Path
    on_event: object = None
    cancel_requested: threading.Event | None = None
    fresh_trace: bool = True
    results_lock: threading.Lock | None = None
    results: dict = field(default_factory=dict)

    def __post_init__(self):
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_path.write_text("")

    def _emit(self, unit_id, node, action, duration, **kw):
        event = {"timestamp": time.time(), "unit": unit_id, "node": node, "action": action,
                  "duration_seconds": duration, **kw}
        with self.trace_path.open("a") as f:
            f.write(json.dumps(event) + "\n")
        if self.on_event:
            self.on_event(event)

    def run(self):
        self._emit("*", "plan", "select_units", 0.0, outcome="units=['UNIT-A', 'UNIT-B']")
        for unit_id in ("UNIT-A", "UNIT-B"):
            if self.cancel_requested is not None and self.cancel_requested.is_set():
                self._emit("*", "cancel", "stop_before_unit", 0.0, outcome=f"stopped before {unit_id}")
                break
            self._emit(unit_id, "commit", "accept", 0.01, outcome="verified clean")
            self.results[unit_id] = UnitResult(unit_id, "committed", "body", 0, False, 0.01)
            self._persist_state()
        return self.results

    def _persist_state(self):
        from dataclasses import asdict
        # Atomic, like the real Orchestrator: a non-atomic write here is
        # read mid-write by GET /runs/{id} and fails to parse (this is what
        # made this suite flaky before 2026-08-12).
        write_json_atomic(self.state_path, {k: asdict(v) for k, v in self.results.items()})


@pytest.fixture(autouse=True)
def _patch_orchestrator(monkeypatch, tmp_path):
    monkeypatch.setattr(runs_module, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    # This file exercises the transport/lifecycle layer with a stand-in
    # Orchestrator, independent of whether a real GnuCOBOL toolchain is
    # present (see module docstring). The toolchain gate itself (added for
    # the OI-3 version-detection fix) is exercised separately below.
    monkeypatch.setattr(app_module, "_check_toolchain", lambda: (True, "ok"))

    # Each test gets its own RunManager. `backend.app.run_manager` is a
    # process-wide singleton that (a) serialises every run behind
    # `_active_lock` and (b) accumulates records in `_runs` forever. Shared
    # across tests that both start background threads, it produced two
    # distinct flakes: a run still holding the lock from an earlier test
    # made a later test's `_wait_terminal` time out (which test lost the
    # race varied run to run), and `GET /runs` saw other tests' records.
    # Constructed after RUNS_ROOT is patched -- __init__ scans it.
    manager = runs_module.RunManager()
    monkeypatch.setattr(app_module, "run_manager", manager)

    yield

    # Never leave a worker running into the next test: it would take
    # `_active_lock` on a manager that test is not expecting to be busy.
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
    raise TimeoutError(
        f"run {run_id} did not reach a terminal state within {timeout}s "
        f"(last lifecycle: {state.get('lifecycle')!r})"
    )


def _create_payload(**overrides):
    payload = dict(
        cobol_source="fixtures/cobol/interest.cob", data_file="fixtures/data/interest.dat",
        seed=1, model_name="m", model_digest="d",
    )
    payload.update(overrides)
    return payload


def test_health_binds_loopback(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["bind_host"] == "127.0.0.1"


def test_create_run_echoes_all_determinism_parameters(client):
    payload = _create_payload(seed=42, model_digest="sha256:abc")
    resp = client.post("/runs", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["seed"] == 42
    assert body["model_digest"] == "sha256:abc"
    assert "run_id" in body


def test_run_not_found_is_typed_404(client):
    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error_class"] == "RUN_NOT_FOUND"


def test_run_completes_and_event_stream_matches_trace_file(client):
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    state = _wait_terminal(client, run_id)
    assert state["lifecycle"] == "COMPLETED"
    assert {u["unit_id"] for u in state["units"]} == {"UNIT-A", "UNIT-B"}

    record = runs_module_run_manager_record(run_id)
    trace_lines = [json.loads(l) for l in record.trace_path.read_text().splitlines() if l.strip()]
    assert len(trace_lines) >= 3  # plan + 2 commits


def runs_module_run_manager_record(run_id):
    from backend.app import run_manager
    return run_manager.get_run(run_id)


def test_cancellation_stops_at_unit_boundary(client):
    # Cancel immediately; the fake worker checks cancel between units, so
    # a synchronous request/cancel race can still let it finish -- assert
    # only that cancellation is accepted and reflected, never a 500.
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    cancel_resp = client.post(f"/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200
    state = _wait_terminal(client, run_id)
    assert state["lifecycle"] in {"CANCELLED", "COMPLETED"}


def test_metrics_endpoint_matches_compute_metrics_directly(client):
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    state = _wait_terminal(client, run_id)
    api_metrics = state["metrics"]

    from weaver.agent.metrics import compute_metrics
    import dataclasses
    record = runs_module_run_manager_record(run_id)
    direct_metrics = dataclasses.asdict(compute_metrics(record.trace_path, record.state_path,
                                                          record.run_dir / "m4_baseline.json"))
    assert api_metrics == direct_metrics


def test_escalation_decision_on_non_escalated_unit_is_rejected(client):
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)
    decision_resp = client.post(
        f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"}
    )
    # UNIT-A committed cleanly in the fake run -- it is not escalated, so
    # the API must refuse rather than silently no-op.
    assert decision_resp.status_code == 400
    assert decision_resp.json()["error_class"] == "INVALID_REQUEST"


def test_get_run_includes_diagnostic_for_escalated_unit(client, monkeypatch):
    """Gap 2: the escalation card needs defect class/delta/confidence/
    attempts before a human decides accept/reject/body."""
    from weaver.agent.escalation import DiagnosticRecord

    @dataclass
    class FakeOrchestratorEscalates(FakeOrchestrator):
        def run(self):
            self._emit("*", "plan", "select_units", 0.0, outcome="units=['UNIT-A']")
            diag = DiagnosticRecord(
                unit_identifier="UNIT-A", failing_input_record="rec", oracle_value="1.00",
                candidate_value="2.00", delta="1.00", defect_class="TRUNCATION", confidence=0.9,
                attempts=[{"attempt": 1, "patch_summary": "x", "why_it_failed": "y"}],
                assumptions=["a"], suspected_source_lines="1-2", decision_requested="accept?",
            )
            self.results["UNIT-A"] = UnitResult("UNIT-A", "escalated", None, 1, False, 0.02, diag)
            self._persist_state()
            return self.results

    monkeypatch.setattr(runs_module, "Orchestrator", FakeOrchestratorEscalates)
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    state = _wait_terminal(client, run_id)

    unit = next(u for u in state["units"] if u["unit_id"] == "UNIT-A")
    assert unit["diagnostic"]["defect_class"] == "TRUNCATION"
    assert unit["diagnostic"]["confidence"] == 0.9
    assert unit["diagnostic"]["attempts"][0]["patch_summary"] == "x"


def test_escalation_decision_verifies_against_the_run_own_spec(client, monkeypatch):
    """Regression: decide_escalation used to call verify_unit(unit_id,
    candidate_body, work_dir) with no `spec=`, so it silently verified
    against RunSpec.default() (the interest.cob demo scaffold) no matter
    which program the run was actually for. For any other program (e.g.
    feecalc.cob, whose scaffold has no markers for its own paragraph ids)
    assemble() raised UnknownParagraphError, an unhandled exception that
    surfaced as a bare 500 instead of a typed error. Asserts verify_unit
    is called with the run's own resolved spec, not the default one."""
    from weaver.agent.attribution import AttributionResult
    from weaver.agent.escalation import DiagnosticRecord
    from weaver.report import Report

    class FakeMemory:
        def __init__(self):
            self.written_back = []

        def write_back(self, case):
            self.written_back.append(case)

    @dataclass
    class FakeOrchestratorEscalates(FakeOrchestrator):
        def __post_init__(self):
            super().__post_init__()
            self.memory = FakeMemory()

        def run(self):
            self._emit("*", "plan", "select_units", 0.0, outcome="units=['UNIT-A']")
            diag = DiagnosticRecord(
                unit_identifier="UNIT-A", failing_input_record="rec", oracle_value="1.00",
                candidate_value="2.00", delta="1.00", defect_class="TRUNCATION", confidence=0.9,
                attempts=[{"attempt": 1, "patch_summary": "x", "why_it_failed": "y"}],
                assumptions=["a"], suspected_source_lines="1-2", decision_requested="accept?",
            )
            self.results["UNIT-A"] = UnitResult("UNIT-A", "escalated", "final body", 1, False, 0.02, diag)
            self._persist_state()
            return self.results

    monkeypatch.setattr(runs_module, "Orchestrator", FakeOrchestratorEscalates)

    seen_specs = []

    def fake_verify_unit(unit_id, candidate_body, work_dir, *, spec=None):
        seen_specs.append(spec)
        return AttributionResult(unit_id, Report(unit_id, 1, divergence_count=0), [], True, None)

    monkeypatch.setattr(runs_module, "verify_unit", fake_verify_unit)

    resp = client.post("/runs", json=_create_payload(
        cobol_source="fixtures/cobol_feecalc/feecalc.cob", data_file="fixtures/data_feecalc/fees.dat",
    ))
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)

    decision_resp = client.post(
        f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"}
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["verified"] is True

    from backend.app import run_manager
    record = run_manager.get_run(run_id)
    assert len(seen_specs) == 1
    assert seen_specs[0] is record.orchestrator.spec
    assert seen_specs[0] != RunSpec.default()
    assert "feecalc" in str(seen_specs[0].scaffold_path)


def test_get_run_diagnostic_is_null_for_committed_unit(client):
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    state = _wait_terminal(client, run_id)
    assert all(u["diagnostic"] is None for u in state["units"])


def test_unit_code_returns_cobol_span_and_java_body(client, monkeypatch):
    """Gap 1: the console's side-by-side panel needs COBOL text + span
    and the generated Java body for one unit."""
    from weaver.agent.segment import Paragraph

    fake_paragraph = Paragraph(identifier="UNIT-A", start_line=10, end_line=12,
                                source="UNIT-A.\n    COMPUTE X = 1.")
    monkeypatch.setattr(runs_module, "segment", lambda text: [fake_paragraph])

    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)

    code_resp = client.get(f"/runs/{run_id}/units/UNIT-A/code")
    assert code_resp.status_code == 200
    body = code_resp.json()
    assert body["unit_id"] == "UNIT-A"
    assert body["cobol"]["start_line"] == 10
    assert body["cobol"]["end_line"] == 12
    assert "COMPUTE X" in body["cobol"]["text"]
    assert body["java"]["available"] is True
    assert body["java"]["body"] == "body"  # FakeOrchestrator commits final_body="body"


def test_unit_code_404_for_unknown_unit(client, monkeypatch):
    monkeypatch.setattr(runs_module, "segment", lambda text: [])
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)

    code_resp = client.get(f"/runs/{run_id}/units/NOPE/code")
    assert code_resp.status_code == 404
    assert code_resp.json()["error_class"] == "RUN_NOT_FOUND"


def test_resume_route_is_reachable(client):
    """Gap 3: resume_run() existed with no HTTP route. Force a completed
    run's in-memory lifecycle to INTERRUPTED and confirm the route reaches
    RunManager.resume_run rather than 404ing -- full resumption behavior
    against a real Orchestrator is exercised elsewhere; this is a
    transport-reachability test."""
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)

    from backend.app import run_manager
    record = run_manager.get_run(run_id)
    record.lifecycle = "INTERRUPTED"

    resume_resp = client.post(f"/runs/{run_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["run_id"] == run_id


def test_resume_rejects_non_interrupted_run(client):
    resp = client.post("/runs", json=_create_payload())
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)  # COMPLETED, not INTERRUPTED

    resume_resp = client.post(f"/runs/{run_id}/resume")
    assert resume_resp.status_code == 400
    assert resume_resp.json()["error_class"] == "INVALID_REQUEST"


def test_list_runs_newest_first_with_counts(client):
    r1 = client.post("/runs", json=_create_payload()).json()["run_id"]
    _wait_terminal(client, r1)
    time.sleep(0.01)
    r2 = client.post("/runs", json=_create_payload()).json()["run_id"]
    _wait_terminal(client, r2)

    listing = client.get("/runs").json()
    ids = [r["run_id"] for r in listing]
    assert ids.index(r2) < ids.index(r1)
    entry = next(r for r in listing if r["run_id"] == r2)
    assert entry["lifecycle"] == "COMPLETED"
    assert entry["unit_count"] == 2
    assert entry["committed_count"] == 2


def test_params_json_records_resolved_spec_alongside_request(client):
    """Gap 4: params.json must describe the spec that actually ran, not
    only the raw request -- CLAUDE.md rule 13 / NFR-D1."""
    resp = client.post("/runs", json=_create_payload(seed=5, max_repair_attempts=9))
    run_id = resp.json()["run_id"]
    _wait_terminal(client, run_id)

    from backend.app import run_manager
    record = run_manager.get_run(run_id)
    params = json.loads(record.params_path.read_text())
    assert params["request"]["seed"] == 5
    assert params["resolved_spec"]["seed"] == 5
    assert params["resolved_spec"]["max_repairs"] == 9


def test_bind_refusal_for_non_loopback_host():
    from backend.__main__ import _validate_bind_host
    from backend.errors import OfflineViolationError
    with pytest.raises(OfflineViolationError):
        _validate_bind_host("0.0.0.0")
    _validate_bind_host("127.0.0.1")  # does not raise


# -- GnuCOBOL version detection (SRS §2.4 / §8 OI-3) ------------------------
# _check_toolchain is monkeypatched to (True, "ok") for every test above via
# the autouse fixture (transport-layer tests don't care about the real
# toolchain); these exercise the detection function itself directly, with
# subprocess/shutil.which mocked so no real cobc/javac install is needed.

def test_toolchain_reports_not_found_when_cobc_absent(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: None)
    available, detail = _real_check_toolchain()
    assert available is False
    assert detail == "gnucobol_not_found"


def test_toolchain_reports_not_found_when_javac_absent(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: "/usr/bin/cobc" if name == "cobc" else None)
    monkeypatch.setattr(app_module, "_gnucobol_major_version", lambda path: 3)
    available, detail = _real_check_toolchain()
    assert available is False
    assert detail == "javac_not_found"


def test_toolchain_rejects_gnucobol_2x(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(app_module, "_gnucobol_major_version", lambda path: 2)
    available, detail = _real_check_toolchain()
    assert available is False
    assert detail.startswith("gnucobol_version_unsupported:2")


def test_toolchain_accepts_gnucobol_3x(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(app_module, "_gnucobol_major_version", lambda path: 3)
    available, detail = _real_check_toolchain()
    assert available is True
    assert detail == "ok"


def test_gnucobol_major_version_parses_banner(monkeypatch):
    class _FakeProc:
        stdout = "cobc (GnuCOBOL) 3.1.2\nCopyright (C) ..."
        stderr = ""

    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **kw: _FakeProc())
    assert app_module._gnucobol_major_version("cobc") == 3


def test_create_run_rejects_when_toolchain_unavailable(monkeypatch, client):
    monkeypatch.setattr(app_module, "_check_toolchain", lambda: (False, "gnucobol_not_found"))
    resp = client.post("/runs", json=_create_payload())
    assert resp.status_code == 503
    assert resp.json()["error_class"] == "TOOLCHAIN_MISSING"


def test_cli_report_and_api_metrics_are_byte_identical(tmp_path, capsys):
    """DC-5 (BACKEND_PLAN.md SS4.4): every number the API serves must be
    obtainable from the CLI. Both call compute_metrics on the same files; if
    they ever diverge, correctness is being decided in two places."""
    import dataclasses
    import json

    from weaver.agent.metrics import compute_metrics
    from weaver.cli import build_parser, run_report

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps({
            "timestamp": 1.0, "unit": "P1", "node": "perceive", "action": "segment",
            "duration_seconds": 0.1, "model_calls": 0, "tokens": 0,
            "memory_hit": False, "outcome": "1 paragraphs found",
        }) + "\n"
    )
    (run_dir / "orchestrator_state.json").write_text("{}")

    api_metrics = dataclasses.asdict(
        compute_metrics(run_dir / "trace.jsonl", run_dir / "orchestrator_state.json",
                        run_dir / "m4_baseline.json")
    )

    args = build_parser().parse_args(["report", str(run_dir)])
    assert run_report(args) == 0
    cli_metrics = json.loads(capsys.readouterr().out)

    assert cli_metrics == api_metrics
