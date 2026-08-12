"""The run service — BACKEND_PLAN.md Part IV. FastAPI app.

Binding, inference-loopback validation, and static asset serving are all
enforced here at startup/mount time, not left to configuration (§5.1,
§5.2, §5.4). This module imports the agent; nothing in zuse/agent may
import this module or fastapi/starlette (§3.3, enforced by
tests/test_backend_import_direction.py).
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from zuse.agent.inference import OLLAMA_HOST, _assert_loopback

from backend.errors import RunNotFoundError, ServiceError, ToolchainMissingError
from backend.models import (
    CreateRunRequest,
    CreateRunResponse,
    EscalationDecisionRequest,
    HealthResponse,
)
from backend.runs import RunManager

BIND_HOST = "127.0.0.1"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # §3.9.2 / §5.2 -- must run in the service, not only the CLI. A remote
    # inference host must abort startup, naming the reason, so the UI path
    # can never be less safe than the CLI path.
    _assert_loopback(OLLAMA_HOST)
    yield


app = FastAPI(title="Zuse run service", lifespan=_lifespan)
run_manager = RunManager()


MIN_GNUCOBOL_MAJOR = 3
_GNUCOBOL_VERSION_RE = re.compile(r"GnuCOBOL\)?\s+(\d+)\.")


def _gnucobol_major_version(cobc_path: str) -> int | None:
    """Parse the major version out of `cobc --version`'s banner. Returns
    None if the banner can't be parsed -- treated as unsupported rather
    than assumed-fine, since SRS §2.4 requires 3.x and §8 OI-3 explicitly
    calls out that 2.x silently diverges rather than erroring."""
    try:
        proc = subprocess.run(
            [cobc_path, "--version"], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    match = _GNUCOBOL_VERSION_RE.search(proc.stdout or proc.stderr or "")
    return int(match.group(1)) if match else None


def _check_toolchain() -> tuple[bool, str]:
    """Returns (available, detail). `detail` distinguishes "not installed"
    from "installed but the wrong major version" (SRS §2.4 / OI-3) rather
    than collapsing both into an unexplained bool."""
    cobc_path = shutil.which("cobc")
    if cobc_path is None:
        return False, "gnucobol_not_found"
    if shutil.which("javac") is None:
        return False, "javac_not_found"
    major = _gnucobol_major_version(cobc_path)
    if major is None:
        return False, "gnucobol_version_undetermined"
    if major < MIN_GNUCOBOL_MAJOR:
        return (
            False,
            f"gnucobol_version_unsupported:{major}.x (requires {MIN_GNUCOBOL_MAJOR}.x, SRS §2.4)",
        )
    return True, "ok"


def _inference_available() -> bool:
    import requests

    try:
        requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1)
        return True
    except Exception:
        return False


@app.exception_handler(ServiceError)
def _service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_class": exc.error_class, "message": exc.message},
    )


@app.exception_handler(Exception)
def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """BACKEND_PLAN.md §4.6: every INTERNAL error carries a trace ID.

    Endpoint bodies (get_run, get_divergences, stream_events, etc.) don't
    each wrap their own try/except -- an exception raised outside the
    worker-thread's own handling (which already catches and records
    FAILED lifecycle) previously fell through to FastAPI's default 500
    with no error_class/trace ID, unlike every typed ServiceError. Found
    in the 2026-08-12 audit. Registering a handler for the base Exception
    does not shadow the ServiceError handler above or FastAPI's own
    HTTPException/RequestValidationError handlers -- Starlette dispatches
    to the most specific registered handler in the exception's MRO.
    """
    trace_id = uuid.uuid4().hex
    return JSONResponse(
        status_code=500,
        content={"error_class": "INTERNAL", "message": str(exc), "trace_id": trace_id},
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    toolchain_available, toolchain_detail = _check_toolchain()
    return HealthResponse(
        status="ok",
        toolchain_available=toolchain_available,
        toolchain_detail=toolchain_detail,
        inference_available=_inference_available(),
        bind_host=BIND_HOST,
    )


@app.post("/runs", response_model=CreateRunResponse)
def create_run(req: CreateRunRequest) -> CreateRunResponse:
    toolchain_available, toolchain_detail = _check_toolchain()
    if not toolchain_available:
        raise ToolchainMissingError(f"toolchain unavailable: {toolchain_detail}")
    record = run_manager.create_run(req)
    return CreateRunResponse(run_id=record.run_id, **req.model_dump())


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    record = run_manager.get_run(run_id)
    # Read lifecycle before units: the worker only ever sets a terminal
    # lifecycle *after* the results dict is fully populated, so reading
    # in this order can under-report units for a still-RUNNING run (an
    # honest snapshot of in-progress state) but can never pair a
    # terminal lifecycle with an incomplete unit list.
    lifecycle = record.lifecycle
    units = run_manager.list_units(record)
    metrics = run_manager.metrics_for(record)
    return {
        "run_id": record.run_id,
        "lifecycle": lifecycle,
        "units": [
            {
                "unit_id": u.unit_id,
                "status": u.status,
                "model_calls": u.model_calls,
                "memory_hit": u.memory_hit,
                "duration_seconds": u.duration_seconds,
                # Gap 2: the escalation card needs to show why a unit
                # escalated (defect class, delta, confidence, prior repair
                # attempts) before a human is asked to accept/reject it.
                # Serialized verbatim -- null for a unit that hasn't
                # escalated, never a synthesized placeholder.
                "diagnostic": dataclasses.asdict(u.diagnostic)
                if u.diagnostic is not None
                else None,
            }
            for u in units
        ],
        "metrics": metrics,
        "error": record.error,
    }


@app.get("/runs")
def list_runs() -> list[dict]:
    """Gap 5: history sidebar / run-ID recovery after a page refresh.
    Newest first; includes INTERRUPTED runs, which are what the resume
    button targets."""
    return run_manager.list_runs()


@app.get("/runs/{run_id}/units/{unit_id}/code")
def get_unit_code(run_id: str, unit_id: str) -> dict:
    """Gap 1: COBOL source span + generated Java body for the console's
    side-by-side, provenance-hover panel."""
    record = run_manager.get_run(run_id)
    return run_manager.unit_code(record, unit_id)


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    record = run_manager.cancel_run(run_id)
    return {
        "run_id": record.run_id,
        "cancel_requested": True,
        "lifecycle": record.lifecycle,
    }


@app.post("/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict:
    """Gap 3: NFR-R2 resumability was fully implemented in RunManager but
    unreachable from a browser. InvalidRequestError (400) propagates from
    resume_run when the run isn't INTERRUPTED."""
    record = run_manager.resume_run(run_id)
    return {"run_id": record.run_id, "lifecycle": record.lifecycle}


