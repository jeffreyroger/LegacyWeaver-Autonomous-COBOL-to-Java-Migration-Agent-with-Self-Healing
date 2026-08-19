"""Trace harvesting — GRAPH_PLAN.md M5.

`parse_trace()` turns captured stdout (GnuCOBOL's DISPLAY output, which
instrument.py's injected lines write to) into `UnitFixture`s. Record index
is inferred by counting ENTRY-block occurrences per paragraph in the order
they appear in the trace, rather than by instrumenting a counter into
WORKING-STORAGE -- the program's own control flow already guarantees one
ENTRY block followed by one EXIT block per invocation, so sequential
grouping is sufficient and avoids touching the oracle's data layout at
all (Non-Negotiable Design Decision 1, GRAPH_PLAN.md §1).

`harvest()` wraps `weaver.execution.run_oracle` around it, reusing that
module's existing isolated-directory subprocess mechanics rather than
duplicating them (GRAPH_PLAN.md §4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from weaver.execution import run_oracle

_TRACE_RE = re.compile(
    r"^WEAVER-TRACE:(?P<paragraph>[A-Z0-9-]+):(?P<phase>ENTRY|EXIT):(?P<field>[A-Z0-9-]+)=(?P<value>.*)$"
)


@dataclass(frozen=True)
class UnitFixture:
    paragraph_id: str
    record_index: int
    input_state: dict[str, str] = field(default_factory=dict)
    output_state: dict[str, str] = field(default_factory=dict)


def parse_trace(stdout: str) -> list[UnitFixture]:
    fixtures: list[UnitFixture] = []
    counters: dict[str, int] = {}
    # per-paragraph in-progress record: accumulated fields + which phase
    # was last seen (so a new ENTRY after an EXIT means "start the next
    # record", not "keep adding to this one").
    open_records: dict[str, dict] = {}

    def _flush(pid: str) -> None:
        state = open_records.get(pid)
        if state is None or (not state["input"] and not state["output"]):
            return
        idx = counters.get(pid, 0)
        fixtures.append(UnitFixture(pid, idx, dict(state["input"]), dict(state["output"])))
        counters[pid] = idx + 1
        state["input"] = {}
        state["output"] = {}
        state["phase"] = None

    for line in stdout.splitlines():
        m = _TRACE_RE.match(line)
        if not m:
            continue
        pid, phase, field_name, value = (
            m.group("paragraph"), m.group("phase"), m.group("field"), m.group("value"),
        )
        state = open_records.setdefault(pid, {"input": {}, "output": {}, "phase": None})
        if phase == "ENTRY" and state["phase"] == "EXIT":
            _flush(pid)
            state = open_records[pid]
        if phase == "ENTRY":
            state["input"][field_name] = value
        else:
            state["output"][field_name] = value
        state["phase"] = phase

    for pid in open_records:
        _flush(pid)

    return fixtures


def harvest(binary_path: Path, work_dir: Path, input_path: Path, output_filename: str) -> list[UnitFixture]:
    """Run the instrumented binary once and parse its trace output. The
    binary must already be an instrumented, separately compiled variant
    (see instrument.py) -- this function never distinguishes an
    instrumented binary from the oracle; that separation is the caller's
    responsibility, per Non-Negotiable Design Decision 1."""
    result = run_oracle(binary_path, work_dir, input_path, output_filename)
    return parse_trace(result.stdout)
