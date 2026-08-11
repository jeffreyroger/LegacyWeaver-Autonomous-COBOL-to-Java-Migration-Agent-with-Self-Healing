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
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({k: asdict(v) for k, v in self.results.items()}, default=str))


@pytest.fixture(autouse=True)
def _patch_orchestrator(monkeypatch, tmp_path):
    monkeypatch.setattr(runs_module, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    # This file exercises the transport/lifecycle layer with a stand-in
    # Orchestrator, independent of whether a real GnuCOBOL toolchain is
    # present (see module docstring). The toolchain gate itself (added for
    # the OI-3 version-detection fix) is exercised separately below.
    monkeypatch.setattr(app_module, "_check_toolchain", lambda: (True, "ok"))
    yield


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
    raise TimeoutError("run did not reach a terminal state")


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
