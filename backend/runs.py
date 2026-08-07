"""Run lifecycle and orchestration — BACKEND_PLAN.md §3.2, §4.2, §4.5, Steps B3/B6/B7.

`RunManager` is the only place the API touches the agent. It imports
`weaver.agent.orchestrator.Orchestrator` and nothing more from the agent's
correctness path -- it never computes, filters, or classifies anything
itself (§1.2).
"""

from __future__ import annotations

import dataclasses
import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent.attribution import verify_unit
from weaver.agent.memory import MemoryCase, embed
from weaver.agent.metrics import compute_metrics
from weaver.agent.orchestrator import Orchestrator, UnitResult
from weaver.agent.runspec import RunSpec
from weaver.agent.signature import build_signature
from weaver.classification import Classification, DefectClass
from weaver.report import Report

from backend.errors import InvalidRequestError, RunNotFoundError
from backend.events import RunEventBus
from backend.models import CreateRunRequest

RUNS_ROOT = Path("generated/runs")

LIFECYCLE_TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}


@dataclass
class RunRecord:
    run_id: str
    request: CreateRunRequest
    run_dir: Path
    lifecycle: str = "CREATED"
    error: str | None = None
    event_bus: RunEventBus = field(default_factory=RunEventBus)
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    orchestrator: Orchestrator | None = None
    thread: threading.Thread | None = None
    escalation_decisions: dict[str, dict] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def trace_path(self) -> Path:
        return self.run_dir / "trace.jsonl"

    @property
    def state_path(self) -> Path:
        return self.run_dir / "orchestrator_state.json"

    @property
    def params_path(self) -> Path:
        return self.run_dir / "params.json"

    @property
    def lifecycle_path(self) -> Path:
        return self.run_dir / "lifecycle.json"