@app.get("/runs/{run_id}/divergences/{unit_id}")
def get_divergences(run_id: str, unit_id: str) -> dict:
    record = run_manager.get_run(run_id)
    report = run_manager.divergence_report(record, unit_id)
    if report is None:
        raise RunNotFoundError(
            f"no divergence report for unit {unit_id} on run {run_id}"
        )
    return json.loads(report.to_json())


@app.post("/runs/{run_id}/escalations/{unit_id}/decision")
def post_escalation_decision(
    run_id: str, unit_id: str, req: EscalationDecisionRequest
) -> dict:
    record = run_manager.get_run(run_id)
    return run_manager.decide_escalation(record, unit_id, req.decision, req.body)


@app.get("/runs/{run_id}/events")
def stream_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream, forwarding trace events verbatim (§4.3 / Step B4)."""
    record = run_manager.get_run(run_id)
    last_event_id = 0
    header = request.headers.get("last-event-id")
    if header:
        last_event_id = int(header)

    def _generate():
        sub_id, live_queue, backlog = record.event_bus.subscribe(last_event_id)
        try:
            for seq, event in backlog:
                yield f"id: {seq}\ndata: {json.dumps(event)}\n\n"
            while True:
                item = live_queue.get()
                if item is None:  # run finished, bus closed
                    break
                seq, event = item
                yield f"id: {seq}\ndata: {json.dumps(event)}\n\n"
        finally:
            record.event_bus.unsubscribe(sub_id)

    return StreamingResponse(_generate(), media_type="text/event-stream")


# §5.1 / Step B8 -- serve frontend assets from disk, no CDN fallback.
# STATIC_DIR is currently a placeholder: the frontend bundle has not been
# built yet (out of scope for this backend phase), so nothing is mounted
# until it exists. Mounting an empty/missing directory as the UI would
# misrepresent a component as working before its own acceptance test
# passes (CLAUDE.md rule 12).
if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
