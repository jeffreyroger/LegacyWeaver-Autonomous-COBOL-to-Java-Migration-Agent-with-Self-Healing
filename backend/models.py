"""Request/response shapes for the run service — BACKEND_PLAN.md §4.1/§4.2.

Pydantic models only. No field here computes, filters, or derives a value;
every value either echoes what the caller sent or is copied verbatim from
an agent-produced structure (Orchestrator.UnitResult, Report, Metrics).
"""

from __future__ import annotations

from pydantic import BaseModel

from zuse.agent.runspec import DEFAULT_MAX_REPAIRS, DEFAULT_MODEL, DEFAULT_SEED


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
