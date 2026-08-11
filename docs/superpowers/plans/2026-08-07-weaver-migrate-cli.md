# `weaver migrate` CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `weaver migrate` — the command SRS §3.9.1 **[MUST]** specifies as the entry point to the autonomous migration agent — so the Phase 2 orchestrator is drivable from the terminal exactly as the spec defines it.

**Architecture:** The orchestrator already exists and is already driven by `backend/runs.py`. This plan adds no second way to run it. It (a) fixes the parameter-plumbing defects that make orchestrator arguments silently inert, (b) adds the `weaver migrate` surface verbatim from §3.9.1, (c) satisfies FR-8.1's run-directory contract and §3.9.4's streaming-status **[MUST]**, and (d) proves CLI and backend serve identical metrics.

**Tech Stack:** Python 3.11+, `argparse` (existing `weaver/cli.py` subparser pattern), `rich` (existing console rendering), `pytest`.

---

## Specification conformance findings

The full `LEGACYWEAVER_SRS.md` is now available, which **invalidates the surface proposed in the previous revision of this plan** (`weaver agent run` — an inference made while the SRS was missing). §3.9.1 is normative and reads:

```
weaver migrate  <program.cbl> [--copybook DIR] [--data FILE] [--out DIR]
                [--max-repairs 3] [--model qwen2.5-coder:7b] [--seed 42]
weaver verify   --cobol <src> --java <src> --data <file>
weaver baseline <program.cbl>
weaver replay   <run_id>
weaver memory   list | export | import <file>
weaver report   <run_id>
```

Auditing the repo against it surfaced six deviations. **This plan fixes 1, 2 and 3; the rest are logged for separate tracking** (see "Deviations logged, not fixed here").

| # | Requirement | Repo today | Fixed here |
|---|---|---|---|
| 1 | §3.9.1 `weaver migrate` **[MUST]** | Absent — orchestrator only reachable via `python -m weaver.agent.orchestrator` | **Yes** — Tasks 2–5 |
| 2 | §3.9.4 CLI streams unit status with colour coding **[MUST]** | No streaming CLI path exists | **Yes** — Task 4 |
| 3 | FR-8.1 trace at `runs/<run_id>/trace.jsonl` | `generated/trace.ndjson` — wrong directory *and* wrong filename | **Yes** — Task 3 |
| 4 | §3.9.1 `weaver verify --cobol --java --data` | Implemented with **positional** args (`cli.py:39-43`) | Task 7 (compatible) |
| 5 | §3.9.1 `weaver baseline` (FR-8.3), `weaver replay` (FR-8.4), `weaver memory` — all **[MUST]** | Absent as commands | No — logged |
| 6 | NFR-S1 / §3.9.3 generated code runs only in containers | `javac`/`java` execute on the **host** (`attribution.py:52`) | No — logged |

**Note on BACKEND_PLAN.md:47.** It audits "§3.9.1 CLI command surface — **PASS**". Findings 1, 4 and 5 show that audit was incorrect: at the time it was written `migrate`, `baseline`, `replay` and `memory` did not exist and `verify`'s signature did not match. Correct the row when Task 7 lands.

## Global Constraints

From CLAUDE.md and the full SRS. Every task's requirements implicitly include these.

- **Offline and credential-free (DC-1, NFR-8, NFR-10, §3.9.2).** The only network call is to the loopback inference endpoint, validated as loopback at startup — a non-loopback host **shall abort the run**.
- **The comparison contract is absolute (FR-10, DC-4).** Byte-for-byte only. Nothing here participates in the equivalence determination; the CLI renders results, it never decides them.
- **Classification is deterministic (FR-13, DC-4).** No model in the classification path.
- **Exact decimal arithmetic (DC-3).** `decimal.Decimal`, never binary float.
- **Layouts are data (NFR-14).** No hardcoded offsets.
- **Import direction is enforced.** `weaver/` must never import `backend/` — `tests/test_backend_import_direction.py` asserts it, and BACKEND_PLAN.md:116 makes it load-bearing. Shared constants move *into* `weaver/`.
- **Scope stays disclosed (FR-20, DC-6).** No README or `--help` text may claim behaviour that isn't implemented and passing its test. This explicitly includes not implying `baseline`/`replay`/`memory` exist.
- **Spec defaults are exact.** `--max-repairs 3`, `--model qwen2.5-coder:7b`, `--seed 42` — copy verbatim from §3.9.1.
- **NFR-P4:** end-to-end migration ≤ 12 min without replay, ≤ 60 s with `--replay`.
- **Load-bearing numbers:** 201 records, 132 divergences, golden checksum `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`. Changing one means something broke.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `weaver/agent/runspec.py` | **New** — single definition of a run's parameters, one field per §3.9.1 flag | Create |
| `weaver/agent/attribution.py` | Assemble + compile + verify one unit | Modify — accept `spec` instead of module constants |
| `weaver/agent/repair_loop.py` | Repair attempts | Modify — `MAX_ATTEMPTS` becomes `spec.max_repairs` |
| `weaver/agent/inference.py` | Inference client | Modify — `SEED` becomes a per-request parameter |
| `weaver/agent/orchestrator.py` | State machine | Modify — take `RunSpec`, use `scaffold_path`, add `RUNS_ROOT` |
| `weaver/cli.py` | Command surface | Modify — add `migrate`; Task 7 adds `verify` flag form |
| `backend/runs.py` | Service run lifecycle | Modify — pass `data_file` through instead of ignoring it |
| `tests/test_param_plumbing.py` | **New** — regression: supplied params reach the verifier | Create |
| `tests/test_migrate_cli.py` | **New** — §3.9.1 surface, exit codes, run-dir contract | Create |

---

### Task 1: Make run parameters actually take effect

**Why this is first:** §3.9.1 requires `migrate` to accept seven parameters. Four of them are, today, module constants that no caller can influence — a `migrate` built on top would parse the user's flags and silently ignore them.

