"""One serialization of a unit result, shared by the CLI and the backend
-- added 2026-08-26 for multi-program (leaf-first DAG) runs.

BACKEND_PLAN.md §1.2 forbids the API layer from computing or deriving
anything, and BACKEND_PLAN.md:419 forbids implementing one requirement in
two places. `weaver/cli.py`'s `run_migrate_leaf_first` and the backend
both need to turn a `LeafOrchestrator.run()` result into JSON, and those
results are heterogeneous: a file-based DAG node yields
`weaver.agent.orchestrator.UnitResult`, a subprogram node yields
`weaver.agent.subprogram_orchestrator.SubprogramUnitResult`, and the two
dataclasses share only `status`, `final_body`, `model_calls` and
`duration_seconds`. This module is the single place that difference is
reconciled.

Nothing here compares, classifies, or judges. A field the source
dataclass genuinely does not have is rendered as its honest empty value
(`memory_hit=False`, `diagnostic=None`) and `kind` records which type it
actually was, so a consumer can tell "this unit had no memory hit" apart
from "this kind of unit has no such concept" -- never a fabricated
placeholder presented as real data (CLAUDE.md rule 12).

**Composite ids.** A paragraph id is only unique *within* one program: a
directory of programs can easily contain two `MAIN-PARA`s. Multi-program
runs therefore key units by `PROGRAM::UNIT`. `::` is safe unencoded in a
URL path segment and is not a legal character in a COBOL paragraph name,
so it can never occur inside a real id and `split_composite` is
unambiguous. Keeping this key flat (rather than nesting the state file)
is what lets `weaver/agent/metrics.py` read a multi-program run's state
file completely unmodified -- see that module's `compute_metrics`, which
does `len(state)` and `r["status"]`.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

COMPOSITE_SEP = "::"


def composite_id(program_name: str | None, unit_id: str) -> str:
    """`PROGRAM::UNIT` for a multi-program run; the bare unit id when
    there is no program dimension (an ordinary single-program run, whose
    existing on-disk and API shapes must not change)."""
    if not program_name:
        return unit_id
    return f"{program_name}{COMPOSITE_SEP}{unit_id}"


def split_composite(cid: str) -> tuple[str | None, str]:
    """Inverse of `composite_id`. Returns `(None, cid)` for a bare id."""
    program, sep, unit = cid.partition(COMPOSITE_SEP)
    if not sep:
        return None, cid
    return program, unit


def _unit_id_of(result) -> str:
    """`UnitResult.unit_id` or `SubprogramUnitResult.program_id` -- the
    two dataclasses name their identifier differently."""
    unit_id = getattr(result, "unit_id", None)
    if unit_id is not None:
        return unit_id
    return result.program_id


def result_kind(result) -> str:
    """"file_based" (UnitResult, the Orchestrator path) or "subprogram"
    (SubprogramUnitResult, the SubprogramOrchestrator path). Keyed off
    the identifier field name rather than an isinstance check so this
    module does not have to import either orchestrator -- both of which
    import heavy verification machinery."""
    return "file_based" if getattr(result, "unit_id", None) is not None else "subprogram"


def normalize_unit_result(result, *, program_name: str | None = None) -> dict:
    """One dict shape for `UnitResult` and `SubprogramUnitResult` alike.

    `memory_hit` and `diagnostic` are absent from `SubprogramUnitResult`
    entirely (there is no failure-memory path for a subprogram unit yet);
    they render as False/None with `kind == "subprogram"` alongside, so
    the absence is legible rather than disguised.
    """
    unit_id = _unit_id_of(result)
    diagnostic = getattr(result, "diagnostic", None)
    return {
        "unit_id": unit_id,
        "composite_id": composite_id(program_name, unit_id),
        "program": program_name,
        "kind": result_kind(result),
        "status": result.status,
        "final_body": result.final_body,
        "model_calls": result.model_calls,
        "duration_seconds": result.duration_seconds,
        "memory_hit": bool(getattr(result, "memory_hit", False)),
        "diagnostic": dataclasses.asdict(diagnostic) if diagnostic is not None else None,
        "escalation_reason": getattr(result, "escalation_reason", None),
    }


def normalize_program_results(program_results: dict[str, dict]) -> dict[str, dict]:
    """Flatten `LeafOrchestrator.run()`'s nested
    `{program: {unit: result}}` into `{composite_id: normalized}` -- the
    exact shape written to a multi-program run's `orchestrator_state.json`
    and the shape `weaver/agent/metrics.py` already knows how to read."""
    flat: dict[str, dict] = {}
    for program_name, units in program_results.items():
        for unit_id, result in units.items():
            entry = normalize_unit_result(result, program_name=program_name)
            flat[entry["composite_id"]] = entry
    return flat


def all_committed(program_results: dict[str, dict]) -> bool:
    """The one definition of "this multi-program run succeeded", shared by
    `weaver/cli.py`'s exit code and the backend's lifecycle. A run with no
    programs at all is not a success -- there is nothing to have verified."""
    if not program_results:
        return False
    return all(
        r.status == "committed"
        for units in program_results.values()
        for r in units.values()
    )


def _decimal_safe(value):
    return str(value) if isinstance(value, Decimal) else value


def normalize_divergence_report(result) -> dict | None:
    """A `weaver.report.Report` (file-based) or a
    `weaver.agent.subprogram_verify.SubprogramVerifyResult` (subprogram)
    rendered for the divergence view.

    The file-based branch passes `Report.to_json()` through verbatim and
    tags it `kind: "file_based"` -- that payload is already the frontend's
    DivergenceTable contract and must not be reshaped. The subprogram
    branch has no `to_json()` and no record/field/offset concept at all:
    its divergences are witness input/output triples. It is rendered with
    its own field names under `kind: "subprogram"` rather than being
    forced into record-index columns it has no values for, which would
    mean inventing data.
    """
    if result is None:
        return None
    if hasattr(result, "to_json"):
        payload = json.loads(result.to_json())
        payload["kind"] = "file_based"
        return payload
    return {
        "kind": "subprogram",
        "compiled": result.compiled,
        "compile_error": result.compile_error,
        "divergence_count": result.divergence_count,
        "divergence_list_capped": False,
        "divergences": [
            {
                "witness_input": _decimal_safe(d.witness_input),
                "oracle_output": _decimal_safe(d.oracle_output),
                "candidate_output": _decimal_safe(d.candidate_output),
            }
            for d in result.divergences
        ],
    }


def divergence_source(result):
    """The verification artefact a normalized unit's divergence view is
    built from: `UnitResult.last_report` or
    `SubprogramUnitResult.verify_result`. Returns None when the unit has
    neither (e.g. a synthesis failure that never reached verification)."""
    report = getattr(result, "last_report", None)
    if report is not None:
        return report
    return getattr(result, "verify_result", None)


__all__ = [
    "COMPOSITE_SEP",
    "all_committed",
    "composite_id",
    "divergence_source",
    "normalize_divergence_report",
    "normalize_program_results",
    "normalize_unit_result",
    "result_kind",
    "split_composite",
]
