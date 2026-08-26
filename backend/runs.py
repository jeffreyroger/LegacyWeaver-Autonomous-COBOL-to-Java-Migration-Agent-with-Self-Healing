"""Run lifecycle and orchestration — BACKEND_PLAN.md §3.2, §4.2, §4.5, Steps B3/B6/B7.

`RunManager` is the only place the API touches the agent. It imports
`weaver.agent.orchestrator.Orchestrator` and nothing more from the agent's
correctness path -- it never computes, filters, or classifies anything
itself (§1.2).
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent.attribution import verify_unit
from weaver.agent.leaf_orchestrator import LeafOrchestrator
from weaver.agent.memory import MemoryCase, embed
from weaver.agent.metrics import compute_metrics
from weaver.atomic_json import write_json_atomic
from weaver.agent.orchestrator import Orchestrator, UnitResult
from weaver.agent.program_profiles import program_profile
from weaver.agent.result_view import (
    divergence_source,
    normalize_divergence_report,
    normalize_unit_result,
    result_kind,
)
from weaver.agent.runspec import RunSpec
from weaver.agent.segment import segment
from weaver.agent.signature import build_signature
from weaver.classification import Classification, DefectClass
from weaver.cobol.subprogram import load_subprogram

from backend.errors import InvalidRequestError, RunNotFoundError
from backend.events import RunEventBus
from backend.models import CreateRunRequest

RUNS_ROOT = Path("generated/runs")

LIFECYCLE_TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}


@dataclass(frozen=True)
class _SourceSpan:
    start_line: int
    end_line: int
    source: str


def _build_run_spec(request: CreateRunRequest) -> RunSpec:
    """Translate a CreateRunRequest into the RunSpec the orchestrator runs.

    Mirrors weaver/cli.py's build_migrate_spec: every parameter that
    reaches this function must land in the RunSpec, and per-program
    defaults (scaffold_path/golden_output/reference_body_path/
    scaffold_spec) come from the same ProgramProfile registry the CLI
    uses, not silently interest.cob's -- both were CLAUDE.md rule 13/
    DC-5/NFR-D1 violations found in the 2026-08-12 audit: seed, model,
    max_repairs, replay, and copybook_dir were dropped entirely, and no
    program-specific profile was ever consulted, so any backend-launched
    run against a program other than interest.cob would have silently
    verified against interest.cob's scaffold and golden output.
    """
    defaults = RunSpec.default()
    cobol_source = Path(request.cobol_source)
    # Multi-program (leaf-first) requests give cobol_source as a DIRECTORY,
    # not a single program file -- program_profile() parses a single file
    # through the real COBOL frontend, so calling it on a directory would
    # raise. LeafOrchestrator._run_file_based already re-resolves each DAG
    # node's own profile individually (see that module); this base spec is
    # deliberately left at RunSpec's plain defaults for the fields a
    # profile would otherwise fill in.
    profile = None if request.leaf_first else program_profile(cobol_source)
    scaffold_spec = (profile.scaffold_spec if profile else None) or defaults.scaffold_spec
    if request.redefines_as_subclasses:
        scaffold_spec = dataclasses.replace(scaffold_spec, redefines_as_subclasses=True)
    return RunSpec(
        cobol_source=cobol_source,
        copybook_dir=Path(request.copybook_dir) if request.copybook_dir else None,
        input_data=Path(request.data_file),
        golden_output=(profile.golden_output if profile else None) or defaults.golden_output,
        scaffold_path=(profile.scaffold_path if profile else None) or defaults.scaffold_path,
        memory_store_path=defaults.memory_store_path,
        reference_body_path=(profile.reference_body_path if profile else None) or defaults.reference_body_path,
        reference_paragraph_id=(profile.reference_paragraph_id if profile else None)
                                or defaults.reference_paragraph_id,
        scaffold_spec=scaffold_spec,
        candidate_body_path=Path(request.candidate_path) if not request.synthesis_mode else None,
        max_repairs=request.max_repair_attempts,
        model=request.model_name,
        model_digest=request.model_digest,
        seed=request.seed,
        replay=request.replay,
        use_text_refinement=request.use_text_refinement,
        use_delta_debugging=request.use_delta_debugging,
        use_batch_synthesis=request.use_batch_synthesis,
    )


@dataclass
class RunRecord:
    run_id: str
    request: CreateRunRequest
    run_dir: Path
    lifecycle: str = "CREATED"
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    event_bus: RunEventBus = field(default_factory=RunEventBus)
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    orchestrator: Orchestrator | LeafOrchestrator | None = None
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
        if not req.synthesis_mode and not req.candidate_path:
            raise InvalidRequestError("synthesis_mode=false requires candidate_path")
        if not req.synthesis_mode and not Path(req.candidate_path).exists():
            raise InvalidRequestError(f"candidate_path does not exist: {req.candidate_path}")
        # Multi-program dispatch (weaver migrate --leaf-first's backend
        # equivalent): cobol_source must actually be the shape leaf_first
        # claims it is, mirroring weaver/cli.py:443-446's own directory
        # check for the same flag.
        cobol_source_path = Path(req.cobol_source)
        if req.leaf_first and not cobol_source_path.is_dir():
            raise InvalidRequestError(
                f"leaf_first=true requires cobol_source to be a directory of *.cob files, "
                f"got a file: {req.cobol_source}"
            )
        if not req.leaf_first and cobol_source_path.is_dir():
            raise InvalidRequestError(
                f"cobol_source is a directory ({req.cobol_source}) but leaf_first=false -- "
                "pass leaf_first=true for a multi-program run"
            )

        run_id = uuid.uuid4().hex
        run_dir = RUNS_ROOT / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        record = RunRecord(run_id=run_id, request=req, run_dir=run_dir)
        # Persist determinism-affecting parameters before the first unit
        # executes -- the reproducibility record required by NFR-D1/§4.2.
        # "request" is the raw caller input; "resolved_spec" (added once the
        # worker builds the RunSpec, see _write_resolved_spec) is what
        # actually ran -- CLAUDE.md rule 13's guard is that the two must
        # never silently diverge.
        self._write_params(record, resolved_spec=None)
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

    def _raw_unit_pairs(self, record: RunRecord) -> list[tuple[str | None, object]]:
        """Every unit result on this run as (program_name_or_None,
        raw_result) -- None for a single-program run (`Orchestrator`), the
        DAG program name for a multi-program run (`LeafOrchestrator`).
        Raw dataclass instances (`UnitResult`/`SubprogramUnitResult`), not
        serialized -- normalization happens once, at the API boundary
        (`weaver.agent.result_view`), never duplicated here (§1.2)."""
        if record.orchestrator is None:
            return []
        if isinstance(record.orchestrator, LeafOrchestrator):
            with record.lock:
                program_results = {p: dict(u) for p, u in record.orchestrator.program_results.items()}
            return [(program, result) for program, units in program_results.items() for result in units.values()]
        with record.lock:
            results = list(record.orchestrator.results.values())
        return [(None, r) for r in results]

    def list_units(self, record: RunRecord) -> list[dict]:
        """Normalized `{unit_id, composite_id, program, status, ...}`
        dicts (`weaver.agent.result_view.normalize_unit_result`) -- one
        shape for both a single-program `Orchestrator` run and a
        multi-program `LeafOrchestrator` run, reused unmodified from
        `weaver/cli.py`'s own serialization (BACKEND_PLAN.md:419)."""
        return [normalize_unit_result(result, program_name=program)
                for program, result in self._raw_unit_pairs(record)]

    def _find_raw_result(self, record: RunRecord, unit_id: str, program: str | None) -> object | None:
        for p, result in self._raw_unit_pairs(record):
            this_id = getattr(result, "unit_id", None) or getattr(result, "program_id", None)
            if p == program and this_id == unit_id:
                return result
        return None

    def metrics_for(self, record: RunRecord) -> dict | None:
        if not record.state_path.exists() or not record.trace_path.exists():
            return None
        m4_path = record.run_dir / "m4_baseline.json"
        m = compute_metrics(record.trace_path, record.state_path, m4_path)
        return dataclasses.asdict(m)

    def divergence_report(self, record: RunRecord, unit_id: str, program: str | None = None) -> dict | None:
        result = self._find_raw_result(record, unit_id, program)
        if result is None:
            return None
        return normalize_divergence_report(divergence_source(result))

    def unit_code(self, record: RunRecord, unit_id: str, program: str | None = None) -> dict:
        """Gap 1: COBOL source span + generated Java body for the console's
        side-by-side panel. Re-runs segment() on the unit's own program
        source rather than caching paragraph state on RunRecord -- the
        field table already resolved before this point is what should be
        trusted.

        For a multi-program run, `program` selects which DAG node's source
        file to read (via LeafOrchestrator.resolve_source_file) instead of
        assuming record.request.cobol_source is a single file -- it is a
        directory for a leaf-first run. A subprogram unit's real paragraph
        is looked up by its actual paragraph id (SubprogramModel.paragraph_id,
        e.g. "MAIN-PARA"), which usually differs from the unit/program id
        (e.g. "LEAF-A") that names it everywhere else -- segment()-based
        lookup by unit_id would 404 on every real subprogram fixture
        otherwise.
        """
        result = self._find_raw_result(record, unit_id, program)
        if result is None:
            raise RunNotFoundError(f"no such unit {unit_id!r} on run {record.run_id}")

        if program is not None:
            if not isinstance(record.orchestrator, LeafOrchestrator):
                raise RunNotFoundError(f"run {record.run_id} is not a multi-program run")
            cobol_path = record.orchestrator.resolve_source_file(program)
        else:
            cobol_path = Path(record.request.cobol_source)

        source_text = cobol_path.read_text(encoding="utf-8")
        paragraph = None
        if result_kind(result) == "subprogram":
            # The unit id IS the program id for a subprogram (see
            # weaver.agent.result_view.normalize_unit_result); the actual
            # paragraph inside it is very often named differently
            # (MAIN-PARA in every fixture this project has).
            model = load_subprogram(cobol_path)
            paragraph = _SourceSpan(start_line=1, end_line=source_text.count("\n") + 1,
                                     source=model.paragraph_source)
        else:
            paragraphs = segment(source_text)
            paragraph = next((p for p in paragraphs if p.identifier == unit_id), None)
        if paragraph is None:
            raise RunNotFoundError(f"no paragraph {unit_id!r} in {cobol_path}")

        return {
            "unit_id": unit_id,
            "cobol": {
                "source_path": str(cobol_path),
                "start_line": paragraph.start_line,
                "end_line": paragraph.end_line,
                "text": paragraph.source,
            },
            "java": {"body": result.final_body, "available": result.final_body is not None},
        }

    def list_runs(self) -> list[dict]:
        """Gap 5: history sidebar / run-ID recovery after a page refresh.
        Merges the on-disk lifecycle.json/orchestrator_state.json scan
        (covers runs from a prior process, including INTERRUPTED ones) with
        live in-memory records (more current for a run still executing in
        this process) -- newest first."""
        by_id: dict[str, dict] = {}
        if RUNS_ROOT.exists():
            for run_dir in RUNS_ROOT.iterdir():
                lifecycle_path = run_dir / "lifecycle.json"
                if not lifecycle_path.exists():
                    continue
                data = json.loads(lifecycle_path.read_text(encoding="utf-8"))
                run_id = data.get("run_id", run_dir.name)
                unit_count = 0
                committed_count = 0
                state_path = run_dir / "orchestrator_state.json"
                if state_path.exists():
                    try:
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        unit_count = len(state)
                        committed_count = sum(1 for u in state.values() if u.get("status") == "committed")
                    except json.JSONDecodeError:
                        pass
                by_id[run_id] = {
                    "run_id": run_id, "lifecycle": data.get("lifecycle"),
                    "created_at": data.get("created_at"), "unit_count": unit_count,
                    "committed_count": committed_count,
                }

        with self._registry_lock:
            live_records = list(self._runs.values())
        for record in live_records:
            units = self.list_units(record)
            by_id[record.run_id] = {
                "run_id": record.run_id, "lifecycle": record.lifecycle,
                "created_at": record.created_at, "unit_count": len(units),
                "committed_count": sum(1 for u in units if u["status"] == "committed"),
            }

        return sorted(by_id.values(), key=lambda r: r["created_at"] or 0, reverse=True)

    # -- B6: escalation decisions ----------------------------------------

    def decide_escalation(self, record: RunRecord, unit_id: str, decision: str, body: str | None,
                           program: str | None = None) -> dict:
        """Accept, reject, or supply a body for an escalated unit.

        Any accepted/supplied body is re-verified against the oracle before
        being committed (FR-4.5) -- a human's approval is not evidence of
        correctness; the byte comparison is the only authority (§1.2).

        `program` set means this is a multi-program (leaf_first) unit --
        dispatched to `_decide_escalation_multi_program`, which uses
        `verify_subprogram`/`_verify_mocked` for a subprogram unit instead
        of the file-based `verify_unit` path below (docs/specs/
        BACKEND_PLAN.md Step B10; 2026-08-26).
        """
        if program is not None:
            return self._decide_escalation_multi_program(record, unit_id, decision, body, program)
        if isinstance(record.orchestrator, LeafOrchestrator):
            raise InvalidRequestError(
                "unit_id alone is ambiguous for a multi-program run -- use "
                "/runs/{run_id}/programs/{program}/escalations/{unit_id}/decision"
            )
        unit = record.orchestrator.results.get(unit_id) if record.orchestrator is not None else None
        if unit is None or unit.status != "escalated":
            raise InvalidRequestError(f"unit {unit_id} is not in an escalated state")

        if decision == "reject":
            outcome = {"unit_id": unit_id, "decision": "reject", "verified": False, "committed": False}
        elif decision in ("accept", "body"):
            candidate_body = body if decision == "body" else unit.final_body
            if not candidate_body:
                raise InvalidRequestError("no body available to verify for this decision")
            work_dir = record.run_dir / "escalations" / unit_id
            # verify_unit defaults to RunSpec.default() (the interest.cob
            # demo scaffold) when spec is omitted -- for any other program
            # (e.g. handlfee.cob) its scaffold has no markers for this
            # unit_id, so assemble() raises UnknownParagraphError, an
            # unhandled exception that fell through to a bare 500 instead
            # of a typed error. record.orchestrator is guaranteed non-None
            # here: `unit` above came from list_units(), which returns []
            # when orchestrator is None, and we'd have raised
            # InvalidRequestError before reaching this line in that case.
            result = verify_unit(unit_id, candidate_body, work_dir, spec=record.orchestrator.spec)
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
        write_json_atomic(record.run_dir / "escalation_decisions.json",
                            record.escalation_decisions)
        return outcome

    def _decide_escalation_multi_program(self, record: RunRecord, unit_id: str, decision: str,
                                          body: str | None, program: str) -> dict:
        if not isinstance(record.orchestrator, LeafOrchestrator):
            raise InvalidRequestError(f"run {record.run_id} is not a multi-program run")
        unit = self._find_raw_result(record, unit_id, program)
        if unit is None or unit.status != "escalated":
            raise InvalidRequestError(f"unit {unit_id} on program {program} is not in an escalated state")

        if decision == "reject":
            outcome = {"unit_id": unit_id, "program": program, "decision": "reject",
                       "verified": False, "committed": False}
        elif decision in ("accept", "body"):
            candidate_body = body if decision == "body" else unit.final_body
            if not candidate_body:
                raise InvalidRequestError("no body available to verify for this decision")
            work_dir = record.run_dir / "escalations" / program / unit_id
            kind = result_kind(unit)
            if kind == "subprogram":
                verify_result = self._reverify_subprogram(record.orchestrator, program, candidate_body, work_dir)
                verified = verify_result.compiled and verify_result.divergence_count == 0
                divergence_count = verify_result.divergence_count if verify_result.compiled else None
                replaced_field = "verify_result"
            else:
                attribution_result = self._reverify_file_based(record.orchestrator, program, unit_id,
                                                                 candidate_body, work_dir)
                verified = attribution_result.compiled and attribution_result.report.divergence_count == 0
                divergence_count = attribution_result.report.divergence_count if attribution_result.compiled else None
                verify_result = attribution_result.report
                replaced_field = "last_report"
            if verified:
                with record.lock:
                    record.orchestrator.program_results.setdefault(program, {})[unit_id] = dataclasses.replace(
                        unit, status="committed", final_body=candidate_body,
                        **{replaced_field: verify_result},
                    )
                    record.orchestrator._persist_state()
                # No memory write-back here: SubprogramUnitResult carries no
                # DiagnosticRecord to build a signature from (subprogram
                # units have no failure-memory path at all yet), and a
                # multi-program file-based unit's diagnostic is dropped at
                # this same granularity -- a disclosed narrower scope than
                # the single-program path's _write_back_escalation.
            outcome = {
                "unit_id": unit_id, "program": program, "decision": decision,
                "verified": verified, "committed": verified, "divergence_count": divergence_count,
            }
        else:
            raise InvalidRequestError(f"unknown decision: {decision!r}")

        key = f"{program}::{unit_id}"
        record.escalation_decisions[key] = outcome
        write_json_atomic(record.run_dir / "escalation_decisions.json", record.escalation_decisions)
        return outcome

    @staticmethod
    def _reverify_subprogram(orchestrator: LeafOrchestrator, program: str, candidate_body: str, work_dir: Path):
        """Real re-verification for an escalated subprogram unit --
        `verify_subprogram` (or `_verify_mocked` for an EXEC SQL/CICS
        subprogram) over the fixed, hand-verified
        `DEFAULT_SUBPROGRAM_WITNESSES` set. An escalated unit never
        finished a commit, so it was never harvested into a UnitCache
        (`_run_subprogram` only harvests after `status == "committed"`) --
        there is no cache to re-verify against, only a fresh real
        cobc/javac round trip. The original run's witness set (possibly
        witness-search-derived) isn't persisted anywhere, so this
        deliberately re-verifies against the same fixed set every
        subprogram escalation gets -- a disclosed, real, meaningful
        re-verification, not a fabricated pass."""
        from weaver.agent.leaf_orchestrator import DEFAULT_SUBPROGRAM_WITNESSES
        from weaver.agent.subprogram_orchestrator import _verify_mocked
        from weaver.agent.subprogram_verify import verify_subprogram
        from weaver.cobol.mock_directives import find_mock_directives
        from weaver.cobol.subprogram import load_subprogram

        cobol_file = orchestrator.resolve_source_file(program)
        model = load_subprogram(cobol_file)
        mocked = bool(find_mock_directives(cobol_file.read_text(encoding="utf-8")))
        if mocked:
            return _verify_mocked(model, candidate_body, DEFAULT_SUBPROGRAM_WITNESSES, work_dir)
        return verify_subprogram(model, candidate_body, DEFAULT_SUBPROGRAM_WITNESSES, work_dir)

    @staticmethod
    def _reverify_file_based(orchestrator: LeafOrchestrator, program: str, unit_id: str,
                              candidate_body: str, work_dir: Path):
        """Real re-verification for an escalated file-based unit inside a
        multi-program run -- the same `verify_unit` the single-program
        path uses, but built against THIS PROGRAM's own resolved profile
        (golden_output/scaffold_spec/...), exactly like
        `LeafOrchestrator._run_file_based` resolves it for a fresh run.
        Using `orchestrator.base_spec` directly (as the single-program
        path uses `record.orchestrator.spec`) would verify against
        whichever program a plain `weaver migrate` run happened to be
        built for -- the same DC-5/CLAUDE.md rule 13 class of bug Phase X7
        already fixed for the ordinary run path."""
        cobol_file = orchestrator.resolve_source_file(program)
        profile = program_profile(cobol_file)
        spec = orchestrator.base_spec
        if profile is not None:
            spec = spec.replace(
                cobol_source=cobol_file,
                golden_output=profile.golden_output or spec.golden_output,
                scaffold_spec=profile.scaffold_spec or spec.scaffold_spec,
                scaffold_path=profile.scaffold_path or spec.scaffold_path,
                reference_body_path=profile.reference_body_path or spec.reference_body_path,
                reference_paragraph_id=profile.reference_paragraph_id or spec.reference_paragraph_id,
                input_data=profile.input_data or spec.input_data,
            )
        else:
            spec = spec.replace(cobol_source=cobol_file)
        return verify_unit(unit_id, candidate_body, work_dir, spec=spec)

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
                spec = _build_run_spec(record.request)
                self._write_params(record, resolved_spec=spec.to_dict())
                if record.request.leaf_first:
                    self._run_leaf_first(record, spec)
                else:
                    self._run_single_program(record, spec)
            except Exception as exc:  # noqa: BLE001 -- surfaced as run state, never a crash
                record.lifecycle = "FAILED"
                record.error = str(exc)
            finally:
                self._write_lifecycle(record)
                record.event_bus.close()

    def _run_single_program(self, record: RunRecord, spec: RunSpec) -> None:
        orchestrator = Orchestrator(
            spec=spec,
            trace_path=record.trace_path,
            state_path=record.state_path,
            on_event=lambda event: record.event_bus.publish(event),
            cancel_requested=record.cancel_requested,
            results_lock=record.lock,
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

    def _run_leaf_first(self, record: RunRecord, spec: RunSpec) -> None:
        """Multi-program dispatch -- the backend equivalent of
        `weaver migrate --leaf-first`. `run_dir=record.run_dir` makes
        LeafOrchestrator write its own combined trace/flat state to
        exactly `record.trace_path`/`record.state_path`
        (run_dir/trace.jsonl, run_dir/orchestrator_state.json), so
        `metrics_for` needs no multi-program awareness at all -- see
        weaver/agent/result_view.py and leaf_orchestrator.py's run_dir
        field docstring. Lifecycle uses the exact same all-committed rule
        `weaver/cli.py`'s exit code does (BACKEND_PLAN.md:419: one
        definition, not two)."""
        from weaver.agent.result_view import all_committed

        orchestrator = LeafOrchestrator(
            program_dir=spec.cobol_source,
            base_spec=spec,
            work_root=record.run_dir / "leaf_orchestrator",
            run_dir=record.run_dir,
            on_event=lambda event: record.event_bus.publish(event),
            cancel_requested=record.cancel_requested,
            results_lock=record.lock,
        )
        record.orchestrator = orchestrator
        program_results = orchestrator.run()

        if record.cancel_requested.is_set():
            record.lifecycle = "CANCELLED"
        elif all_committed(program_results):
            record.lifecycle = "COMPLETED"
        elif program_results:
            record.lifecycle = "PARTIAL"
        else:
            record.lifecycle = "FAILED"

    # -- B7: checkpoint / resume --------------------------------------------

    def _write_params(self, record: RunRecord, resolved_spec: dict | None) -> None:
        write_json_atomic(record.params_path, {
            "request": record.request.model_dump(), "resolved_spec": resolved_spec,
        })

    def _write_lifecycle(self, record: RunRecord) -> None:
        write_json_atomic(record.lifecycle_path, {
            "run_id": record.run_id, "lifecycle": record.lifecycle, "error": record.error,
            "created_at": record.created_at,
        })

    def _scan_for_interrupted_runs(self) -> None:
        """On startup, any run left RUNNING with no live process is
        INTERRUPTED, not silently resumed as if nothing happened."""
        if not RUNS_ROOT.exists():
            return
        for run_dir in RUNS_ROOT.iterdir():
            lifecycle_path = run_dir / "lifecycle.json"
            if not lifecycle_path.exists():
                continue
            data = json.loads(lifecycle_path.read_text(encoding="utf-8"))
            if data.get("lifecycle") == "RUNNING":
                data["lifecycle"] = "INTERRUPTED"
                write_json_atomic(lifecycle_path, data)

    def resume_run(self, run_id: str) -> RunRecord:
        """Reload an INTERRUPTED run's state and continue from the first
        incomplete unit (single-program) or program (multi-program).
        Committed units/programs are not re-verified (§4.5).

        Branches on `record.request.leaf_first`, not `isinstance(
        record.orchestrator, LeafOrchestrator)`, because after a process
        restart (the exact case resume exists for) `record.orchestrator`
        is None -- the original request is the only thing that survives.
        """
        record = self.get_run(run_id)
        if record.lifecycle != "INTERRUPTED":
            raise InvalidRequestError(f"run {run_id} is not interrupted (state={record.lifecycle})")

        if record.request.leaf_first:
            resume_committed = self._reconstruct_committed_programs(record)
            thread = threading.Thread(
                target=self._resume_leaf_first_worker, args=(record, resume_committed), daemon=True,
            )
        else:
            committed_results: dict[str, UnitResult] = {}
            if record.state_path.exists():
                saved = json.loads(record.state_path.read_text(encoding="utf-8"))
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

    def _reconstruct_committed_programs(self, record: RunRecord) -> dict[str, dict[str, object]]:
        """Groups the flat, composite-id-keyed state file
        (weaver.agent.result_view.normalize_program_results's own output
        shape) back into `{program: {unit_id: raw_result}}` for
        LeafOrchestrator.resume_committed -- but only for a program where
        EVERY unit committed. A program with even one escalated/failed
        unit is re-run from scratch: LeafOrchestrator has no per-unit
        resume within a single program's own nested orchestrator, only
        program granularity (a disclosed, deliberate scope limit -- see
        docs/specs/BACKEND_PLAN.md Step B10)."""
        if not record.state_path.exists():
            return {}
        saved = json.loads(record.state_path.read_text(encoding="utf-8"))
        by_program: dict[str, dict[str, dict]] = {}
        for entry in saved.values():
            by_program.setdefault(entry["program"], {})[entry["unit_id"]] = entry

        resume_committed: dict[str, dict[str, object]] = {}
        for program_name, units in by_program.items():
            if not all(u["status"] == "committed" for u in units.values()):
                continue
            resume_committed[program_name] = {
                unit_id: self._reconstruct_raw_result(entry) for unit_id, entry in units.items()
            }
        return resume_committed

    @staticmethod
    def _reconstruct_raw_result(entry: dict) -> object:
        """UnitResult or SubprogramUnitResult from a normalized state
        entry -- diagnostic/last_report/verify_result are dropped, same as
        the single-program resume path already does: a resumed unit is
        adopted, never re-verified, so there is nothing to re-derive them
        from without actually re-running the verification this exists to
        skip."""
        if entry["kind"] == "subprogram":
            from weaver.agent.subprogram_orchestrator import SubprogramUnitResult

            return SubprogramUnitResult(
                program_id=entry["unit_id"], status=entry["status"], final_body=entry["final_body"],
                model_calls=entry["model_calls"], duration_seconds=entry["duration_seconds"],
            )
        return UnitResult(
            unit_id=entry["unit_id"], status=entry["status"], final_body=entry["final_body"],
            model_calls=entry["model_calls"], memory_hit=entry.get("memory_hit", False),
            duration_seconds=entry["duration_seconds"],
        )

    def _resume_leaf_first_worker(self, record: RunRecord, resume_committed: dict[str, dict[str, object]]) -> None:
        with self._active_lock:
            record.lifecycle = "RUNNING"
            self._write_lifecycle(record)
            try:
                from weaver.agent.result_view import all_committed

                spec = _build_run_spec(record.request)
                self._write_params(record, resolved_spec=spec.to_dict())
                orchestrator = LeafOrchestrator(
                    program_dir=spec.cobol_source,
                    base_spec=spec,
                    work_root=record.run_dir / "leaf_orchestrator",
                    run_dir=record.run_dir,
                    on_event=lambda event: record.event_bus.publish(event),
                    cancel_requested=record.cancel_requested,
                    results_lock=record.lock,
                    resume_committed=resume_committed,
                )
                record.orchestrator = orchestrator
                program_results = orchestrator.run()

                if record.cancel_requested.is_set():
                    record.lifecycle = "CANCELLED"
                elif all_committed(program_results):
                    record.lifecycle = "COMPLETED"
                elif program_results:
                    record.lifecycle = "PARTIAL"
                else:
                    record.lifecycle = "FAILED"
            except Exception as exc:  # noqa: BLE001
                record.lifecycle = "FAILED"
                record.error = str(exc)
            finally:
                self._write_lifecycle(record)
                record.event_bus.close()

    def _resume_worker(self, record: RunRecord, committed_results: dict[str, UnitResult]) -> None:
        with self._active_lock:
            record.lifecycle = "RUNNING"
            self._write_lifecycle(record)
            try:
                spec = _build_run_spec(record.request)
                self._write_params(record, resolved_spec=spec.to_dict())
                orchestrator = Orchestrator(
                    spec=spec,
                    trace_path=record.trace_path,
                    state_path=record.state_path,
                    on_event=lambda event: record.event_bus.publish(event),
                    cancel_requested=record.cancel_requested,
                    fresh_trace=False,
                    results_lock=record.lock,
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
