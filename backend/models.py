"""Request/response shapes for the run service — BACKEND_PLAN.md §4.1/§4.2.

Pydantic models only. No field here computes, filters, or derives a value;
every value either echoes what the caller sent or is copied verbatim from
an agent-produced structure (Orchestrator.UnitResult, Report, Metrics).
"""

from __future__ import annotations

from pydantic import BaseModel

from weaver.agent.runspec import DEFAULT_MAX_REPAIRS, DEFAULT_MODEL, DEFAULT_SEED


class CreateRunRequest(BaseModel):
    cobol_source: str
    copybook_dir: str | None = None
    data_file: str
    # BACKEND_PLAN.md §4.2's "candidate path or synthesis mode": when
    # synthesis_mode is False, candidate_path must point at a Java method
    # body file used directly instead of calling the model (zero inference
    # calls) -- RunManager.create_run validates the pairing and existence,
    # _build_run_spec threads it into RunSpec.candidate_body_path, and
    # Orchestrator._process_unit skips synthesize_paragraph when set. Only
    # supports single-synthesis-unit programs (Orchestrator.run() raises
    # otherwise) -- implemented 2026-08-12.
    candidate_path: str | None = None
    synthesis_mode: bool = True
    seed: int = DEFAULT_SEED
    model_name: str = DEFAULT_MODEL
    model_digest: str = ""
    max_repair_attempts: int = DEFAULT_MAX_REPAIRS
    replay: bool = False
    # 2026-08-26: the same opt-in RunSpec switches weaver/cli.py's `migrate`
    # subcommand has exposed since (respectively) 2026-08-07 and 2026-08-26
    # -- until now, only reachable from the CLI, never from a backend-
    # launched run (see _build_run_spec's docstring in backend/runs.py).
    # All four default False/unchanged, so an existing caller that never
    # sets them gets byte-identical behavior to before this field existed.
    use_text_refinement: bool = False
    use_delta_debugging: bool = False
    use_batch_synthesis: bool = False
    redefines_as_subclasses: bool = False
    # Multi-program (leaf-first DAG) runs, added 2026-08-26 -- mirrors
    # `weaver migrate --leaf-first` (weaver/cli.py). When True,
    # `cobol_source` is reinterpreted as a DIRECTORY of *.cob files
    # (RunManager.create_run validates this) and RunManager dispatches to
    # weaver.agent.leaf_orchestrator.LeafOrchestrator instead of the
    # single-program Orchestrator. False by default -- an existing
    # single-program request is completely unaffected. DAG-level resume
    # (RunManager.resume_run) and escalation decisions
    # (POST .../programs/{program}/escalations/{unit}/decision) are both
    # implemented for a leaf-first run (docs/specs/BACKEND_PLAN.md Step
    # B10) -- memory write-back on an accepted escalation is the one
    # remaining disclosed gap (CLAUDE.md rule 12), not resume/escalation
    # themselves.
    leaf_first: bool = False


class CreateRunResponse(BaseModel):
    run_id: str
    # Echoed verbatim -- the reproducibility record required by NFR-D1.
    cobol_source: str
    copybook_dir: str | None
    data_file: str
    candidate_path: str | None
    synthesis_mode: bool
    seed: int
    model_name: str
    model_digest: str
    max_repair_attempts: int
    replay: bool
    use_text_refinement: bool
    use_delta_debugging: bool
    use_batch_synthesis: bool
    redefines_as_subclasses: bool
    leaf_first: bool


class UnitStateResponse(BaseModel):
    unit_id: str
    status: str
    model_calls: int
    memory_hit: bool
    duration_seconds: float


class RunStateResponse(BaseModel):
    run_id: str
    lifecycle: str  # CREATED | RUNNING | COMPLETED | PARTIAL | FAILED | CANCELLED | INTERRUPTED
    units: list[UnitStateResponse]
    metrics: dict | None
    error: str | None = None


class EscalationDecisionRequest(BaseModel):
    decision: str  # "accept" | "reject" | "body"
    body: str | None = None


class HealthResponse(BaseModel):
    status: str
    toolchain_available: bool
    toolchain_detail: str
    inference_available: bool
    bind_host: str
