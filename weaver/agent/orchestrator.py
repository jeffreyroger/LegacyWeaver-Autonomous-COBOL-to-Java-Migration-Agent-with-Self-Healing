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
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import uuid

from weaver.agent.assemble import assemble
from weaver.agent.attribution import verify_unit
from weaver.agent.escalation import DiagnosticRecord, build_diagnostic_record
from weaver.agent.inference import GROQ_HOST, InferenceClient
from weaver.agent.memory import FailureMemory, MemoryCase, embed
from weaver.agent.memory_repair import try_memory_repair
from weaver.agent.repair_loop import repair_unit
from weaver.agent.runspec import RunSpec
from weaver.agent.scaffold import field_scale as scaffold_field_scale
from weaver.agent.scaffold import generate as generate_scaffold
from weaver.agent.segment import Paragraph, segment
from weaver.agent.signature import build_signature
from weaver.agent.synthesize import SynthesisResult, synthesize_paragraph
from weaver.agent.validate import SynthesizedBody
from weaver.atomic_json import write_json_atomic
from weaver.report import Report

STATE_PATH = Path("generated/orchestrator_state.json")
TRACE_PATH = Path("generated/trace.jsonl")  # FR-8.1
RUNS_ROOT = Path("runs")  # FR-8.1: runs/<run_id>/trace.jsonl


@dataclass
class UnitResult:
    unit_id: str
    status: str  # "committed" | "escalated"
    final_body: str | None
    model_calls: int
    memory_hit: bool
    duration_seconds: float
    diagnostic: DiagnosticRecord | None = None
    last_report: Report | None = None  # backend divergence endpoint (BACKEND_PLAN.md §4.1) reads this verbatim