**Defect 1 — `scaffold_path` is inert.** `Orchestrator.scaffold_path` is a required field (`orchestrator.py:52`), passed by all three call sites (`orchestrator.py:237`, `backend/runs.py:223`, `backend/runs.py:303`) — and read nowhere. `attribution.py:46` uses its own module constant `SCAFFOLD_PATH` (`attribution.py:24`) instead.

**Defect 2 — the input data file is inert.** `backend/runs.py:78-79` *rejects* a request without `data_file` and writes it to `params.json` as the NFR-D1 reproducibility record (`runs.py:88`) — but never passes it to the `Orchestrator`, which has no such field. The real path is the constant `INPUT_DATA` at `verify.py:25`, reached via `verify_candidate`'s defaults at `attribution.py:56`. **Today `params.json` records an input file that did not influence the run** — a direct DC-5 violation.

**Defect 3 — `--max-repairs` has no hook.** `MAX_ATTEMPTS = 3` is a module constant (`repair_loop.py:33`).

**Defect 4 — `--seed` and `--replay` have no hook.** `SEED` is a module constant (`inference.py:51`), and `orchestrator.py:67` constructs `InferenceClient(cache_dir=...)` with `replay_only` left at its default, so FR-8.4's replay mode is unreachable from any caller.

**Files:**
- Create: `weaver/agent/runspec.py`, `tests/test_param_plumbing.py`
- Modify: `weaver/agent/attribution.py:37-57`, `weaver/agent/orchestrator.py:49-68`, `backend/runs.py:221-229`, `backend/runs.py:301-310`

**Interfaces:**
- Produces: `weaver.agent.runspec.RunSpec` — frozen dataclass, fields `cobol_source: Path`, `copybook_dir: Path | None`, `input_data: Path`, `out_dir: Path | None`, `golden_output: Path`, `scaffold_path: Path`, `memory_store_path: Path`, `max_repairs: int`, `model: str`, `seed: int`, `replay: bool`; classmethod `default()`; methods `replace(**changes)`, `to_dict()`.
- Produces: `verify_unit(unit_id, candidate_body, work_dir, *, spec: RunSpec | None = None) -> AttributionResult`.
- Produces: `Orchestrator(spec: RunSpec, trace_path, state_path, on_event, cancel_requested, fresh_trace)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_param_plumbing.py`:

```python
"""Regression tests: parameters the caller supplies must actually reach the
code that consumes them. Before 2026-08-07 scaffold_path was accepted and
never read, and data_file was recorded in params.json without influencing
the run -- so the NFR-D1 reproducibility record described parameters that
had no effect (DC-5). SRS SS3.9.1 requires `weaver migrate` to expose seven
such parameters; each must be threaded, not defaulted from a constant."""
from pathlib import Path

import pytest

from weaver.agent.runspec import RunSpec


def test_defaults_match_srs_3_9_1():
    """Defaults are copied verbatim from SRS SS3.9.1."""
    spec = RunSpec.default()
    assert spec.max_repairs == 3
    assert spec.model == "qwen2.5-coder:7b"
    assert spec.seed == 42
    assert spec.replay is False


def test_default_paths_match_repo_fixtures():
    spec = RunSpec.default()
    assert spec.input_data == Path("fixtures/data/accounts.dat")
    assert spec.golden_output == Path("fixtures/data/expected/golden_interest.out")
    assert spec.scaffold_path == Path("generated/Scaffold.java")


def test_verify_unit_reads_the_scaffold_it_was_given(tmp_path, monkeypatch):
    sentinel = tmp_path / "Sentinel.java"
    sentinel.write_text("// SENTINEL SCAFFOLD\n")
    spec = RunSpec.default().replace(scaffold_path=sentinel)

    seen = {}

    def fake_assemble(scaffold_text, bodies):
        seen["text"] = scaffold_text
        raise RuntimeError("stop after assemble")

    monkeypatch.setattr("weaver.agent.attribution.assemble", fake_assemble)

    from weaver.agent.attribution import verify_unit

    with pytest.raises(RuntimeError, match="stop after assemble"):
        verify_unit("PROCESS-RECORD", "// body", tmp_path, spec=spec)

    assert "SENTINEL SCAFFOLD" in seen["text"]


def test_verify_candidate_uses_injected_input_data(tmp_path, monkeypatch):
    from weaver.agent import verify as verify_mod

    golden = tmp_path / "golden.out"
    golden.write_text("")
    data = tmp_path / "custom.dat"
    data.write_text("")

    seen = {}

    def fake_run_candidate(main_class, classpath, work_dir, input_data, output_filename):
        seen["input_data"] = input_data
        raise RuntimeError("stop after run_candidate")

    monkeypatch.setattr(verify_mod, "run_candidate", fake_run_candidate)

    with pytest.raises(RuntimeError, match="stop after run_candidate"):
        verify_mod.verify_candidate("Scaffold", tmp_path, golden_output=golden, input_data=data)

    assert seen["input_data"] == data
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_param_plumbing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'weaver.agent.runspec'`

- [ ] **Step 3: Create the `RunSpec` type**

Create `weaver/agent/runspec.py`:

```python
"""The single definition of what parameters constitute a run.

One field per SRS SS3.9.1 `weaver migrate` flag. Before this existed,
scaffold_path was accepted by Orchestrator and never read, the input data
path was a module constant no caller could influence, MAX_ATTEMPTS and SEED
were module constants, and replay_only was unreachable -- so backend/runs.py
recorded a `data_file` in params.json that had no effect on the run
(DC-5 / NFR-D1). Every run parameter now lives here and is threaded
explicitly.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

# Defaults copied verbatim from SRS SS3.9.1.
DEFAULT_MAX_REPAIRS = 3
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_SEED = 42

DEFAULT_COBOL_SOURCE = Path("fixtures/cobol/interest.cob")
DEFAULT_INPUT_DATA = Path("fixtures/data/accounts.dat")
DEFAULT_GOLDEN_OUTPUT = Path("fixtures/data/expected/golden_interest.out")
DEFAULT_SCAFFOLD_PATH = Path("generated/Scaffold.java")
DEFAULT_MEMORY_STORE = Path("generated/failure_memory.json")


@dataclass(frozen=True)
class RunSpec:
    cobol_source: Path = DEFAULT_COBOL_SOURCE
    copybook_dir: Path | None = None
    input_data: Path = DEFAULT_INPUT_DATA
    out_dir: Path | None = None
    golden_output: Path = DEFAULT_GOLDEN_OUTPUT
    scaffold_path: Path = DEFAULT_SCAFFOLD_PATH
    memory_store_path: Path = DEFAULT_MEMORY_STORE
    max_repairs: int = DEFAULT_MAX_REPAIRS
    model: str = DEFAULT_MODEL
    seed: int = DEFAULT_SEED
    replay: bool = False

    @classmethod
    def default(cls) -> RunSpec:
        return cls()

    def replace(self, **changes: object) -> RunSpec:
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, str | int | bool | None]:
        """Serialised form written to a run directory's params.json
        (the NFR-D1 reproducibility record)."""
        out: dict[str, str | int | bool | None] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            out[f.name] = str(value) if isinstance(value, Path) else value
        return out
```

- [ ] **Step 4: Confirm `verify.py` needs no change**

`verify_candidate` (`weaver/agent/verify.py:29-32`) already accepts `golden_output` and `input_data` as defaulted parameters — the bug is that `attribution.py:56` never passes them. Re-read lines 29–37 and confirm; make no edit.

- [ ] **Step 5: Thread the spec through `verify_unit`**

In `weaver/agent/attribution.py`, add the import:

```python
from weaver.agent.runspec import RunSpec
```

Replace `verify_unit` (lines 37–57):

```python
def verify_unit(unit_id: str, candidate_body: str, work_dir: Path,
                *, spec: RunSpec | None = None) -> AttributionResult:
    """Assemble the reference implementation with `unit_id`'s body replaced
    by `candidate_body`, compile, and verify. All other units keep their
    known-correct reference bodies, so any resulting divergence is
    attributable to `unit_id` alone.

    `spec` supplies the scaffold, input data, and golden output. Defaults to
    RunSpec.default() so existing call sites keep working; it is threaded
    explicitly so a caller-supplied path is never silently ignored.
    """
    spec = spec or RunSpec.default()

    bodies = {"PROCESS-RECORD": REFERENCE_BODY_PATH.read_text()}
    bodies[unit_id] = candidate_body  # overwrite the unit under test

    assembled = assemble(spec.scaffold_path.read_text(), bodies)
    src_path = work_dir / "Scaffold.java"
    build_dir = work_dir / "build"
    work_dir.mkdir(parents=True, exist_ok=True)
    src_path.write_text(assembled)

    proc = subprocess.run(["javac", "-d", str(build_dir), str(src_path)], capture_output=True, text=True)
    if proc.returncode != 0:
        return AttributionResult(unit_id, Report(unit_id, 0), [], False, proc.stderr)

    report, classifications = verify_candidate(
        "Scaffold", build_dir,
        golden_output=spec.golden_output,
        input_data=spec.input_data,
    )
    return AttributionResult(unit_id, report, classifications, True, None)
```

Keep the `SCAFFOLD_PATH` constant (line 24) — the `__main__` block at line 60 still uses it — but `verify_unit` no longer consults it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_param_plumbing.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Give `Orchestrator` a spec and use it**

In `weaver/agent/orchestrator.py`, add the import and a runs root beside the existing path constants (lines 33–34):

```python
from weaver.agent.runspec import RunSpec

RUNS_ROOT = Path("runs")  # FR-8.1: runs/<run_id>/trace.jsonl
```

Replace the `cobol_source` / `scaffold_path` / `memory_store_path` fields (lines 51–53) with a single spec:

```python
@dataclass
class Orchestrator:
    spec: RunSpec = field(default_factory=RunSpec.default)
    trace_path: Path = TRACE_PATH
    state_path: Path = STATE_PATH
    results: dict[str, UnitResult] = field(default_factory=dict)
    on_event: Callable[[dict], None] | None = None
    cancel_requested: threading.Event | None = None
    fresh_trace: bool = True

    @property
    def cobol_source(self) -> Path:
        return self.spec.cobol_source
```

In `__post_init__` (lines 67–68), honour the replay and memory settings:

```python
        self.client = InferenceClient(
            cache_dir=Path("generated/model_cache"),
            replay_only=self.spec.replay,
        )
        self.memory = FailureMemory(self.spec.memory_store_path)
```

Pass the spec to every `verify_unit(` and `repair_unit(` call in this file (`repair_unit` is called at line 158):

```python
result = verify_unit(unit.identifier, body, work_dir, spec=self.spec)
```

```python
outcome = repair_unit(unit.identifier, unit, body, result, self.client, spec=self.spec)
```

- [ ] **Step 8: Make `max_repairs` configurable**

In `weaver/agent/repair_loop.py`, keep `MAX_ATTEMPTS = 3` (line 33) as the default source, add a keyword-only `spec` parameter to `repair_unit`, and replace the loop bound at line 78 and the message at line 169:

```python
    spec = spec or RunSpec.default()
    max_repairs = spec.max_repairs
    ...
    for attempt_number in range(1, max_repairs + 1):
    ...
        f"attempt budget ({max_repairs}) exhausted",
```

Add the import:

```python
from weaver.agent.runspec import RunSpec
```

- [ ] **Step 9: Make `seed` and `model` configurable**

In `weaver/agent/inference.py`, `InferenceRequest.model` already exists (line 42) but `SEED` is baked into `payload()` (line 51). Add a `seed` field defaulting to the module constant and use it:

```python
@dataclass
class InferenceRequest:
    ...
    model: str = DEFAULT_MODEL
    seed: int = SEED
```

and in `payload()`:

```python
                "seed": self.seed,
```

- [ ] **Step 10: Update the orchestrator's `__main__` block**

Replace lines 235–239 of `orchestrator.py`:

```python
if __name__ == "__main__":
    orchestrator = Orchestrator(spec=RunSpec.default())
```

- [ ] **Step 11: Update the backend to pass `data_file` through**

In `backend/runs.py`, add the import:

```python
from weaver.agent.runspec import RunSpec
```

Replace both `Orchestrator(...)` constructions (lines 221–229 and 301–310):

```python
                spec = RunSpec.default().replace(
                    cobol_source=Path(record.request.cobol_source),
                    input_data=Path(record.request.data_file),
                )
                orchestrator = Orchestrator(
                    spec=spec,
                    trace_path=record.trace_path,
                    state_path=record.state_path,
                    on_event=lambda event: record.event_bus.publish(event),
                    cancel_requested=record.cancel_requested,
                )
```

The second site (line 301, the resume path) additionally keeps `fresh_trace=False`.

- [ ] **Step 12: Confirm no other caller broke**

Run: `grep -rn "Orchestrator(\|verify_unit(\|repair_unit(" --include=*.py . | grep -v "def \|class "`
Expected: only the sites edited above. The two `Orchestrator(` hits in `tests/test_memory_writeback.py:92,128` construct a local `_FakeOrchestrator`, not the real class, and are unaffected.

- [ ] **Step 13: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all previously-passing tests still pass; `test_backend_import_direction.py` still passes (we added `weaver → weaver` imports, never `weaver → backend`).

- [ ] **Step 14: Commit**

```bash
git add weaver/agent/runspec.py weaver/agent/attribution.py weaver/agent/orchestrator.py weaver/agent/repair_loop.py weaver/agent/inference.py backend/runs.py tests/test_param_plumbing.py
git commit -m "fix: thread run parameters through instead of reading module constants

scaffold_path was accepted and never read, data_file was recorded in
params.json without influencing the run (DC-5/NFR-D1), and max_repairs,
seed and replay had no caller hook at all. Introduces RunSpec as the single
definition of a run's parameters, one field per SRS 3.9.1 migrate flag."
```

---

### Task 2: Add the `weaver migrate` surface from §3.9.1

**Files:**
- Modify: `weaver/cli.py:34-48` (parser)
- Create: `tests/test_migrate_cli.py`

**Interfaces:**
- Consumes: `RunSpec` (Task 1).
- Produces: `weaver.cli.build_migrate_spec(args) -> RunSpec`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_cli.py`:

```python
"""Surface tests for `weaver migrate` (SRS SS3.9.1). These never invoke the
real orchestrator -- they assert the CLI parses arguments into the RunSpec
the orchestrator is constructed with, which is the property that broke
before: a flag the user passes must not be silently dropped."""
from pathlib import Path

from weaver.cli import build_migrate_spec, build_parser


def test_migrate_takes_a_positional_program():
    args = build_parser().parse_args(["migrate", "prog.cbl"])
    assert args.command == "migrate"
    assert args.program == Path("prog.cbl")


def test_migrate_defaults_match_srs_3_9_1():
    args = build_parser().parse_args(["migrate", "prog.cbl"])
    spec = build_migrate_spec(args)
    assert spec.max_repairs == 3
    assert spec.model == "qwen2.5-coder:7b"
    assert spec.seed == 42
    assert spec.replay is False


def test_migrate_flags_reach_the_spec():
    args = build_parser().parse_args([
        "migrate", "prog.cbl",
        "--copybook", "cb/",
        "--data", "custom/input.dat",
        "--out", "outdir/",
        "--max-repairs", "5",
        "--model", "qwen2.5-coder:14b",
        "--seed", "7",
    ])
    spec = build_migrate_spec(args)
    assert spec.cobol_source == Path("prog.cbl")
    assert spec.copybook_dir == Path("cb/")
    assert spec.input_data == Path("custom/input.dat")
    assert spec.out_dir == Path("outdir/")
    assert spec.max_repairs == 5
    assert spec.model == "qwen2.5-coder:14b"
    assert spec.seed == 7


def test_existing_commands_still_parse():
    """migrate must not disturb the existing surface (SS3.9.4: the terminal
    path stands alone)."""
    p = build_parser()
    assert p.parse_args(["verify", "a.cob", "B.java", "c.dat"]).command == "verify"
    assert p.parse_args(["report", "runs/abc"]).command == "report"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_migrate_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_migrate_spec' from 'weaver.cli'`

- [ ] **Step 3: Add the parser**

In `weaver/cli.py`, add the import:

```python
from weaver.agent.runspec import (
    DEFAULT_MAX_REPAIRS,
    DEFAULT_MODEL,
    DEFAULT_SEED,
    RunSpec,
)
```

and inside `build_parser()` before `return parser` (line 48):

```python
    # SRS 3.9.1: weaver migrate <program.cbl> [--copybook DIR] [--data FILE]
    #            [--out DIR] [--max-repairs 3] [--model qwen2.5-coder:7b] [--seed 42]
    migrate = sub.add_parser("migrate", help="Autonomously migrate a COBOL program to Java")
    migrate.add_argument("program", type=Path, help="COBOL program to migrate")
    migrate.add_argument("--copybook", type=Path, default=None, help="Copybook directory")
    migrate.add_argument("--data", type=Path, default=None, help="Input data file for verification")
    migrate.add_argument("--out", type=Path, default=None, help="Output directory for generated Java")
    migrate.add_argument("--max-repairs", type=int, default=DEFAULT_MAX_REPAIRS,
                         help="Maximum repair attempts per unit")
    migrate.add_argument("--model", default=DEFAULT_MODEL, help="Local inference model tag")
    migrate.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Inference seed")
    migrate.add_argument("--replay", action="store_true",
                         help="FR-8.4: serve model responses exclusively from cache")
    migrate.add_argument("--run-dir", type=Path, default=None,
                         help="Run directory (default: runs/<run_id>)")
    migrate.add_argument("--json", action="store_true",
                         help="Emit machine-readable JSON instead of streaming status")
```

- [ ] **Step 4: Add `build_migrate_spec`**

Add to `weaver/cli.py`, above `main`:

```python
def build_migrate_spec(args: argparse.Namespace) -> RunSpec:
    """Translate parsed `migrate` arguments into the RunSpec the orchestrator
    runs. Every flag must land in the spec -- a flag that parses but never
    reaches the orchestrator is the exact defect Task 1 fixed.
    """
    defaults = RunSpec.default()
    return RunSpec(
        cobol_source=args.program,
        copybook_dir=args.copybook,
        input_data=args.data or defaults.input_data,
        out_dir=args.out,
        golden_output=defaults.golden_output,
        scaffold_path=defaults.scaffold_path,
        memory_store_path=defaults.memory_store_path,
        max_repairs=args.max_repairs,
        model=args.model,
        seed=args.seed,
        replay=args.replay,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_migrate_cli.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add weaver/cli.py tests/test_migrate_cli.py
git commit -m "feat: add 'weaver migrate' command surface per SRS 3.9.1"
```

---

### Task 3: Execute the run into an FR-8.1 run directory

FR-8.1 **[MUST]**: *"Every state transition shall append a `TraceEvent` to `runs/<run_id>/trace.jsonl`."* The repo writes `generated/trace.ndjson` — wrong directory and wrong extension. `weaver report` (`cli.py:58-60`) reads `trace.ndjson` from a run dir, so both must move together.

**Files:**
- Modify: `weaver/cli.py` (add `run_migrate`, wire dispatch at lines 171–179)
- Modify: `weaver/agent/orchestrator.py` (`TRACE_PATH` filename)
- Modify: `weaver/cli.py:58` (`run_report` trace filename)
- Modify: `tests/test_migrate_cli.py`

**Interfaces:**
- Consumes: `build_migrate_spec` (Task 2), `RUNS_ROOT` (Task 1).
- Produces: `run_migrate(args) -> int`; a run directory containing `params.json`, `trace.jsonl`, `orchestrator_state.json`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migrate_cli.py`:

```python
def test_migrate_writes_an_fr_8_1_run_dir(tmp_path, monkeypatch):
    """FR-8.1: trace lands at <run_dir>/trace.jsonl, and the directory is
    exactly what `weaver report` reads."""
    import weaver.cli as cli_mod

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}

        def run(self):
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
            self.state_path.write_text("{}")
            return self.results

    monkeypatch.setattr(cli_mod, "Orchestrator", FakeOrchestrator)

    run_dir = tmp_path / "run1"
    args = cli_mod.build_parser().parse_args(
        ["migrate", "prog.cbl", "--run-dir", str(run_dir), "--json"]
    )
    assert cli_mod.run_migrate(args) == 0
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "orchestrator_state.json").exists()
    assert (run_dir / "params.json").exists()


def test_migrate_params_json_records_every_spec_field(tmp_path, monkeypatch):
    """NFR-D1: the reproducibility record must describe the run that
    actually happened -- every RunSpec field, no omissions."""
    import json

    import weaver.cli as cli_mod
    from weaver.agent.runspec import RunSpec

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}

        def run(self):
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
            self.state_path.write_text("{}")
            return self.results

    monkeypatch.setattr(cli_mod, "Orchestrator", FakeOrchestrator)

    run_dir = tmp_path / "run2"
    args = cli_mod.build_parser().parse_args(
        ["migrate", "prog.cbl", "--run-dir", str(run_dir), "--seed", "7", "--json"]
    )
    cli_mod.run_migrate(args)

    recorded = json.loads((run_dir / "params.json").read_text())
    assert set(recorded) == {f.name for f in dataclasses.fields(RunSpec)}
    assert recorded["seed"] == 7


def test_migrate_exit_code_1_when_a_unit_escalates(tmp_path, monkeypatch):
    import weaver.cli as cli_mod
    from weaver.agent.orchestrator import UnitResult

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}

        def run(self):
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
            self.state_path.write_text("{}")
            self.results = {
                "P1": UnitResult("P1", "committed", "body", 1, False, 0.5),
                "P2": UnitResult("P2", "escalated", None, 3, False, 1.5),
            }
            return self.results

    monkeypatch.setattr(cli_mod, "Orchestrator", FakeOrchestrator)

    args = cli_mod.build_parser().parse_args(
        ["migrate", "prog.cbl", "--run-dir", str(tmp_path / "run3"), "--json"]
    )
    assert cli_mod.run_migrate(args) == 1
```

Add `import dataclasses` to the top of the test file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_migrate_cli.py -v`
Expected: FAIL — `AttributeError: module 'weaver.cli' has no attribute 'run_migrate'`

- [ ] **Step 3: Rename the trace file to FR-8.1's name**

In `weaver/agent/orchestrator.py` line 34:

```python
TRACE_PATH = Path("generated/trace.jsonl")  # FR-8.1
```

In `weaver/cli.py` line 58:

```python
    trace_path = args.run_dir / "trace.jsonl"
```

In `backend/runs.py`, update `RunRecord.trace_path` (line 50–51):

```python
    @property
    def trace_path(self) -> Path:
        return self.run_dir / "trace.jsonl"
```

- [ ] **Step 4: Implement `run_migrate`**

Add to `weaver/cli.py`:

```python
def run_migrate(args: argparse.Namespace) -> int:
    """`weaver migrate` (SRS 3.9.1) -- drive the orchestrator from the terminal.

    Constructs the same Orchestrator backend/runs.py constructs and writes the
    same files into the run directory, so `weaver report <run_dir>` and the
    service's GET /runs/{id} read identical inputs (DC-5).
    """
    spec = build_migrate_spec(args)
    run_id = uuid.uuid4().hex
    run_dir = args.run_dir or (RUNS_ROOT / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    # NFR-D1 reproducibility record, written before the first unit executes.
    # Every value here actually influences the run -- see weaver/agent/runspec.py.
    (run_dir / "params.json").write_text(json.dumps(spec.to_dict(), indent=2))

    cancel_requested = threading.Event()
    orchestrator = Orchestrator(
        spec=spec,
        trace_path=run_dir / "trace.jsonl",
        state_path=run_dir / "orchestrator_state.json",
        on_event=None if args.json else _stream_event,
        cancel_requested=cancel_requested,
    )

    try:
        results = orchestrator.run()
    except KeyboardInterrupt:
        # Cooperative: ask the orchestrator to stop at the next unit boundary
        # rather than dying mid-unit (orchestrator.py: "never kill mid-unit,
        # which would leave containers running and state inconsistent").
        cancel_requested.set()
        console.print("[yellow]Cancellation requested; stopping at unit boundary.[/yellow]")
        return 130

    statuses = {r.status for r in results.values()}
    exit_code = 0 if statuses <= {"committed"} else 1

    if args.json:
        print(json.dumps({
            "run_dir": str(run_dir),
            "units": {uid: dataclasses.asdict(r) for uid, r in results.items()},
            "exit_code": exit_code,
        }, indent=2, default=str))
    else:
        _render_migrate_summary(run_dir, results)

    return exit_code
```

Add the imports to `cli.py`:

```python
import threading
import uuid

from weaver.agent.orchestrator import RUNS_ROOT, Orchestrator
```

- [ ] **Step 5: Wire the dispatch**

In `main` (lines 174–178), before the fallthrough:

```python
    if args.command == "migrate":
        return run_migrate(args)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_migrate_cli.py -v`
Expected: PASS (7 passed). Task 4 supplies `_stream_event` and `_render_migrate_summary`; until then define both as one-line stubs that `pass`, and remove the stubs in Task 4.

- [ ] **Step 7: Commit**

```bash
git add weaver/cli.py weaver/agent/orchestrator.py backend/runs.py tests/test_migrate_cli.py
git commit -m "feat: execute migrations into an FR-8.1 run directory (trace.jsonl)"
```

---

### Task 4: Stream unit status with colour coding (§3.9.4 **[MUST]**)

§3.9.4: *"The CLI shall stream unit status with colour coding."* This is a **[MUST]**, and it is why `Orchestrator.on_event` exists (`orchestrator.py:57`) — the callback is a tee for observers, documented at `orchestrator.py:78-80` as never blocking or altering what lands on disk.

**Files:**
- Modify: `weaver/cli.py`
- Modify: `tests/test_migrate_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migrate_cli.py`:

```python
def test_stream_event_emits_colour_coded_status(capsys):
    """SS3.9.4 [MUST]: stream unit status with colour coding."""
    from weaver.cli import _stream_event

    _stream_event({
        "timestamp": 1.0, "unit": "PROCESS-RECORD", "node": "repair",
        "action": "patch", "duration_seconds": 0.4, "model_calls": 1,
        "tokens": 120, "memory_hit": False, "outcome": "committed",
    })
    out = capsys.readouterr().out
    assert "PROCESS-RECORD" in out
    assert "repair" in out


def test_stream_event_never_raises_on_a_partial_event(capsys):
    """The callback is a tee for an observer and must never break a run --
    a malformed or partial event must not propagate an exception into the
    orchestrator's state machine."""
    from weaver.cli import _stream_event

    _stream_event({"unit": "P1"})  # every other key missing
    assert capsys.readouterr().out  # produced something, raised nothing
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_migrate_cli.py -k stream -v`
Expected: FAIL — `_stream_event` is a `pass` stub producing no output.

- [ ] **Step 3: Implement streaming and the summary**

Replace the Task 3 stubs in `weaver/cli.py`:

```python
# SS3.9.4 [MUST]: colour coding for streamed unit status.
_OUTCOME_COLOURS = {
    "committed": "green",
    "escalated": "red",
    "cancel": "yellow",
}


def _stream_event(event: dict) -> None:
    """Render one TraceEvent as a coloured status line (SS3.9.4).

    This is a tee for an observer: it must never raise, because an exception
    here would propagate into the orchestrator's state machine and abort a
    run over a display concern.
    """
    unit = event.get("unit", "?")
    node = event.get("node", "?")
    action = event.get("action", "")
    outcome = event.get("outcome", "")
    duration = event.get("duration_seconds", 0.0)

    colour = _OUTCOME_COLOURS.get(outcome, "cyan")
    for key, value in _OUTCOME_COLOURS.items():
        if key in str(outcome):
            colour = value
            break

    try:
        console.print(
            f"[dim]{duration:>6.2f}s[/dim] "
            f"[bold]{unit}[/bold] "
            f"[{colour}]{node}[/{colour}]"
            f"{' · ' + action if action else ''}"
            f"{' · ' + str(outcome) if outcome else ''}"
        )
    except Exception:  # noqa: BLE001 - display must never break a run
        pass


def _render_migrate_summary(run_dir: Path, results: dict) -> None:
    table = Table(title="Migration summary")
    table.add_column("Unit")
    table.add_column("Status")
    table.add_column("Model calls")
    table.add_column("Memory hit")
    table.add_column("Duration")
    for unit_id, r in results.items():
        colour = _OUTCOME_COLOURS.get(r.status, "cyan")
        table.add_row(
            unit_id,
            f"[{colour}]{r.status}[/{colour}]",
            str(r.model_calls),
            str(r.memory_hit),
            f"{r.duration_seconds:.1f}s",
        )
    console.print(table)
    console.print(f"[cyan]Run directory:[/cyan] {run_dir}")
    console.print(f"[cyan]Metrics:[/cyan] weaver report {run_dir}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_migrate_cli.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add weaver/cli.py tests/test_migrate_cli.py
git commit -m "feat: stream colour-coded unit status during migrate (SRS 3.9.4)"
```

---

### Task 5: Prove CLI and backend serve identical metrics (DC-5)

BACKEND_PLAN.md:312: *"API metrics are byte-identical to `weaver report` output. This is the DC-5 test — run it explicitly."*

**Files:**
- Modify: `tests/test_backend_service.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_backend_service.py`:

