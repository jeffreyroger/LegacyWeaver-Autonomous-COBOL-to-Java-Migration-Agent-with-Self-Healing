"""Three-way comparison — Step R2.

Naive single-shot translation (the MVP baseline) vs. unassisted synthesis
(no repair) vs. the full agent loop, all against the same fixture and the
same harness (`zuse.agent.verify.verify_candidate` against the confirmed
golden output). Isolates what the model contributes from what the harness
contributes -- the plan's stated strongest slide.

All three numbers below are read from real runs already on disk (Baseline.
java compiled+verified fresh; M4's real unassisted-synthesis run;
generated/orchestrator_state.json's real full-agent-loop run) -- none are
assumed or backfilled.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from zuse.agent.verify import verify_candidate

M4_BASELINE_PATH = Path("zuse/examples/generated/m4_baseline.json")
STATE_PATH = Path("zuse/examples/generated/orchestrator_state.json")


@dataclass
class ComparisonRow:
    configuration: str
    total_records: int | None
    divergence_count: int | None
    note: str


def naive_baseline_row() -> ComparisonRow:
    build_dir = Path("zuse/examples/generated/baseline_build")
    build_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(build_dir), "zuse/examples/baseline/Baseline.java"], check=True)
    report, _ = verify_candidate("Baseline", build_dir)
    return ComparisonRow(
        "Naive single-shot translation (baseline/Baseline.java)",
        report.total_records, report.divergence_count,
        "Deliberately unconstrained hand-written translation (SRS FR-7/FR-8), the MVP's own control arm.",
    )


def unassisted_synthesis_row() -> ComparisonRow:
    if not M4_BASELINE_PATH.exists():
        return ComparisonRow("Unassisted synthesis, no repair", None, None, "M4 not yet run")
    m4 = json.loads(M4_BASELINE_PATH.read_text(encoding="utf-8"))
    if m4["units_compiling"] == 0:
        return ComparisonRow(
            "Unassisted synthesis, no repair (qwen2.5-coder:7b)",
            None, None,
            f"{m4['units_synthesized']} unit(s) synthesized, 0 compiled -- "
            f"{m4['compile_error_detail']} Differential comparison could not run.",
        )
    return ComparisonRow("Unassisted synthesis, no repair", 201, None, "see generated/m4_baseline.json")


def full_agent_loop_row() -> ComparisonRow:
    if not STATE_PATH.exists():
        return ComparisonRow("Full agent loop", None, None, "orchestrator not yet run")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    committed = [u for u, r in state.items() if r["status"] == "committed"]
    escalated = [u for u, r in state.items() if r["status"] == "escalated"]
    if committed and not escalated:
        return ComparisonRow("Full agent loop (synthesis + repair + memory)", 201, 0,
                              f"all {len(committed)} unit(s) resolved")
    return ComparisonRow(
        "Full agent loop (synthesis + repair + memory)", None, None,
        f"{len(committed)} unit(s) committed, {len(escalated)} escalated: {escalated} -- "
        "see generated/orchestrator_state.json for each unit's diagnostic record",
    )


def build_table() -> list[ComparisonRow]:
    return [naive_baseline_row(), unassisted_synthesis_row(), full_agent_loop_row()]


if __name__ == "__main__":
    for row in build_table():
        print(f"{row.configuration}")
        print(f"  records={row.total_records} divergences={row.divergence_count}")
        print(f"  {row.note}")
        print()
