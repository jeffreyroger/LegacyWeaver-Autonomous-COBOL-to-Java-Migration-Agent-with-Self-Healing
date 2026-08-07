"""Orchestrator — Step P2.

Implements the state machine in docs/specs/orchestrator_state_machine.md.
Emits one trace event per transition (newline-delimited JSON, appended
immediately -- not buffered -- so a crashed run still leaves a usable
partial trace) and persists per-unit state so a run is resumable.
Never halts the whole run on one unit's escalation (plan's explicit
instruction) -- continues to the next unit and reports partial progress.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from weaver.agent.attribution import verify_unit
from weaver.agent.escalation import DiagnosticRecord, build_diagnostic_record
from weaver.agent.inference import InferenceClient
from weaver.agent.memory import FailureMemory
from weaver.agent.memory_repair import try_memory_repair
from weaver.agent.repair_loop import repair_unit
from weaver.agent.segment import Paragraph, segment
from weaver.agent.synthesize import synthesize_paragraph

STATE_PATH = Path("generated/orchestrator_state.json")
TRACE_PATH = Path("generated/trace.ndjson")


@dataclass
class UnitResult:
    unit_id: str
    status: str  # "committed" | "escalated"
    final_body: str | None
    model_calls: int
    memory_hit: bool
    duration_seconds: float
    diagnostic: DiagnosticRecord | None = None


@dataclass
class Orchestrator:
    cobol_source: Path
    scaffold_path: Path
    memory_store_path: Path
    trace_path: Path = TRACE_PATH
    state_path: Path = STATE_PATH
    results: dict[str, UnitResult] = field(default_factory=dict)
    on_event: Callable[[dict], None] | None = None
    cancel_requested: threading.Event | None = None

    def __post_init__(self) -> None:
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_path.write_text("")  # fresh trace per run
        self.client = InferenceClient(cache_dir=Path("generated/model_cache"))
        self.memory = FailureMemory(self.memory_store_path)

    def _emit(self, unit_id: str, node: str, action: str, duration: float,
               model_calls: int = 0, tokens: int = 0, memory_hit: bool = False,
               outcome: str = "") -> None:
        event = {
            "timestamp": time.time(), "unit": unit_id, "node": node, "action": action,
            "duration_seconds": round(duration, 3), "model_calls": model_calls,
            "tokens": tokens, "memory_hit": memory_hit, "outcome": outcome,
        }
        # Disk write is authoritative and happens unconditionally; the
        # callback is a tee for an observer (e.g. the backend's SSE stream)
        # and must never block or alter what lands on disk.
        with self.trace_path.open("a") as f:
            f.write(json.dumps(event) + "\n")
        if self.on_event is not None:
            self.on_event(event)

    def _plan(self) -> list[Paragraph]:
        # perceive
        t0 = time.monotonic()
        paragraphs = segment(self.cobol_source.read_text())
        self._emit("*", "perceive", "segment", time.monotonic() - t0, outcome=f"{len(paragraphs)} paragraphs found")

        # plan: only non-control-flow paragraphs are synthesis units (K1 --
        # MAIN-PARA is control flow, handled by the scaffold's main loop).
        control_flow_ids = {"MAIN-PARA"}
        units = [p for p in paragraphs if p.identifier not in control_flow_ids]
        self._emit("*", "plan", "select_units", 0.0, outcome=f"units={[u.identifier for u in units]}")
        return units

    def _process_unit(self, unit: Paragraph) -> UnitResult:
        unit_start = time.monotonic()
        model_calls = 0

        # synthesise
        t0 = time.monotonic()
        synth = synthesize_paragraph(unit, self.client)
        model_calls += synth.validation_attempts
        self._emit(unit.identifier, "synthesise", "generate", time.monotonic() - t0,
                    model_calls=synth.validation_attempts, outcome="ok" if synth.body else "synthesis_failure")

        if synth.body is None:
            record = build_diagnostic_record(
                unit, "SYNTHESIS_FAILURE", None, None, [], synth.raw_responses,
            )
            duration = time.monotonic() - unit_start
            self._emit(unit.identifier, "escalate", "give_up", duration, outcome="synthesis_failure")
            return UnitResult(unit.identifier, "escalated", None, model_calls, False, duration, record)

        body = synth.body.method_body

        # compile + verify (attribution)
        t0 = time.monotonic()
        result = verify_unit(unit.identifier, body, Path(f"generated/orchestrator/{unit.identifier}/synthesis"))
        self._emit(unit.identifier, "compile", "javac", time.monotonic() - t0,
                    outcome="ok" if result.compiled else "compile_error")

        if result.compiled:
            t0 = time.monotonic()
            self._emit(unit.identifier, "verify", "differential_compare", time.monotonic() - t0,
                        outcome=f"{result.report.divergence_count} divergences")

            if result.report.divergence_count == 0:
                duration = time.monotonic() - unit_start
                self._emit(unit.identifier, "commit", "accept", duration, outcome="verified clean")
                return UnitResult(unit.identifier, "committed", body, model_calls, False, duration)

            # classify (already computed inside verify_unit) + memory lookup
            classification = result.classifications[0]
            failing_div = result.report.divergences[0]
            t0 = time.monotonic()
            mem_result, case_id = try_memory_repair(
                self.memory, unit.identifier, body, classification, 2,
                failing_div.field_name, Path(f"generated/orchestrator/{unit.identifier}/memory"),
            )
            self._emit(unit.identifier, "memory_lookup", "query", time.monotonic() - t0,
                        memory_hit=case_id is not None, outcome=case_id or "miss")

            if mem_result is not None:
                duration = time.monotonic() - unit_start
                self._emit(unit.identifier, "commit", "accept", duration,
                            memory_hit=True, outcome=f"resolved from memory case {case_id}")
                return UnitResult(unit.identifier, "committed", body, model_calls, True, duration)

        # repair (N2/N3/N4)
        t0 = time.monotonic()
        outcome = repair_unit(unit.identifier, unit, body, result, self.client,
                               Path(f"generated/orchestrator/{unit.identifier}/repair"))
        model_calls += sum(1 for a in outcome.attempts if "model" in a.outcome or "compile_error" in a.outcome)
        self._emit(unit.identifier, "repair", "attempt_loop", time.monotonic() - t0,
                    model_calls=model_calls,
                    outcome="resolved" if outcome.resolved else outcome.escalation_reason)

        duration = time.monotonic() - unit_start
        if outcome.resolved:
            self._emit(unit.identifier, "commit", "accept", duration, outcome="resolved via repair loop")
            return UnitResult(unit.identifier, "committed", outcome.final_body, model_calls, False, duration)

        record = build_diagnostic_record(
            unit, outcome.escalation_reason or "unresolved", classification if result.compiled else None,
            result.report.divergences[0] if result.compiled and result.report.divergences else None,
            outcome.attempts, synth.body.assumptions,
        )
        self._emit(unit.identifier, "escalate", "give_up", duration, outcome=outcome.escalation_reason)
        return UnitResult(unit.identifier, "escalated", outcome.final_body, model_calls, False, duration, record)

    def run(self) -> dict[str, UnitResult]:
        units = self._plan()
        for unit in units:
            # Checked at a unit boundary only -- never kill mid-unit, which
            # would leave containers running and state inconsistent.
            if self.cancel_requested is not None and self.cancel_requested.is_set():
                self._emit("*", "cancel", "stop_before_unit", 0.0, outcome=f"stopped before {unit.identifier}")
                break
            # Never halt the whole run on one unit's escalation.
            result = self._process_unit(unit)
            self.results[unit.identifier] = result
            # Checkpoint after commit/escalate (both terminal), never before.
            self._persist_state()
        return self.results

    def _persist_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {}
        for unit_id, r in self.results.items():
            d = asdict(r)
            payload[unit_id] = d
        self.state_path.write_text(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    orchestrator = Orchestrator(
        cobol_source=Path("fixtures/cobol/interest.cob"),
        scaffold_path=Path("generated/Scaffold.java"),
        memory_store_path=Path("generated/failure_memory.json"),
    )
    results = orchestrator.run()
    for unit_id, r in results.items():
        print(f"{unit_id}: {r.status} (model_calls={r.model_calls}, memory_hit={r.memory_hit}, "
              f"{r.duration_seconds:.1f}s)")
    print(f"\ntrace: {orchestrator.trace_path}")
    print(f"state: {orchestrator.state_path}")