@dataclass
class Orchestrator:
    spec: RunSpec = field(default_factory=RunSpec.default)
    trace_path: Path = TRACE_PATH
    state_path: Path = STATE_PATH
    results: dict[str, UnitResult] = field(default_factory=dict)
    output_path: Path | None = field(default=None, init=False)  # set by run() -- see _write_output
    on_event: Callable[[dict], None] | None = None
    cancel_requested: threading.Event | None = None
    fresh_trace: bool = True
    # Held around every `results` mutation, if supplied, so a caller reading
    # `results` under its own lock (e.g. backend/runs.py's `record.lock`,
    # which guards RunManager.list_units()/decide_escalation()'s reads of
    # this same dict) never races the worker thread's writes -- found in
    # the 2026-08-12 audit: the backend's lock only serialized its own
    # accesses against each other, not against this thread.
    results_lock: threading.Lock | None = None

    @property
    def cobol_source(self) -> Path:
        return self.spec.cobol_source

    def __post_init__(self) -> None:
        # Rule 9 (Phase V): the scaffold is derived data from scaffold_spec,
        # not a hand-committed artefact -- regenerate it unconditionally so
        # `weaver migrate`/the backend work for any program, not only
        # interest.cob (whose generated/Scaffold.java happens to be checked
        # in). Deterministic from scaffold_spec, so this never changes
        # behaviour for a program whose scaffold was already on disk.
        self.spec.scaffold_path.parent.mkdir(parents=True, exist_ok=True)
        self.spec.scaffold_path.write_text(generate_scaffold(self.spec.scaffold_spec), encoding="utf-8")

        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        if self.fresh_trace:
            self.trace_path.write_text("", encoding="utf-8")  # fresh trace per run
        else:
            self.trace_path.touch(exist_ok=True)  # resume: append, never truncate
        # CI-only override (CLAUDE.md rule 10 scoped exception): the
        # GitHub Action sets WEAVER_INFERENCE_PROVIDER=groq because runners
        # have no local Ollama daemon. Local/CLI/backend/frontend runs never
        # set this and stay on the offline "ollama" default.
        provider = os.environ.get("WEAVER_INFERENCE_PROVIDER", "ollama")
        client_kwargs: dict = {
            "cache_dir": Path("generated/model_cache"),
            "replay_only": self.spec.replay,
            "provider": provider,
        }
        if provider == "groq":
            client_kwargs["host"] = GROQ_HOST
        self.client = InferenceClient(**client_kwargs)
        self.memory = FailureMemory(self.spec.memory_store_path)

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
        paragraphs = segment(self.cobol_source.read_text(encoding="utf-8"))
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

        # synthesise -- or, if the caller supplied a candidate body
        # (BACKEND_PLAN.md SS4.2's candidate-supplied mode, added 2026-08-12),
        # use that directly and skip the model call entirely.
        t0 = time.monotonic()
        if self.spec.candidate_body_path is not None:
            supplied_body = self.spec.candidate_body_path.read_text(encoding="utf-8")
            synth = SynthesisResult(
                paragraph_id=unit.identifier,
                body=SynthesizedBody(method_body=supplied_body,
                                      assumptions=["supplied candidate body -- not synthesized"]),
                validation_attempts=0,
                prompt="",
                raw_responses=[],
            )
            self._emit(unit.identifier, "synthesise", "supplied", time.monotonic() - t0,
                        model_calls=0, outcome="ok (candidate supplied)")
        else:
            synth = synthesize_paragraph(unit, self.client, spec=self.spec)
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
        result = verify_unit(unit.identifier, body, Path(f"generated/orchestrator/{unit.identifier}/synthesis"),
                              spec=self.spec)
        self._emit(unit.identifier, "compile", "javac", time.monotonic() - t0,
                    outcome="ok" if result.compiled else "compile_error")

        if result.compiled:
            t0 = time.monotonic()
            self._emit(unit.identifier, "verify", "differential_compare", time.monotonic() - t0,
                        outcome=f"{result.report.divergence_count} divergences")

            if result.report.divergence_count == 0:
                duration = time.monotonic() - unit_start
                self._emit(unit.identifier, "commit", "accept", duration, outcome="verified clean")
                return UnitResult(unit.identifier, "committed", body, model_calls, False, duration,
                                   last_report=result.report)

            # classify (already computed inside verify_unit) + memory lookup
            classification = result.classifications[0]
            failing_div = result.report.divergences[0]
            # The field's own declared scale, not a value hardcoded for
            # interest.cob's fields (both happen to be scale 2) -- see
            # 2026-08-12 audit.
            field_scale = scaffold_field_scale(self.spec.scaffold_spec, failing_div.field_name)
            t0 = time.monotonic()
            mem_result, case_id = try_memory_repair(
                self.memory, unit.identifier, body, classification, field_scale,
                failing_div.field_name, Path(f"generated/orchestrator/{unit.identifier}/memory"),
                spec=self.spec,
            )
            self._emit(unit.identifier, "memory_lookup", "query", time.monotonic() - t0,
                        memory_hit=case_id is not None, outcome=case_id or "miss")

            if mem_result is not None:
                duration = time.monotonic() - unit_start
                self._emit(unit.identifier, "commit", "accept", duration,
                            memory_hit=True, outcome=f"resolved from memory case {case_id}")
                return UnitResult(unit.identifier, "committed", body, model_calls, True, duration,
                                   last_report=result.report)

        # repair (N2/N3/N4)
        t0 = time.monotonic()
        outcome = repair_unit(unit.identifier, unit, body, result, self.client,
                               Path(f"generated/orchestrator/{unit.identifier}/repair"), spec=self.spec)
        model_calls += sum(1 for a in outcome.attempts if "model" in a.outcome or "compile_error" in a.outcome)
        self._emit(unit.identifier, "repair", "attempt_loop", time.monotonic() - t0,
                    model_calls=model_calls,
                    outcome="resolved" if outcome.resolved else outcome.escalation_reason)

        duration = time.monotonic() - unit_start
        if outcome.resolved:
            self._emit(unit.identifier, "commit", "accept", duration, outcome="resolved via repair loop")
            if result.compiled:
                self._write_back_case(unit.identifier, classification, field_scale, failing_div.field_name,
                                       outcome)
            return UnitResult(unit.identifier, "committed", outcome.final_body, model_calls, False, duration,
                               last_report=outcome.final_report)

        record = build_diagnostic_record(
            unit, outcome.escalation_reason or "unresolved", classification if result.compiled else None,
            result.report.divergences[0] if result.compiled and result.report.divergences else None,
            outcome.attempts, synth.body.assumptions,
        )
        self._emit(unit.identifier, "escalate", "give_up", duration, outcome=outcome.escalation_reason)
        return UnitResult(unit.identifier, "escalated", outcome.final_body, model_calls, False, duration, record,
                           last_report=outcome.final_report)

    def _write_back_case(self, unit_id: str, classification, field_scale: int,
                          offending_statement: str, outcome) -> None:
        """O2.5 -- write back a repair verified by the loop itself (not a
        memory hit; those are already stored). The signature is built the
        same way O1/O2's query side builds it, so a future run's query()
        can find this case."""
        last_attempt = outcome.attempts[-1] if outcome.attempts else None
        source = "deterministic" if last_attempt and "deterministic" in last_attempt.outcome else "model"
        sig = build_signature(classification, field_scale, offending_statement)
        case = MemoryCase(
            case_id=f"{unit_id}-{classification.defect_class.value}-{uuid.uuid4().hex[:8]}",
            signature=sig,
            embedding=embed(sig.as_text()),
            defect_class=classification.defect_class.value,
            normalized_construct=sig.normalized_operation,
            root_cause=f"Resolved by the {source} repair path after {len(outcome.attempts)} attempt(s).",
            patch_description=last_attempt.outcome if last_attempt else "resolved via repair loop",
            patch_body_template=outcome.final_body,
            verification_status="verified",
            hit_count=0,
            confidence=1.0,
            provenance=f"Written back by Orchestrator._process_unit for unit {unit_id} "
                       f"(real repair loop run, verify_unit compile + differential comparison, "
                       f"0 divergences after patch).",
        )
        self.memory.write_back(case)

    def run(self) -> dict[str, UnitResult]:
        units = self._plan()
        if self.spec.candidate_body_path is not None and len(units) > 1:
            # A single candidate file can't disambiguate which of several
            # synthesis units it's a body for -- fail loudly rather than
            # guessing (e.g. silently applying it to the first unit only).
            raise ValueError(
                f"candidate_body_path ({self.spec.candidate_body_path}) supplies a single "
                f"paragraph body, but {self.cobol_source} has {len(units)} synthesis units "
                f"({[u.identifier for u in units]}) -- candidate-supplied mode only supports "
                "single-unit programs"
            )
        for unit in units:
            # Checked at a unit boundary only -- never kill mid-unit, which
            # would leave containers running and state inconsistent.
            if self.cancel_requested is not None and self.cancel_requested.is_set():
                self._emit("*", "cancel", "stop_before_unit", 0.0, outcome=f"stopped before {unit.identifier}")
                break
            # Never halt the whole run on one unit's escalation.
            result = self._process_unit(unit)
            if self.results_lock is not None:
                with self.results_lock:
                    self.results[unit.identifier] = result
            else:
                self.results[unit.identifier] = result
            # Checkpoint after commit/escalate (both terminal), never before.
            self._persist_state()
        self.output_path = self._write_output()
        return self.results

    def _write_output(self) -> Path | None:
        """Write the fully-assembled migrated program to spec.out_dir --
        SRS SS3.9.1's `--out` flag, accepted since RunSpec existed but never
        actually consumed anywhere (the same "accepted, never read" defect
        class as CLAUDE.md rule 13; found 2026-08-12 when a real CI run
        left `output/` with only its `.gitkeep`).

        Only written once every unit has a verified, committed body --
        never a partial program with an escalated unit's stub left in
        place, which would be a confident wrong answer. Namespaced by the
        COBOL source's stem so multiple programs migrated into the same
        --out directory (as the CI workflow does, looping several changed
        files through one `--out output`) don't overwrite each other.
        """
        if self.spec.out_dir is None:
            return None
        if not self.results or any(r.status != "committed" for r in self.results.values()):
            return None
        bodies = {unit_id: r.final_body for unit_id, r in self.results.items()}
        assembled = assemble(self.spec.scaffold_path.read_text(encoding="utf-8"), bodies)
        out_path = self.spec.out_dir / self.spec.cobol_source.stem / "Scaffold.java"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(assembled, encoding="utf-8")
        return out_path

    def _persist_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {}
        for unit_id, r in self.results.items():
            d = asdict(r)
            payload[unit_id] = d
        # Atomic: the backend serves GET /runs/{id} from this file while the
        # run is still executing (see weaver/atomic_json.py).
        write_json_atomic(self.state_path, payload)


if __name__ == "__main__":
    orchestrator = Orchestrator(spec=RunSpec.default())
    results = orchestrator.run()
    for unit_id, r in results.items():
        print(f"{unit_id}: {r.status} (model_calls={r.model_calls}, memory_hit={r.memory_hit}, "
              f"{r.duration_seconds:.1f}s)")
    print(f"\ntrace: {orchestrator.trace_path}")
    print(f"state: {orchestrator.state_path}")