```python
def test_cli_report_and_api_metrics_are_byte_identical(tmp_path, capsys):
    """DC-5 (BACKEND_PLAN.md SS4.4): every number the API serves must be
    obtainable from the CLI. Both call compute_metrics on the same files; if
    they ever diverge, correctness is being decided in two places."""
    import dataclasses
    import json

    from weaver.agent.metrics import compute_metrics
    from weaver.cli import build_parser, run_report

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps({
            "timestamp": 1.0, "unit": "P1", "node": "perceive", "action": "segment",
            "duration_seconds": 0.1, "model_calls": 0, "tokens": 0,
            "memory_hit": False, "outcome": "1 paragraphs found",
        }) + "\n"
    )
    (run_dir / "orchestrator_state.json").write_text("{}")

    api_metrics = dataclasses.asdict(
        compute_metrics(run_dir / "trace.jsonl", run_dir / "orchestrator_state.json",
                        run_dir / "m4_baseline.json")
    )

    args = build_parser().parse_args(["report", str(run_dir)])
    assert run_report(args) == 0
    cli_metrics = json.loads(capsys.readouterr().out)

    assert cli_metrics == api_metrics
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_backend_service.py::test_cli_report_and_api_metrics_are_byte_identical -v`
Expected: PASS — both paths already call `compute_metrics`. If it FAILS, one path has acquired independent logic; that is a DC-4/DC-5 violation and must be fixed before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_backend_service.py
git commit -m "test: assert CLI report and API metrics are byte-identical (DC-5)"
```

---

### Task 6: Align `weaver verify` with §3.9.1 without breaking callers

§3.9.1 specifies `weaver verify --cobol <src> --java <src> --data <file>`. The implementation uses three positionals (`cli.py:39-43`). The README, `test_acceptance.py`, and BACKEND_PLAN.md:388 all invoke the positional form, so the flag form is added *alongside* rather than replacing it.

**Files:**
- Modify: `weaver/cli.py:39-43`
- Modify: `tests/test_migrate_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migrate_cli.py`:

```python
def test_verify_accepts_the_srs_flag_form():
    """SS3.9.1: weaver verify --cobol <src> --java <src> --data <file>."""
    args = build_parser().parse_args(
        ["verify", "--cobol", "a.cob", "--java", "B.java", "--data", "c.dat"]
    )
    assert args.cobol_source == Path("a.cob")
    assert args.java_candidate == Path("B.java")
    assert args.input_data == Path("c.dat")


def test_verify_still_accepts_the_positional_form():
    """The positional form is used by README, test_acceptance.py and
    BACKEND_PLAN.md:388 -- it must keep working."""
    args = build_parser().parse_args(["verify", "a.cob", "B.java", "c.dat"])
    assert args.cobol_source == Path("a.cob")
    assert args.java_candidate == Path("B.java")
    assert args.input_data == Path("c.dat")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_migrate_cli.py -k verify -v`
Expected: FAIL — `unrecognized arguments: --cobol`

- [ ] **Step 3: Accept both forms**

Replace the `verify` parser block in `weaver/cli.py` (lines 39–43):

```python
    # SRS 3.9.1 specifies the flag form; the positional form predates it and
    # is used by README, tests/test_acceptance.py and BACKEND_PLAN.md:388,
    # so both are accepted.
    verify = sub.add_parser("verify", help="Verify a Java candidate against a COBOL oracle")
    verify.add_argument("cobol_source_pos", type=Path, nargs="?", default=None,
                        metavar="cobol_source")
    verify.add_argument("java_candidate_pos", type=Path, nargs="?", default=None,
                        metavar="java_candidate")
    verify.add_argument("input_data_pos", type=Path, nargs="?", default=None,
                        metavar="input_data")
    verify.add_argument("--cobol", dest="cobol_flag", type=Path, default=None)
    verify.add_argument("--java", dest="java_flag", type=Path, default=None)
    verify.add_argument("--data", dest="data_flag", type=Path, default=None)
    verify.add_argument("--report", type=Path, default=Path("report.json"))
