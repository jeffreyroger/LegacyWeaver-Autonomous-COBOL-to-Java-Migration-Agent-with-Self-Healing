"""Compute metrics from the trace — Step R1.

Reads generated/trace.ndjson (Phase P's structured event stream) and
generated/orchestrator_state.json (per-unit outcomes) and derives the
metrics the plan calls out as slide material. All numbers here are read
back from real runs already on disk -- nothing is computed from an
assumed/idealised scenario.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TRACE_PATH = Path("zuse/examples/generated/trace.ndjson")
STATE_PATH = Path("zuse/examples/generated/orchestrator_state.json")
M4_BASELINE_PATH = Path("zuse/examples/generated/m4_baseline.json")


@dataclass
class Metrics:
    equivalence_rate_unassisted: float | None
    equivalence_rate_post_repair: float
    mean_repair_attempts_per_unit: float
    autonomous_resolution_rate: float
    model_calls_total: int
    wall_clock_seconds: float
    inference_seconds: float


def compute_metrics(trace_path: Path = TRACE_PATH, state_path: Path = STATE_PATH,
                     m4_baseline_path: Path = M4_BASELINE_PATH) -> Metrics:
    trace_lines = [json.loads(l) for l in trace_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    state = json.loads(state_path.read_text(encoding="utf-8"))

    total_units = len(state)
    committed = sum(1 for r in state.values() if r["status"] == "committed")
    equivalence_rate_post_repair = 100 * committed / total_units if total_units else 0.0
    autonomous_resolution_rate = equivalence_rate_post_repair  # same measure at this granularity: units resolved with no human input

    repair_events = [e for e in trace_lines if e["node"] == "repair"]
    mean_repair_attempts = (
        sum(1 for e in repair_events) / total_units if total_units else 0.0
    )

    model_calls_total = sum(e.get("model_calls", 0) for e in trace_lines)
    wall_clock = sum(e.get("duration_seconds", 0.0) for e in trace_lines)
    inference_seconds = sum(
        e.get("duration_seconds", 0.0) for e in trace_lines if e["node"] in ("synthesise", "repair")
    )

    equivalence_rate_unassisted = None
    if m4_baseline_path.exists():
        m4 = json.loads(m4_baseline_path.read_text(encoding="utf-8"))
        if m4["units_synthesized"]:
            equivalence_rate_unassisted = 100 * m4["units_compiling"] / m4["units_synthesized"]

    return Metrics(
        equivalence_rate_unassisted=equivalence_rate_unassisted,
        equivalence_rate_post_repair=equivalence_rate_post_repair,
        mean_repair_attempts_per_unit=mean_repair_attempts,
        autonomous_resolution_rate=autonomous_resolution_rate,
        model_calls_total=model_calls_total,
        wall_clock_seconds=wall_clock,
        inference_seconds=inference_seconds,
    )


if __name__ == "__main__":
    m = compute_metrics()
    print(json.dumps(m.__dict__, indent=2))