class RunManager:
    """One process, one run at a time (§3.1) -- enforced by `_active_lock`."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._registry_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._scan_for_interrupted_runs()

    # -- B3: create / get / cancel --------------------------------------

    def create_run(self, req: CreateRunRequest) -> RunRecord:
        if not req.cobol_source or not req.data_file:
            raise InvalidRequestError("cobol_source and data_file are required")

        run_id = uuid.uuid4().hex
        run_dir = RUNS_ROOT / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        record = RunRecord(run_id=run_id, request=req, run_dir=run_dir)
        # Persist determinism-affecting parameters before the first unit
        # executes -- the reproducibility record required by NFR-D1/§4.2.
        record.params_path.write_text(json.dumps(req.model_dump(), indent=2))
        self._write_lifecycle(record)

        with self._registry_lock:
            self._runs[run_id] = record

        thread = threading.Thread(target=self._run_worker, args=(record,), daemon=True)
        record.thread = thread
        thread.start()
        return record

    def get_run(self, run_id: str) -> RunRecord:
        with self._registry_lock:
            record = self._runs.get(run_id)
        if record is None:
            raise RunNotFoundError(f"no such run: {run_id}")
        return record

    def cancel_run(self, run_id: str) -> RunRecord:
        record = self.get_run(run_id)
        record.cancel_requested.set()
        return record

    def list_units(self, record: RunRecord) -> list[UnitResult]:
        if record.orchestrator is None:
            return []
        with record.lock:
            return list(record.orchestrator.results.values())

    def metrics_for(self, record: RunRecord) -> dict | None:
        if not record.state_path.exists() or not record.trace_path.exists():
            return None
        m4_path = record.run_dir / "m4_baseline.json"
        m = compute_metrics(record.trace_path, record.state_path, m4_path)
        return dataclasses.asdict(m)

    def divergence_report(self, record: RunRecord, unit_id: str) -> Report | None:
        for result in self.list_units(record):
            if result.unit_id == unit_id:
                return result.last_report
        return None

    # -- B6: escalation decisions ----------------------------------------

    def decide_escalation(self, record: RunRecord, unit_id: str, decision: str, body: str | None) -> dict:
        """Accept, reject, or supply a body for an escalated unit.

        Any accepted/supplied body is re-verified against the oracle before
        being committed (FR-4.5) -- a human's approval is not evidence of
        correctness; the byte comparison is the only authority (§1.2).
        """
        units = {r.unit_id: r for r in self.list_units(record)}
        unit = units.get(unit_id)
        if unit is None or unit.status != "escalated":
            raise InvalidRequestError(f"unit {unit_id} is not in an escalated state")

        if decision == "reject":
            outcome = {"unit_id": unit_id, "decision": "reject", "verified": False, "committed": False}
        elif decision in ("accept", "body"):
            candidate_body = body if decision == "body" else unit.final_body
            if not candidate_body:
                raise InvalidRequestError("no body available to verify for this decision")
            work_dir = record.run_dir / "escalations" / unit_id
            result = verify_unit(unit_id, candidate_body, work_dir)
            verified = result.compiled and result.report.divergence_count == 0
            if verified:
                with record.lock:
                    record.orchestrator.results[unit_id] = dataclasses.replace(
                        unit, status="committed", final_body=candidate_body, last_report=result.report,
                    )
                    record.orchestrator._persist_state()
                # B6 item 3 / FR-6.4 -- write back only after verification
                # succeeded above; a human's approval is never sufficient on
                # its own (§1.2), the byte comparison already ran and passed.
                self._write_back_escalation(record, unit, candidate_body)
            outcome = {
                "unit_id": unit_id, "decision": decision, "verified": verified, "committed": verified,
                "divergence_count": result.report.divergence_count if result.compiled else None,
            }
        else:
            raise InvalidRequestError(f"unknown decision: {decision!r}")

        record.escalation_decisions[unit_id] = outcome
        (record.run_dir / "escalation_decisions.json").write_text(
            json.dumps(record.escalation_decisions, indent=2)
        )
        return outcome

    def _write_back_escalation(self, record: RunRecord, unit: UnitResult, verified_body: str) -> None:
        """Store a human-accepted, oracle-verified repair the same way the
        orchestrator's own repair loop does (O2.5/B6 item 3). Only unit
        diagnostics that named a defect class carry enough information to
        build a signature -- a synthesis failure (no candidate body at all)
        has nothing to key retrieval on, so it is skipped rather than
        stored with a fabricated signature."""
        diagnostic = unit.diagnostic
        if diagnostic is None or diagnostic.defect_class is None:
            return
        classification = Classification(
            DefectClass(diagnostic.defect_class), diagnostic.confidence or 0.0,
            {"delta": diagnostic.delta} if diagnostic.delta is not None else {},
        )
        # The original offending COBOL statement isn't retained on the
        # diagnostic record; the unit identifier is the best available text
        # for the normalized-operation component of the signature at this
        # (post-escalation, human-decision) point.
        sig = build_signature(classification, field_scale=2, offending_statement=unit.unit_id)
        case = MemoryCase(
            case_id=f"{unit.unit_id}-{classification.defect_class.value}-{uuid.uuid4().hex[:8]}",
            signature=sig,
            embedding=embed(sig.as_text()),
            defect_class=classification.defect_class.value,
            normalized_construct=sig.normalized_operation,
            root_cause=f"Resolved by human escalation decision on unit {unit.unit_id}.",
            patch_description="Body supplied or accepted via the escalation-decision endpoint.",
            patch_body_template=verified_body,
            verification_status="verified",
            hit_count=0,
            confidence=1.0,
            provenance=f"Written back by RunManager.decide_escalation for run {record.run_id}, "
                       f"unit {unit.unit_id} (verify_unit compile + differential comparison, "
                       f"0 divergences, after human decision).",
        )
        with record.lock:
            record.orchestrator.memory.write_back(case)

    # -- worker thread -----------------------------------------------------

    def _run_worker(self, record: RunRecord) -> None:
        with self._active_lock:  # one run at a time, process-wide (§3.1)
            record.lifecycle = "RUNNING"
            self._write_lifecycle(record)
            try:
                spec = RunSpec.default().replace(
                    cobol_source=Path(record.request.cobol_source),
                    input_data=Path(record.request.data_file),
                )
                orchestrator = Orchestrator(
                    spec=spec,
                    trace_path=record.trace_path,
                    state_path=record.state_path,
                    on_event=lambda event: record.event_bus.publish(event),
                    cancel_requested=record.cancel_requested,
                )
                record.orchestrator = orchestrator
                orchestrator.run()

                if record.cancel_requested.is_set():
                    record.lifecycle = "CANCELLED"
                else:
                    statuses = {r.status for r in orchestrator.results.values()}
                    if not statuses or statuses == {"committed"}:
                        record.lifecycle = "COMPLETED"
                    elif "committed" in statuses:
                        record.lifecycle = "PARTIAL"
                    else:
                        record.lifecycle = "PARTIAL" if orchestrator.results else "FAILED"
            except Exception as exc:  # noqa: BLE001 -- surfaced as run state, never a crash
                record.lifecycle = "FAILED"
                record.error = str(exc)
            finally:
                self._write_lifecycle(record)
                record.event_bus.close()

    # -- B7: checkpoint / resume --------------------------------------------

    def _write_lifecycle(self, record: RunRecord) -> None:
        record.lifecycle_path.write_text(json.dumps({
            "run_id": record.run_id, "lifecycle": record.lifecycle, "error": record.error,
        }, indent=2))

    def _scan_for_interrupted_runs(self) -> None:
        """On startup, any run left RUNNING with no live process is
        INTERRUPTED, not silently resumed as if nothing happened."""
        if not RUNS_ROOT.exists():
            return
        for run_dir in RUNS_ROOT.iterdir():
            lifecycle_path = run_dir / "lifecycle.json"
            if not lifecycle_path.exists():
                continue
            data = json.loads(lifecycle_path.read_text())
            if data.get("lifecycle") == "RUNNING":
                data["lifecycle"] = "INTERRUPTED"
                lifecycle_path.write_text(json.dumps(data, indent=2))

    def resume_run(self, run_id: str) -> RunRecord:
        """Reload an INTERRUPTED run's state and continue from the first
        incomplete unit. Committed units are not re-verified (§4.5)."""
        record = self.get_run(run_id)
        if record.lifecycle != "INTERRUPTED":
            raise InvalidRequestError(f"run {run_id} is not interrupted (state={record.lifecycle})")

        committed_results: dict[str, UnitResult] = {}
        if record.state_path.exists():
            saved = json.loads(record.state_path.read_text())
            for uid, r in saved.items():
                if r["status"] == "committed":
                    committed_results[uid] = UnitResult(
                        unit_id=uid, status="committed", final_body=r.get("final_body"),
                        model_calls=r.get("model_calls", 0), memory_hit=r.get("memory_hit", False),
                        duration_seconds=r.get("duration_seconds", 0.0),
                    )

        thread = threading.Thread(
            target=self._resume_worker, args=(record, committed_results), daemon=True,
        )
        record.thread = thread
        thread.start()
        return record

    def _resume_worker(self, record: RunRecord, committed_results: dict[str, UnitResult]) -> None:
        with self._active_lock:
            record.lifecycle = "RUNNING"
            self._write_lifecycle(record)
            try:
                spec = RunSpec.default().replace(
                    cobol_source=Path(record.request.cobol_source),
                    input_data=Path(record.request.data_file),
                )
                orchestrator = Orchestrator(
                    spec=spec,
                    trace_path=record.trace_path,
                    state_path=record.state_path,
                    on_event=lambda event: record.event_bus.publish(event),
                    cancel_requested=record.cancel_requested,
                    fresh_trace=False,
                )
                orchestrator.results.update(committed_results)
                record.orchestrator = orchestrator
                _run_skipping_committed(orchestrator, set(committed_results))

                statuses = {r.status for r in orchestrator.results.values()}
                record.lifecycle = "COMPLETED" if statuses <= {"committed"} else "PARTIAL"
            except Exception as exc:  # noqa: BLE001
                record.lifecycle = "FAILED"
                record.error = str(exc)
            finally:
                self._write_lifecycle(record)
                record.event_bus.close()


def _run_skipping_committed(orchestrator: Orchestrator, committed_ids: set[str]) -> None:
    """Same loop as Orchestrator.run(), but committed units from a prior
    (interrupted) attempt are neither re-synthesised nor re-verified --
    only the checkpointed record is kept."""
    units = orchestrator._plan()
    for unit in units:
        if orchestrator.cancel_requested is not None and orchestrator.cancel_requested.is_set():
            break
        if unit.identifier in committed_ids:
            continue
        result = orchestrator._process_unit(unit)
        orchestrator.results[unit.identifier] = result
        orchestrator._persist_state()