```

Then normalise the two forms in `main`, before dispatching to `run_verify`:

```python
def _normalise_verify_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Collapse SS3.9.1's flag form and the older positional form into one
    set of attributes run_verify can rely on."""
    args.cobol_source = args.cobol_flag or args.cobol_source_pos
    args.java_candidate = args.java_flag or args.java_candidate_pos
    args.input_data = args.data_flag or args.input_data_pos
    missing = [
        name for name, value in (
            ("cobol source", args.cobol_source),
            ("java candidate", args.java_candidate),
            ("input data", args.input_data),
        ) if value is None
    ]
    if missing:
        parser.error(
            "verify requires " + ", ".join(missing)
            + " (positionally, or via --cobol/--java/--data)"
        )
```

Call it from `main`:

```python
    if args.command == "verify":
        _normalise_verify_args(args, parser)
        return run_verify(args)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: all pass, including the pre-existing `test_acceptance.py` invocations of the positional form.

- [ ] **Step 5: Commit**

```bash
git add weaver/cli.py tests/test_migrate_cli.py
git commit -m "feat: accept SRS 3.9.1 flag form for 'weaver verify' alongside positionals"
```

---

### Task 7: Update documentation and correct the conformance ledger

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/specs/BACKEND_PLAN.md:47`

- [ ] **Step 1: Run the full suite and capture the result**

Run: `python -m pytest tests/ -v`
Expected: all pass; `test_full_pipeline_against_real_fixture` skips without `cobc`/`javac`.

- [ ] **Step 2: Update the README**

Replace the "Running the agent" section of `README.md`:

````markdown
### Running the agent

With [Ollama](https://ollama.com) running locally:

```bash
weaver migrate fixtures/cobol/interest.cob --data fixtures/data/accounts.dat
```

The orchestrator synthesizes a candidate, verifies it against the oracle,
and — if it doesn't verify — enters a repair loop, consulting failure
memory before each attempt so it doesn't retry a fix that's already known
not to work. Unit status streams with colour coding as the run proceeds,
and Ctrl-C stops cleanly at the next unit boundary.

```
--copybook DIR      copybook directory
--data FILE         input data file used for verification
--out DIR           output directory for generated Java
--max-repairs 3     repair attempts per unit
--model TAG         local inference model (default qwen2.5-coder:7b)
--seed 42           inference seed
--replay            serve model responses exclusively from cache
```

Each run writes `runs/<run_id>/` containing `params.json`, `trace.jsonl`,
and `orchestrator_state.json`. Read its metrics back with:

```bash
weaver report runs/<run_id>
```

That is the same object the local run service serves from `GET /runs/{id}` —
byte-identical by test, so no number depends on which surface you read it from.

Exit codes: `0` all units committed, `1` at least one unit escalated,
`130` cancelled.

**Not yet implemented:** `weaver baseline` (FR-8.3), `weaver replay <run_id>`
(FR-8.4 — the `--replay` flag on `migrate` works; the standalone command does
not), and `weaver memory list|export|import` (§3.9.1). Generated code is
compiled and executed on the host, not in the containers §3.9.3/NFR-S1
require.
````

- [ ] **Step 3: Record the parameter contract in CLAUDE.md**

Add to CLAUDE.md's hard rules:

```markdown
13. **Run parameters live in `RunSpec` and must actually take effect.**
    `weaver/agent/runspec.py` is the single definition of what parameters
    constitute a run, one field per SRS §3.9.1 `migrate` flag. Before
    2026-08-07, `Orchestrator.scaffold_path` was accepted and never read,
    the backend's required `data_file` was written into `params.json`
    without influencing the run (DC-5/NFR-D1), and `max_repairs`/`seed`/
    `replay` had no caller hook at all. Never add a run parameter that is
    accepted but not threaded to the code that consumes it;
    `tests/test_param_plumbing.py` guards this.
```

- [ ] **Step 4: Correct the backend conformance audit**

In `docs/specs/BACKEND_PLAN.md`, line 47, replace the §3.9.1 row:

```markdown
| §3.9.1 | CLI command surface | **PARTIAL** | `migrate`, `verify`, `report` implemented; `baseline`, `replay`, `memory` absent. Backend must not diverge from it. §3.4 |
```

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/specs/BACKEND_PLAN.md
git commit -m "docs: document 'weaver migrate' and correct the 3.9.1 conformance row"
```

---

## Deviations logged, not fixed here

These are real **[MUST]** gaps against the full SRS. They are out of scope for this plan and need their own tracking — do not let the README imply any of them works.

1. **`weaver baseline <program.cbl>` (FR-8.3, AC-7)** — single-shot whole-program translation with no verification or repair, to quantify the harness's contribution. `generated/m4_baseline.json` and `metrics.py`'s `m4_path` suggest partial groundwork exists; audit before planning.
2. **`weaver replay <run_id>` (FR-8.4)** — Task 2 exposes `--replay` on `migrate`, and `PromptCache(replay_only=True)` already implements the semantics, but the standalone command that replays a *recorded run by id* does not exist. NFR-P4's ≤ 60 s replay target is unmeasured.
3. **`weaver memory list | export | import <file>` (§3.9.1)** — `FailureMemory` exists; no CLI surface.
4. **NFR-S1 / §3.9.3 sandboxing** — the spec requires generated code to execute only in containers (`--network=none`, `--read-only`, `--memory=2g`, `--cpus=2`, 30 s kill). `attribution.py:52` runs `javac` directly on the host, and `weaver/execution.py` runs the compiled class on the host. This is the largest gap on the list and gates AC-11. CLAUDE.md rule 12 requires it stay explicitly marked not-implemented until built.
5. **`weaver report <run_id>` vs `<run_dir>`** — §3.9.1 says the argument is a run *id*; the implementation takes a filesystem path. Task 3 makes the default location `runs/<run_id>`, so accepting a bare id and resolving it under `RUNS_ROOT` is a small follow-up.

---

## Self-Review

**Spec coverage.** §3.9.1 `migrate` — Tasks 2–4. §3.9.1 `verify` flag form — Task 6. §3.9.4 streaming colour-coded status **[MUST]** — Task 4. FR-8.1 `runs/<run_id>/trace.jsonl` — Task 3. FR-8.4 `--replay` reachability — Task 1 Step 7. NFR-D1 reproducibility record — Task 3 Step 4, tested in Step 1. DC-5 metrics equivalence — Task 5. Cancellation at unit boundary per `orchestrator_state_machine.md` — Task 3 Step 4. §3.9.1 `baseline`/`replay`/`memory` and NFR-S1 sandboxing — explicitly **not covered**, logged above.

**Placeholder scan.** No TBDs; every code step carries literal code. Task 1 Step 4 is deliberately a no-op verification rather than an edit — `verify.py`'s signature already accepts the parameters, and the plan says so instead of inventing a change. Task 3 Step 6 forward-declares two stubs that Task 4 replaces; this is stated inline rather than left implicit.

**Type consistency.** `RunSpec`'s eleven fields are used identically in Tasks 1, 2, 3 and in `backend/runs.py`. `verify_unit(..., *, spec)` and `repair_unit(..., spec=...)` are keyword-only at both definition and call sites. `UnitResult`'s positional order in the test fakes matches the dataclass at `orchestrator.py:37-46`. `Orchestrator(spec=..., trace_path=..., state_path=..., on_event=..., cancel_requested=...)` is keyword-constructed everywhere. `_stream_event` and `_render_migrate_summary` are referenced in Task 3 and defined in Task 4 under exactly those names. `trace.jsonl` is used consistently after Task 3 Step 3 — including in Task 5's test and in `backend/runs.py`.

**Verified risk.** `grep -rn "Orchestrator(" --include=*.py .` returns exactly three real construction sites, all updated in Task 1: `backend/runs.py:221`, `backend/runs.py:301`, `weaver/agent/orchestrator.py:235`. The two hits in `tests/test_memory_writeback.py:92,128` construct a local `_FakeOrchestrator` and are unaffected. Re-run after Task 1 Step 7 to confirm nothing new landed.
