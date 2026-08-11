# Backend B6–B9 and SRS §3.9.1 CLI Conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining backend steps (B6 depth, B7 resume, B8 static serving, B9 conformance validation) and the four SRS §3.9.1 CLI gaps (`report <run_id>`, `baseline`, `replay`, `memory`), so "validated against the SRS" becomes a demonstrable statement rather than a claim.

**Architecture:** Three defects found during planning block everything downstream and are fixed first (Tasks 1–2): the CLI and the backend disagree on where run directories live, and the backend accepts four determinism parameters it silently discards. The CLI commands come next (Tasks 3–6) because B9's conformance table asserts CLI/API parity — it cannot pass until the CLI surface exists. Backend depth (Tasks 7–8), static serving (Task 9), and the conformance suite (Task 10) follow.

**Tech Stack:** Python 3.11+, `argparse` (existing `weaver/cli.py` subparser pattern), `rich` (terminal rendering), FastAPI + Starlette `TestClient`, `pytest`. No new dependencies. No frontend build toolchain — Task 9 is a single hand-written HTML file by deliberate choice (see its Design note).

---

## Defects found during planning

These were not in the status analysis. Each is a real conformance violation, and two of them silently corrupt the reproducibility record the whole DC-5 argument rests on.

| # | Defect | Evidence | Severity | Fixed in |
|---|---|---|---|---|
| 1 | **`RUNS_ROOT` divergence.** `weaver/agent/orchestrator.py:36` defines `RUNS_ROOT = Path("runs")` (correct per FR-8.1). `backend/runs.py:31` independently defines `RUNS_ROOT = Path("generated/runs")`. The two surfaces write run directories to different trees. | Both files, direct read | **High** — FR-8.1 names `runs/<run_id>/trace.jsonl` literally; the backend violates it, and `weaver report <run_id>` (Task 3) would silently fail to find backend runs | Task 1 |
| 2 | **Backend discards four determinism parameters.** `RunManager._run_worker` (`backend/runs.py:222-225`) builds `RunSpec.default().replace(cobol_source=…, input_data=…)` only. `seed`, `model_name`, `max_repair_attempts`, `replay`, and `copybook_dir` are accepted by `CreateRunRequest`, echoed into `params.json` and the `POST /runs` response — and never reach the orchestrator. `_resume_worker` (`:304-307`) has the identical defect. | `backend/runs.py`, `backend/models.py` | **High** — this is exactly the accepted-but-inert defect class CLAUDE.md rule 13 and `tests/test_param_plumbing.py` exist to prevent. `params.json` currently records a reproducibility claim that is false: a run recorded with `replay: true` did live inference. Violates NFR-D1 and DC-5. | Task 2 |
| 3 | **`resume_run` is unreachable over HTTP.** `RunManager.resume_run` and `_scan_for_interrupted_runs` are implemented (`backend/runs.py:274-297`), but no endpoint calls `resume_run`. B7's acceptance ("kill mid-run, restart, resume") cannot be performed through the API. | `backend/app.py` — 7 routes, none for resume | **Medium** — B7 is **[SHOULD]**; the code exists but the step is not completable as written | Task 8 |

**Rule 13 consequence.** Task 2 is not optional cleanup. Until it lands, every claim of the form "the API and the CLI produce the same run" is unproven for any parameter other than the two that happen to be threaded.

---

## Global Constraints

From CLAUDE.md and the two governing SRS documents. Every task's requirements implicitly include this section.

- **The comparison contract is absolute (FR-10, DC-4).** Byte-for-byte, line-ending normalisation only. No tolerance, threshold, heuristic, or model may participate in an equivalence determination. Nothing in this plan touches the comparison path; `weaver baseline` (Task 6) *measures* using the existing verifier, it never decides.
- **Classification is deterministic (FR-13, DC-4).** No model in the classification path. Rule order: PADDING, SIGN, SCALE, TRUNCATION, CONTROL_FLOW, UNKNOWN.
- **Exact decimal arithmetic (DC-3).** `decimal.Decimal`. Never binary float in harness code.
- **The backend contains no domain logic (BACKEND_PLAN §1.2).** It starts runs, tracks lifecycle, forwards events. Any number the API returns must be independently obtainable from the CLI, or the backend is doing something it should not.
- **Import direction (NFR-M1, §3.3).** `backend/` imports `weaver/`. `weaver/` must **never** import `backend/` or FastAPI/Starlette. Guarded by `tests/test_backend_import_direction.py` — do not break it. Shared constants move *into* `weaver/`.
- **Offline and credential-free (DC-1, NFR-8, NFR-10, §3.9.2).** The only network call is to the loopback inference endpoint, validated as loopback at startup; a non-loopback host aborts the run. **No static asset may reference an external host** (Task 9).
- **NFR-S3.** Trace events cross a network boundary. Do not log the full input set or raw prompts into events.
- **Layouts are data (NFR-14).** No hardcoded offsets outside `weaver/layout.py`.
- **Scope stays disclosed (FR-20, DC-6, CLAUDE.md rule 12).** No README, `--help` text, or docstring may claim behaviour that has not passed its own acceptance test. When a conformance row cannot be executed in this environment, it is reported as **skipped with a reason** — never quietly passed.
- **Spec defaults are exact.** `--max-repairs 3`, `--model qwen2.5-coder:7b`, `--seed 42`, copied verbatim from §3.9.1. Already in `weaver/agent/runspec.py`; do not redefine them elsewhere.
- **Load-bearing numbers:** 201 records, 132 divergences, golden checksum `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`. If one changes, something broke — stop and investigate before proceeding.
- **Tests must not require Ollama or GnuCOBOL to pass.** The suite currently has one Ollama-dependent failure and one `cobc`-dependent skip. Do not add a third environment dependency: monkeypatch `embed`, `InferenceClient.generate`, and `verify_unit` in tests.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `weaver/agent/runspec.py` | Single definition of run parameters | **Modify** — add `from_dict`, `model_digest` field |
| `weaver/agent/orchestrator.py` | `RUNS_ROOT` canonical definition | Unchanged (already correct) |
| `weaver/agent/memory.py` | `FailureMemory` store | **Modify** — add `merge_from` |
| `weaver/agent/baseline.py` | **New** — FR-8.3 single-shot translation, no verification/repair | **Create** |
| `weaver/cli.py` | CLI surface | **Modify** — `report` id resolution, `memory`, `replay`, `baseline` subcommands |
| `backend/runs.py` | Run lifecycle, param threading, resume | **Modify** — Tasks 1, 2, 8 |
| `backend/app.py` | Routes, static mounting | **Modify** — Tasks 8, 9 |
| `backend/static/index.html` | **New** — self-contained trace viewer | **Create** |
| `tests/test_cli_conformance.py` | **New** — §3.9.1 surface tests | **Create** |
| `tests/test_baseline.py` | **New** — FR-8.3 / AC-7 | **Create** |
| `tests/test_backend_service.py` | Backend transport tests | **Modify** — Tasks 1, 2, 7, 8, 9 |
| `tests/test_conformance.py` | **New** — BACKEND_PLAN Part VII §7.1 as executable rows | **Create** |

---

# Part A — Shared foundation (blocks everything)

## Task 1: Unify `RUNS_ROOT` on FR-8.1's `runs/`

**Files:**
- Modify: `backend/runs.py:31`
- Test: `tests/test_backend_service.py`

**Interfaces:**
- Consumes: `weaver.agent.orchestrator.RUNS_ROOT` (already `Path("runs")`)
- Produces: `backend.runs.RUNS_ROOT` is now the *same object* as the orchestrator's. Tasks 3, 5, 8 rely on one tree.

**Design note.** Do not "fix" this by changing the orchestrator to `generated/runs`. FR-8.1 states the path literally: `runs/<run_id>/trace.jsonl`. The orchestrator is correct; the backend is not. Import rather than redefine, so a future edit cannot re-diverge.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_backend_service.py`:

```python
def test_backend_and_cli_agree_on_runs_root():
    """FR-8.1 names runs/<run_id>/trace.jsonl literally. Two independent
    definitions of the run root means `weaver report <run_id>` cannot find
    a backend-created run, and DC-5 parity is unprovable."""
    import backend.runs as runs_module
    from weaver.agent.orchestrator import RUNS_ROOT as AGENT_RUNS_ROOT

    assert runs_module.RUNS_ROOT == AGENT_RUNS_ROOT
    assert AGENT_RUNS_ROOT == Path("runs")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_backend_service.py::test_backend_and_cli_agree_on_runs_root -v`
Expected: FAIL — `WindowsPath('generated/runs') != WindowsPath('runs')`

- [ ] **Step 3: Import instead of redefining**

In `backend/runs.py`, change the import block and delete the local constant:

```python
from weaver.agent.orchestrator import RUNS_ROOT, Orchestrator, UnitResult
```

Delete this line entirely (currently line 31):

```python
RUNS_ROOT = Path("generated/runs")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_backend_service.py -v`
Expected: PASS. The autouse `_patch_orchestrator` fixture already monkeypatches `runs_module.RUNS_ROOT` to `tmp_path / "runs"`, so no existing test writes to the real tree.

- [ ] **Step 5: Commit**

```bash
git add backend/runs.py tests/test_backend_service.py
git commit -m "fix: unify RUNS_ROOT on FR-8.1's runs/ across CLI and backend"
```

---

## Task 2: Thread every `CreateRunRequest` parameter into the `RunSpec`

**Files:**
- Modify: `weaver/agent/runspec.py` (add `model_digest`, `from_dict`)
- Modify: `backend/runs.py` (`_run_worker`, `_resume_worker`, add `_spec_for`)
- Test: `tests/test_param_plumbing.py`

**Interfaces:**
- Consumes: `CreateRunRequest` (`backend/models.py`), `RunSpec` (`weaver/agent/runspec.py`)
- Produces:
  - `RunSpec.from_dict(data: dict) -> RunSpec` — inverse of `to_dict`, coercing `str` back to `Path`. Task 5 (`weaver replay`) depends on this.
  - `RunSpec.model_digest: str = ""` — new field, §4.2 requires it in the reproducibility record.
  - `RunManager._spec_for(req: CreateRunRequest) -> RunSpec` — the single translation point. Task 8's resume worker calls it.

**Design note.** `CreateRunRequest.max_repair_attempts` defaults to `2`; `RunSpec.max_repairs` defaults to `3` per §3.9.1. These are different names for the same parameter with different defaults — a second way for the two surfaces to disagree. Align the API model's default to the spec's `3` as part of this task.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_param_plumbing.py`:

```python
def test_runspec_from_dict_round_trips_to_dict():
    """weaver replay <run_id> (Task 5) rebuilds a spec from params.json.
    A lossy round trip means a replayed run is not the recorded run."""
    from weaver.agent.runspec import RunSpec

    original = RunSpec.default().replace(
        cobol_source=Path("fixtures/cobol/interest.cob"),
        copybook_dir=Path("fixtures/cobol/copybooks"),
        max_repairs=7, model="test-model:1b", seed=99, replay=True,
        model_digest="sha256:abc123",
    )
    assert RunSpec.from_dict(original.to_dict()) == original


def test_backend_threads_every_determinism_parameter_into_the_spec():
    """NFR-D1/DC-5: params.json echoes seed, model, max_repair_attempts and
    replay. If they do not reach the orchestrator, the reproducibility
    record asserts something untrue -- a run stamped replay=true that
    actually performed live inference."""
    from backend.models import CreateRunRequest
    from backend.runs import RunManager

    req = CreateRunRequest(
        cobol_source="fixtures/cobol/interest.cob",
        copybook_dir="fixtures/cobol/copybooks",
        data_file="fixtures/data/accounts.dat",
        seed=1234, model_name="test-model:1b", model_digest="sha256:deadbeef",
        max_repair_attempts=7, replay=True,
    )
    spec = RunManager._spec_for(req)

    assert spec.cobol_source == Path("fixtures/cobol/interest.cob")
    assert spec.copybook_dir == Path("fixtures/cobol/copybooks")
    assert spec.input_data == Path("fixtures/data/accounts.dat")
    assert spec.seed == 1234
    assert spec.model == "test-model:1b"
    assert spec.model_digest == "sha256:deadbeef"
    assert spec.max_repairs == 7
    assert spec.replay is True


def test_create_run_request_max_repairs_default_matches_srs():
    """SRS 3.9.1 states --max-repairs 3. The API model must not introduce a
    second, quieter default."""
    from backend.models import CreateRunRequest
    from weaver.agent.runspec import DEFAULT_MAX_REPAIRS

    req = CreateRunRequest(cobol_source="a.cob", data_file="b.dat")
    assert req.max_repair_attempts == DEFAULT_MAX_REPAIRS == 3
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_param_plumbing.py -v -k "from_dict or determinism or max_repairs_default"`
Expected: 3 FAIL — `AttributeError: type object 'RunSpec' has no attribute 'from_dict'`, `AttributeError: 'RunManager' has no attribute '_spec_for'`, and `assert 2 == 3`.

- [ ] **Step 3: Add `model_digest` and `from_dict` to `RunSpec`**

In `weaver/agent/runspec.py`, add the field to the dataclass (after `seed`, before `replay`):

```python
    model_digest: str = ""
```

Add the classmethod after `default`:

```python
    @classmethod
    def from_dict(cls, data: dict) -> RunSpec:
        """Inverse of to_dict: rebuild a spec from a run directory's
        params.json. Path-typed fields are stored as strings, so they are
        coerced back here -- `weaver replay` (SRS 3.9.1) reconstructs a
        recorded run through this method, and a lossy round trip would mean
        the replayed run is not the run that was recorded (NFR-D1)."""
        path_fields = {
            f.name for f in dataclasses.fields(cls)
            if f.type in ("Path", "Path | None")
        }
        kwargs: dict[str, object] = {}
        for f in dataclasses.fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.name in path_fields and value is not None:
                value = Path(value)
            kwargs[f.name] = value
        return cls(**kwargs)
```

- [ ] **Step 4: Align the API model default and add the translation point**

In `backend/models.py`, change `CreateRunRequest`:

```python
from weaver.agent.runspec import DEFAULT_MAX_REPAIRS, DEFAULT_MODEL, DEFAULT_SEED


class CreateRunRequest(BaseModel):
    cobol_source: str
    copybook_dir: str | None = None
    data_file: str
    candidate_path: str | None = None
    synthesis_mode: bool = True
    seed: int = DEFAULT_SEED
    model_name: str = DEFAULT_MODEL
    model_digest: str = ""
    max_repair_attempts: int = DEFAULT_MAX_REPAIRS
    replay: bool = False
```

In `backend/runs.py`, add the static method to `RunManager` (place it directly above `_run_worker`):

```python
    @staticmethod
    def _spec_for(req: CreateRunRequest) -> RunSpec:
        """The single point where an API request becomes a RunSpec.

        Every determinism-affecting field in the request must land here.
        A field that is echoed into params.json but never reaches the
        orchestrator makes the reproducibility record false (NFR-D1,
        CLAUDE.md rule 13) -- tests/test_param_plumbing.py guards this.
        """
        spec = RunSpec.default().replace(
            cobol_source=Path(req.cobol_source),
            input_data=Path(req.data_file),
            max_repairs=req.max_repair_attempts,
            model=req.model_name,
            model_digest=req.model_digest,
            seed=req.seed,
            replay=req.replay,
        )
        if req.copybook_dir is not None:
            spec = spec.replace(copybook_dir=Path(req.copybook_dir))
        return spec
```

- [ ] **Step 5: Use it in both workers**

In `backend/runs.py`, replace the spec construction in `_run_worker` (currently lines 222–225):

```python
                spec = self._spec_for(record.request)
```

And the identical block in `_resume_worker` (currently lines 304–307):

```python
                spec = self._spec_for(record.request)
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: the three new tests PASS. `test_create_run_echoes_all_determinism_parameters` must still pass — it asserts the echo, which is unchanged.

- [ ] **Step 7: Commit**

```bash
git add weaver/agent/runspec.py backend/models.py backend/runs.py tests/test_param_plumbing.py
git commit -m "fix: thread every run parameter from the API into the RunSpec (NFR-D1)"
```

---

# Part B — SRS §3.9.1 CLI conformance

## Task 3: `weaver report <run_id>` accepts a run id as well as a path

**Files:**
- Modify: `weaver/cli.py` (`build_parser`, `run_report`, add `resolve_run_dir`)
- Test: `tests/test_cli_conformance.py` (new)

**Interfaces:**
- Consumes: `RUNS_ROOT` from `weaver.agent.orchestrator` (already imported in `cli.py:26`)
- Produces: `weaver.cli.resolve_run_dir(target: Path) -> Path` — Task 5 (`replay`) reuses it verbatim.

**Design note.** §3.9.1 says `weaver report <run_id>`. The existing implementation takes a path, and `tests/test_backend_service.py::test_cli_report_and_api_metrics_are_byte_identical` plus `_render_migrate_summary` both pass paths. Accept both: resolve a path if one exists, otherwise treat the argument as an id under `RUNS_ROOT`. Do not break the path form — it is the DC-5 parity test's entry point.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_conformance.py`:

```python
"""SRS 3.9.1 command-surface conformance.

These exercise the CLI surface only -- no GnuCOBOL, no Ollama. Anything
needing a real toolchain belongs in tests/test_conformance.py, where it is
skipped with a stated reason rather than quietly passed (CLAUDE.md rule 12).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import weaver.cli as cli


def _write_run_dir(root: Path, run_id: str) -> Path:
    """A minimal run directory: the three files compute_metrics reads."""
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"timestamp": 0.0, "unit": "UNIT-A", "node": "commit",
                    "action": "accept", "duration_seconds": 1.5,
                    "model_calls": 2, "outcome": "verified clean"}) + "\n"
    )
    (run_dir / "orchestrator_state.json").write_text(
        json.dumps({"UNIT-A": {"unit_id": "UNIT-A", "status": "committed",
                               "final_body": "x", "model_calls": 2,
                               "memory_hit": False, "duration_seconds": 1.5}})
    )
    (run_dir / "params.json").write_text(json.dumps(cli.RunSpec.default().to_dict(), indent=2))
    return run_dir


def test_report_resolves_a_bare_run_id_under_runs_root(tmp_path, monkeypatch, capsys):
    """SRS 3.9.1 specifies `weaver report <run_id>`, not a filesystem path."""
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    _write_run_dir(tmp_path / "runs", "abc123")

    exit_code = cli.main(["report", "abc123"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["equivalence_rate_post_repair"] == 100.0
    assert payload["model_calls_total"] == 2


def test_report_still_accepts_an_explicit_path(tmp_path, monkeypatch, capsys):
    """The path form predates 3.9.1 and is what the DC-5 parity test and
    _render_migrate_summary emit. Accepting an id must not break it."""
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    run_dir = _write_run_dir(tmp_path / "runs", "def456")

    exit_code = cli.main(["report", str(run_dir)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["model_calls_total"] == 2


def test_report_on_an_unknown_run_id_fails_with_a_named_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    (tmp_path / "runs").mkdir()

    exit_code = cli.main(["report", "nonexistent"])

    assert exit_code == 2
    assert "nonexistent" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_cli_conformance.py -v`
Expected: FAIL — `AttributeError: module 'weaver.cli' has no attribute 'RunSpec'` and the id form raising `FileNotFoundError`.

- [ ] **Step 3: Implement resolution**

In `weaver/cli.py`, add `RunSpec` to the existing runspec import so tests and `replay` can reach it:

```python
from weaver.agent.runspec import DEFAULT_MAX_REPAIRS, DEFAULT_MODEL, DEFAULT_SEED, RunSpec
```

Add the resolver above `run_report`:

```python
def resolve_run_dir(target: Path) -> Path:
    """SRS 3.9.1 spells the argument `<run_id>`; the pre-3.9.1 form is a
    path, and README/_render_migrate_summary/the DC-5 parity test all emit
    paths. Accept both: an existing directory is used as-is, anything else
    is treated as an id under RUNS_ROOT.
    """
    target = Path(target)
    if target.is_dir():
        return target
    candidate = RUNS_ROOT / target.name
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        f"no run directory for {str(target)!r} "
        f"(looked for a directory at that path, and for {candidate})"
    )
```

Rewrite `run_report` to use it:

```python
def run_report(args: argparse.Namespace) -> int:
    """`weaver report <run_id>` (SRS 3.9.1, BACKEND_PLAN.md 4.4 DC-5 target).

    Reads the same trace.jsonl / orchestrator_state.json a run directory
    holds and prints the identical Metrics object the backend's
    GET /runs/{id} serves -- both call weaver.agent.metrics.compute_metrics.
    """
    try:
        run_dir = resolve_run_dir(args.run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    metrics = compute_metrics(
        run_dir / "trace.jsonl",
        run_dir / "orchestrator_state.json",
        run_dir / "m4_baseline.json",
    )
    print(json.dumps(dataclasses.asdict(metrics), indent=2))
    return 0
```

Rename the parser argument (currently `run_dir`) so it reads as §3.9.1 spells it:

```python
    report_cmd = sub.add_parser("report", help="Print metrics for a run (by run id or run directory)")
    report_cmd.add_argument("run", metavar="run_id", type=Path,
                            help="Run id under runs/, or an explicit run directory path")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_cli_conformance.py tests/test_backend_service.py -v`
Expected: PASS, including the pre-existing `test_cli_report_and_api_metrics_are_byte_identical`. If that one fails, it is calling `args.run_dir` — update its invocation to the `run` argument name.

- [ ] **Step 5: Commit**

```bash
git add weaver/cli.py tests/test_cli_conformance.py
git commit -m "feat: resolve 'weaver report' by run id per SRS 3.9.1, keeping the path form"
```

---

## Task 4: `weaver memory list | export | import <file>`

**Files:**
- Modify: `weaver/agent/memory.py` (add `merge_from`)
- Modify: `weaver/cli.py` (parser, `run_memory`)
- Test: `tests/test_cli_conformance.py`

**Interfaces:**
- Consumes: `FailureMemory`, `MemoryCase`, `SymptomSignature` from `weaver.agent.memory`
- Produces:
  - `FailureMemory.merge_from(other_path: Path) -> tuple[int, int]` — returns `(imported, skipped)`. Skips any case whose `case_id` already exists.
  - `weaver.cli.run_memory(args) -> int`

**Design note — no embeddings.** `FailureMemory.__post_init__` reads cases straight from JSON, and `MemoryCase.embedding` is stored in the file. `list`, `export`, and `import` therefore need **no** inference call. Do not call `embed()` anywhere in this task — it would add a third Ollama dependency to the suite and break `weaver memory list` on a machine with no model server, for no benefit.

**Design note — import is additive, never destructive.** An imported case with a colliding `case_id` is skipped and counted, not overwritten. Overwriting could silently replace a locally-verified case with an unverified one from an untrusted export.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli_conformance.py`:

```python
def _memory_case_dict(case_id: str, defect_class: str = "SIGN", status: str = "verified") -> dict:
    """A MemoryCase in its on-disk shape. Embedding is stored, so nothing
    in the memory CLI needs an inference call."""
    return {
        "case_id": case_id,
        "signature": {
            "defect_class": defect_class, "field_scale": 2,
            "normalized_operation": "MOVE WS-INTEREST TO RL-INTEREST",
            "magnitude_band": "unit",
        },
        "embedding": [0.1, 0.2, 0.3],
        "defect_class": defect_class,
        "normalized_construct": "MOVE WS-INTEREST TO RL-INTEREST",
        "root_cause": "sign dropped",
        "patch_description": "negate",
        "patch_body_template": "ws.interest = ws.interest.negate();",
        "verification_status": status,
        "hit_count": 3,
        "confidence": 1.0,
        "provenance": "test fixture",
    }


@pytest.fixture
def memory_store(tmp_path):
    store = tmp_path / "failure_memory.json"
    store.write_text(json.dumps([_memory_case_dict("case-one"), _memory_case_dict("case-two")]))
    return store


def test_memory_list_prints_each_case(memory_store, capsys):
    exit_code = cli.main(["memory", "list", "--store", str(memory_store)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "case-one" in out and "case-two" in out
    assert "SIGN" in out


def test_memory_list_on_an_empty_store_says_so(tmp_path, capsys):
    exit_code = cli.main(["memory", "list", "--store", str(tmp_path / "absent.json")])

    assert exit_code == 0
    assert "no cases" in capsys.readouterr().out.lower()


def test_memory_export_writes_valid_json_to_a_file(memory_store, tmp_path, capsys):
    out_path = tmp_path / "exported.json"

    exit_code = cli.main(["memory", "export", "--store", str(memory_store), "--out", str(out_path)])

    assert exit_code == 0
    exported = json.loads(out_path.read_text())
    assert [c["case_id"] for c in exported] == ["case-one", "case-two"]


def test_memory_export_without_out_writes_to_stdout(memory_store, capsys):
    exit_code = cli.main(["memory", "export", "--store", str(memory_store)])

    assert exit_code == 0
    assert [c["case_id"] for c in json.loads(capsys.readouterr().out)] == ["case-one", "case-two"]


def test_memory_import_merges_new_cases_and_skips_collisions(memory_store, tmp_path, capsys):
    incoming = tmp_path / "incoming.json"
    incoming.write_text(json.dumps([
        _memory_case_dict("case-two"),        # collides -- must be skipped
        _memory_case_dict("case-three", defect_class="SCALE"),
    ]))

    exit_code = cli.main(["memory", "import", str(incoming), "--store", str(memory_store)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "imported 1" in out.lower()
    assert "skipped 1" in out.lower()

    stored = json.loads(memory_store.read_text())
    assert [c["case_id"] for c in stored] == ["case-one", "case-two", "case-three"]


def test_memory_import_never_overwrites_an_existing_case(memory_store, tmp_path):
    """A colliding id from an untrusted export must not replace a locally
    verified case."""
    incoming = tmp_path / "incoming.json"
    hostile = _memory_case_dict("case-one", status="unverified")
    hostile["patch_body_template"] = "// replaced"
    incoming.write_text(json.dumps([hostile]))

    cli.main(["memory", "import", str(incoming), "--store", str(memory_store)])

    stored = {c["case_id"]: c for c in json.loads(memory_store.read_text())}
    assert stored["case-one"]["verification_status"] == "verified"
    assert stored["case-one"]["patch_body_template"] != "// replaced"


def test_memory_import_of_a_missing_file_fails_cleanly(memory_store, tmp_path, capsys):
    exit_code = cli.main(["memory", "import", str(tmp_path / "nope.json"), "--store", str(memory_store)])

    assert exit_code == 2
    assert "nope.json" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_cli_conformance.py -v -k memory`
Expected: 7 FAIL — `argparse` exits with "invalid choice: 'memory'".

- [ ] **Step 3: Add `merge_from` to `FailureMemory`**

In `weaver/agent/memory.py`, add to the `FailureMemory` dataclass after `write_back`:

```python
    def merge_from(self, other_path: Path) -> tuple[int, int]:
        """Merge an exported store into this one. Returns (imported, skipped).

        A case whose case_id already exists is skipped, never overwritten:
        an import is additive. Overwriting would let an untrusted export
        silently replace a locally verified case with an unverified one
        (FR-6.4 -- memory holds verified repairs).
        """
        other_path = Path(other_path)
        raw = json.loads(other_path.read_text())
        existing = {c.case_id for c in self.cases}
        imported = 0
        skipped = 0
        for entry in raw:
            if entry["case_id"] in existing:
                skipped += 1
                continue
            self.cases.append(
                MemoryCase(**{**entry, "signature": SymptomSignature(**entry["signature"])})
            )
            existing.add(entry["case_id"])
            imported += 1
        if imported:
            self.save()
        return imported, skipped
```

- [ ] **Step 4: Add the parser and handler**

In `weaver/cli.py`, add these imports at the top:

```python
from weaver.agent.memory import FailureMemory
from weaver.agent.runspec import DEFAULT_MEMORY_STORE
```

Add the subparser in `build_parser`, after the `migrate` block:

```python
    # SRS 3.9.1: weaver memory list | export | import <file>
    memory_cmd = sub.add_parser("memory", help="Inspect, export, or import the failure-memory store")
    memory_sub = memory_cmd.add_subparsers(dest="memory_action", required=True)

    mem_list = memory_sub.add_parser("list", help="List stored cases")
    mem_list.add_argument("--store", type=Path, default=DEFAULT_MEMORY_STORE)

    mem_export = memory_sub.add_parser("export", help="Write the store as JSON (stdout by default)")
    mem_export.add_argument("--store", type=Path, default=DEFAULT_MEMORY_STORE)
    mem_export.add_argument("--out", type=Path, default=None)

    mem_import = memory_sub.add_parser("import", help="Merge an exported store into this one")
    mem_import.add_argument("file", type=Path)
    mem_import.add_argument("--store", type=Path, default=DEFAULT_MEMORY_STORE)
```

Add the handler above `main`:

```python
def run_memory(args: argparse.Namespace) -> int:
    """`weaver memory list | export | import <file>` (SRS 3.9.1).

    Reads and writes the store on disk only. Embeddings are persisted with
    each case, so none of these actions needs an inference call -- memory
    stays inspectable on a machine with no model server running.
    """
    memory = FailureMemory(args.store)

    if args.memory_action == "list":
        if not memory.cases:
            console.print(f"[yellow]No cases in {args.store}.[/yellow]")
            return 0
        table = Table(title=f"Failure memory ({len(memory.cases)} cases) - {args.store}")
        table.add_column("Case id")
        table.add_column("Defect class")
        table.add_column("Status")
        table.add_column("Hits", justify="right")
        table.add_column("Construct")
        for case in memory.cases:
            table.add_row(
                case.case_id, case.defect_class, case.verification_status,
                str(case.hit_count), case.normalized_construct,
            )
        console.print(table)
        return 0

    if args.memory_action == "export":
        payload = json.dumps(
            [{**dataclasses.asdict(c), "signature": dataclasses.asdict(c.signature)}
             for c in memory.cases],
            indent=2,
        )
        if args.out is None:
            print(payload)
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(payload)
            console.print(f"[green]Exported {len(memory.cases)} cases to {args.out}[/green]")
        return 0

    if args.memory_action == "import":
        if not args.file.exists():
            print(f"no such file: {args.file}", file=sys.stderr)
            return 2
        imported, skipped = memory.merge_from(args.file)
        console.print(f"[green]imported {imported}[/green], [yellow]skipped {skipped}[/yellow] "
                      f"(existing case ids are never overwritten)")
        return 0

    return 2
```

Wire it in `main`, before the final `parser.print_help()`:

```python
    if args.command == "memory":
        return run_memory(args)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_cli_conformance.py -v -k memory`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add weaver/agent/memory.py weaver/cli.py tests/test_cli_conformance.py
git commit -m "feat: add 'weaver memory list|export|import' per SRS 3.9.1"
```

---

## Task 5: `weaver replay <run_id>`

**Files:**
- Modify: `weaver/cli.py` (parser, `run_replay`)
- Test: `tests/test_cli_conformance.py`

**Interfaces:**
- Consumes: `resolve_run_dir` (Task 3), `RunSpec.from_dict` (Task 2), `Orchestrator`, `RUNS_ROOT`
- Produces: `weaver.cli.run_replay(args) -> int`

**Design note.** FR-8.4's acceptance is "start run with replay flag → **zero inference calls**." That guarantee is structural, not statistical: `InferenceClient(replay_only=True)` raises `ReplayMissError` on a cache miss rather than falling back to the network. `run_replay` therefore does not need to count calls — it needs to reconstruct the recorded spec faithfully and force `replay=True`. The test asserts zero HTTP by making any real call raise.

**Design note.** A replay writes to a **new** run directory. Overwriting the original would destroy the recording being replayed, and `params.json` would no longer describe the run that produced the trace.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli_conformance.py`:

```python
class _NoInferenceAllowed:
    """Any real inference during a replay is an FR-8.4 violation."""

    def __init__(self, *a, **kw):
        pass

    def generate(self, *a, **kw):
        raise AssertionError("replay performed a live inference call (FR-8.4)")


def test_replay_reconstructs_the_recorded_spec_and_forces_replay_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    run_dir = _write_run_dir(tmp_path / "runs", "recorded")
    recorded = cli.RunSpec.default().replace(
        cobol_source=Path("fixtures/cobol/interest.cob"),
        max_repairs=7, model="test-model:1b", seed=1234, replay=False,
    )
    (run_dir / "params.json").write_text(json.dumps(recorded.to_dict(), indent=2))

    seen = {}

    class _CapturingOrchestrator:
        def __init__(self, *, spec, trace_path, state_path, on_event=None, cancel_requested=None, **kw):
            seen["spec"] = spec
            seen["trace_path"] = trace_path
            self.results = {}

        def run(self):
            return self.results

    monkeypatch.setattr(cli, "Orchestrator", _CapturingOrchestrator)
    monkeypatch.setattr("weaver.agent.inference.InferenceClient", _NoInferenceAllowed)

    exit_code = cli.main(["replay", "recorded"])

    assert exit_code == 0
    assert seen["spec"].max_repairs == 7
    assert seen["spec"].model == "test-model:1b"
    assert seen["spec"].seed == 1234
    assert seen["spec"].replay is True, "FR-8.4: replay must be forced on regardless of what was recorded"


def test_replay_writes_to_a_new_run_directory_not_the_recorded_one(tmp_path, monkeypatch, capsys):
    """Replaying into the source directory would overwrite the trace being
    replayed and leave params.json describing a run it did not produce."""
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    run_dir = _write_run_dir(tmp_path / "runs", "recorded")
    original_trace = (run_dir / "trace.jsonl").read_text()

    seen = {}

    class _CapturingOrchestrator:
        def __init__(self, *, spec, trace_path, state_path, on_event=None, cancel_requested=None, **kw):
            seen["trace_path"] = trace_path
            self.results = {}

        def run(self):
            return self.results

    monkeypatch.setattr(cli, "Orchestrator", _CapturingOrchestrator)

    cli.main(["replay", "recorded"])

    assert seen["trace_path"].parent != run_dir
    assert (run_dir / "trace.jsonl").read_text() == original_trace


def test_replay_of_a_run_without_params_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    run_dir = tmp_path / "runs" / "bare"
    run_dir.mkdir(parents=True)

    exit_code = cli.main(["replay", "bare"])

    assert exit_code == 2
    assert "params.json" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_cli_conformance.py -v -k replay`
Expected: 3 FAIL — "invalid choice: 'replay'".

- [ ] **Step 3: Add the parser and handler**

In `weaver/cli.py`, add the subparser after the `memory` block:

```python
    # SRS 3.9.1: weaver replay <run_id>
    replay_cmd = sub.add_parser("replay", help="Re-execute a recorded run from cache only (FR-8.4)")
    replay_cmd.add_argument("run", metavar="run_id", type=Path,
                            help="Run id under runs/, or an explicit run directory path")
    replay_cmd.add_argument("--json", action="store_true",
                            help="Emit machine-readable JSON instead of streaming status")
```

Add the handler after `run_migrate`:

```python
def run_replay(args: argparse.Namespace) -> int:
    """`weaver replay <run_id>` (SRS 3.9.1, FR-8.4).

    Rebuilds the recorded run's RunSpec from its params.json and re-executes
    it with replay forced on. Zero inference is structural, not checked
    after the fact: InferenceClient(replay_only=True) raises ReplayMissError
    on a cache miss rather than falling back to the network.

    The replay writes into a new run directory. Reusing the recorded one
    would overwrite the trace being replayed.
    """
    try:
        source_dir = resolve_run_dir(args.run)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    params_path = source_dir / "params.json"
    if not params_path.exists():
        print(f"{source_dir} has no params.json; it is not a replayable run "
              f"(the reproducibility record required by NFR-D1 is missing)",
              file=sys.stderr)
        return 2

    spec = RunSpec.from_dict(json.loads(params_path.read_text())).replace(replay=True)

    replay_id = f"replay-{uuid.uuid4().hex[:12]}"
    run_dir = RUNS_ROOT / replay_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "params.json").write_text(json.dumps(spec.to_dict(), indent=2))
    (run_dir / "replay_of.json").write_text(json.dumps({"source_run_dir": str(source_dir)}, indent=2))

    orchestrator = Orchestrator(
        spec=spec,
        trace_path=run_dir / "trace.jsonl",
        state_path=run_dir / "orchestrator_state.json",
        on_event=None if args.json else _stream_event,
        cancel_requested=threading.Event(),
    )
    results = orchestrator.run()

    statuses = {r.status for r in results.values()}
    exit_code = 0 if statuses <= {"committed"} else 1

    if args.json:
        print(json.dumps({
            "run_dir": str(run_dir), "replay_of": str(source_dir),
            "units": {uid: dataclasses.asdict(r) for uid, r in results.items()},
            "exit_code": exit_code,
        }, indent=2, default=str))
    else:
        console.print(f"[cyan]Replayed[/cyan] {source_dir} [cyan]into[/cyan] {run_dir}")
        _render_migrate_summary(run_dir, results)

    return exit_code
```

Wire it in `main`:

```python
    if args.command == "replay":
        return run_replay(args)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_cli_conformance.py -v -k replay`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add weaver/cli.py tests/test_cli_conformance.py
git commit -m "feat: add 'weaver replay <run_id>' per SRS 3.9.1 / FR-8.4"
```

---

## Task 6: `weaver baseline <program.cbl>` (FR-8.3, AC-7)

**Files:**
- Create: `weaver/agent/baseline.py`
- Modify: `weaver/cli.py` (parser, `run_baseline`)
- Test: `tests/test_baseline.py` (new)

**Interfaces:**
- Consumes: `InferenceClient`, `InferenceRequest` (`weaver.agent.inference`), `RunSpec`, `verify_unit` is **not** used — baseline is whole-program, not per-unit
- Produces:
  - `weaver.agent.baseline.BaselineResult` — dataclass: `units_synthesized: int`, `units_compiling: int`, `compiled: bool`, `divergence_count: int | None`, `total_records: int | None`, `verified: bool`, `compile_error: str | None`, `equivalence_rate: float`
  - `weaver.agent.baseline.run_baseline_translation(spec: RunSpec, run_dir: Path, client=None) -> BaselineResult`

**Design note — what FR-8.3 actually asks for.** "Single-shot whole-program translation with **no verification or repair**, evaluated against the same vectors." Two things follow. First: exactly **one** model call, then stop — no repair loop, no memory lookup, no second attempt. Second: "no verification" means no verification *in the loop* — the result is still measured against the oracle afterwards, or AC-7 ("measurably worse equivalence than the full pipeline") would have nothing to compare. The measurement uses the same byte comparison as everything else; baseline never gets its own weaker standard (DC-4).

**Design note — a compile failure is a legitimate result.** `generated/m4_baseline.json` already records `units_compiling: 0` from a real unassisted attempt. Do not treat a non-compiling baseline as an error: record it and report an equivalence rate of `0.0`. That is the finding.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_baseline.py`:

```python
"""FR-8.3 baseline mode and AC-7.

Single-shot whole-program translation with no verification or repair in the
loop, measured afterwards against the same vectors with the same byte
comparison every other path uses (DC-4 -- baseline never gets a weaker
standard). No Ollama and no GnuCOBOL: inference and compilation are both
stubbed, because what these tests pin down is the *shape* of the baseline
path, not the model's output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weaver.agent.baseline import BaselineResult, run_baseline_translation
from weaver.agent.runspec import RunSpec


class _CountingClient:
    """Records how many times the model was asked for anything."""

    def __init__(self, response: str = "public class Baseline {}"):
        self.calls = 0
        self._response = response

    def generate(self, request):
        self.calls += 1

        class _Response:
            text = self._response
            duration_seconds = 0.5
            tokens_in = 100
            tokens_out = 200

        return _Response()


@pytest.fixture
def spec(tmp_path):
    source = tmp_path / "interest.cob"
    source.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. INTEREST.\n")
    data = tmp_path / "accounts.dat"
    data.write_text("ACCT00000000000200000131700+003502SNN  \n")
    golden = tmp_path / "golden.out"
    golden.write_text("line\n")
    return RunSpec.default().replace(cobol_source=source, input_data=data, golden_output=golden)


def test_baseline_makes_exactly_one_model_call(spec, tmp_path, monkeypatch):
    """FR-8.3: single-shot. A second call would make this a repair loop."""
    client = _CountingClient()
    monkeypatch.setattr("weaver.agent.baseline._compile_and_measure",
                        lambda *a, **kw: (False, "stub: not compiled", None, None))

    run_baseline_translation(spec, tmp_path / "run", client=client)

    assert client.calls == 1


def test_baseline_never_invokes_the_repair_loop(spec, tmp_path, monkeypatch):
    """FR-8.3 says 'no verification or repair'. The whole point of the
    measurement is that the harness contributed nothing."""
    import weaver.agent.repair_loop as repair_loop

    def _boom(*a, **kw):
        raise AssertionError("baseline invoked the repair loop (FR-8.3)")

    monkeypatch.setattr(repair_loop, "repair_unit", _boom, raising=False)
    monkeypatch.setattr("weaver.agent.baseline._compile_and_measure",
                        lambda *a, **kw: (False, "stub", None, None))

    run_baseline_translation(spec, tmp_path / "run", client=_CountingClient())


def test_baseline_records_a_compile_failure_as_a_result_not_an_error(spec, tmp_path, monkeypatch):
    """generated/m4_baseline.json already records units_compiling: 0 from a
    real attempt. A non-compiling baseline is the finding, not a crash."""
    monkeypatch.setattr("weaver.agent.baseline._compile_and_measure",
                        lambda *a, **kw: (False, "cannot find symbol: BigDecimal", None, None))

    result = run_baseline_translation(spec, tmp_path / "run", client=_CountingClient())

    assert isinstance(result, BaselineResult)
    assert result.compiled is False
    assert result.units_compiling == 0
    assert result.verified is False
    assert result.equivalence_rate == 0.0
    assert "BigDecimal" in result.compile_error


def test_baseline_measures_divergences_when_it_compiles(spec, tmp_path, monkeypatch):
    monkeypatch.setattr("weaver.agent.baseline._compile_and_measure",
                        lambda *a, **kw: (True, None, 132, 201))

    result = run_baseline_translation(spec, tmp_path / "run", client=_CountingClient())

    assert result.compiled is True
    assert result.units_compiling == 1
    assert result.divergence_count == 132
    assert result.total_records == 201
    assert result.verified is False


def test_baseline_writes_baseline_json_into_the_run_directory(spec, tmp_path, monkeypatch):
    """weaver report reads m4_baseline.json for equivalence_rate_unassisted;
    the baseline command is what produces that file honestly."""
    monkeypatch.setattr("weaver.agent.baseline._compile_and_measure",
                        lambda *a, **kw: (True, None, 132, 201))
    run_dir = tmp_path / "run"

    run_baseline_translation(spec, run_dir, client=_CountingClient())

    payload = json.loads((run_dir / "baseline.json").read_text())
    assert payload["units_synthesized"] == 1
    assert payload["units_compiling"] == 1
    assert payload["divergence_count"] == 132


def test_baseline_writes_the_generated_java_for_inspection(spec, tmp_path, monkeypatch):
    monkeypatch.setattr("weaver.agent.baseline._compile_and_measure",
                        lambda *a, **kw: (False, "stub", None, None))
    run_dir = tmp_path / "run"

    run_baseline_translation(spec, run_dir, client=_CountingClient("public class Baseline { }"))

    assert (run_dir / "Baseline.java").read_text() == "public class Baseline { }"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_baseline.py -v`
Expected: 6 FAIL — `ModuleNotFoundError: No module named 'weaver.agent.baseline'`.

- [ ] **Step 3: Create `weaver/agent/baseline.py`**

```python
"""FR-8.3 baseline mode — single-shot whole-program translation.

The control arm. One model call produces an entire Java program from the
COBOL source; there is no scaffold, no per-unit attribution, no memory
lookup, and no repair. What it produces is then measured against the same
vectors with the same byte comparison every other path uses -- baseline
never gets a weaker standard (DC-4).

The point is AC-7: quantifying what the harness contributes, by showing
what the model does without it.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from weaver.agent.inference import InferenceClient, InferenceRequest
from weaver.agent.runspec import RunSpec
from weaver.comparison import compare_lines, normalize_line_endings
from weaver.execution import run_candidate, run_oracle

MODEL_CACHE_DIR = Path("generated/model_cache")
OUTPUT_FILENAME = "interest.out"

PROMPT_TEMPLATE = """Translate this COBOL program to a single self-contained Java class named Baseline.

Requirements:
- Read the input file path from args[0] and write output to {output_filename} in the working directory.
- Reproduce the program's output format exactly, including all padding and sign conventions.
- Use fully-qualified names (java.math.BigDecimal, java.math.RoundingMode) -- no import statements.

COBOL source:
{source}
"""


@dataclass
class BaselineResult:
    units_synthesized: int
    units_compiling: int
    compiled: bool
    divergence_count: int | None
    total_records: int | None
    verified: bool
    compile_error: str | None
    equivalence_rate: float


def _compile_and_measure(java_path: Path, spec: RunSpec,
                          work_dir: Path) -> tuple[bool, str | None, int | None, int | None]:
    """Compile the generated program and compare it to the oracle.

    Returns (compiled, compile_error, divergence_count, total_records).
    Separated out so tests can stub the toolchain -- what the baseline tests
    pin down is the shape of this path, not GnuCOBOL's behaviour.
    """
    build_dir = work_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["javac", "-d", str(build_dir), str(java_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, proc.stderr.strip(), None, None

    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp) / "candidate"
        candidate_result = run_candidate(
            java_path.stem, build_dir, candidate_dir, spec.input_data, OUTPUT_FILENAME,
        )
        oracle_lines = normalize_line_endings(spec.golden_output.read_text()).splitlines()
        candidate_lines = normalize_line_endings(candidate_result.output_text).splitlines()

    divergences = compare_lines(oracle_lines, candidate_lines)
    return True, None, sum(1 for d in divergences if d is not None), len(oracle_lines)


def run_baseline_translation(spec: RunSpec, run_dir: Path,
                              client: InferenceClient | None = None) -> BaselineResult:
    """One model call, no repair, then measure. FR-8.3."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        client = InferenceClient(
            cache_dir=MODEL_CACHE_DIR, replay_only=spec.replay,
        )

    prompt = PROMPT_TEMPLATE.format(
        output_filename=OUTPUT_FILENAME,
        source=spec.cobol_source.read_text(),
    )
    response = client.generate(InferenceRequest(prompt=prompt, model=spec.model, seed=spec.seed))

    java_path = run_dir / "Baseline.java"
    java_path.write_text(response.text)

    compiled, compile_error, divergence_count, total_records = _compile_and_measure(
        java_path, spec, run_dir,
    )
    verified = compiled and divergence_count == 0

    result = BaselineResult(
        units_synthesized=1,
        units_compiling=1 if compiled else 0,
        compiled=compiled,
        divergence_count=divergence_count,
        total_records=total_records,
        verified=verified,
        compile_error=compile_error,
        equivalence_rate=100.0 if verified else 0.0,
    )
    (run_dir / "baseline.json").write_text(json.dumps(asdict(result), indent=2))
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_baseline.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Add the CLI surface**

In `weaver/cli.py`, add the import:

```python
from weaver.agent.baseline import run_baseline_translation
```

Add the subparser after the `replay` block:

```python
    # SRS 3.9.1: weaver baseline <program.cbl>  (FR-8.3, AC-7)
    baseline_cmd = sub.add_parser(
        "baseline", help="Single-shot whole-program translation, no verification or repair (FR-8.3)")
    baseline_cmd.add_argument("program", type=Path, help="COBOL program to translate")
    baseline_cmd.add_argument("--data", type=Path, default=None, help="Input data file for measurement")
    baseline_cmd.add_argument("--model", default=DEFAULT_MODEL, help="Local inference model tag")
    baseline_cmd.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Inference seed")
    baseline_cmd.add_argument("--replay", action="store_true", help="Serve the model response from cache")
    baseline_cmd.add_argument("--run-dir", type=Path, default=None, help="Run directory")
```

Add the handler after `run_replay`:

```python
def run_baseline(args: argparse.Namespace) -> int:
    """`weaver baseline <program.cbl>` (SRS 3.9.1, FR-8.3).

    The control arm for AC-7. Exits 0 whether or not the translation
    verifies: this is a measurement, not a gate. A baseline that fails to
    compile is the finding, not an error.
    """
    defaults = RunSpec.default()
    spec = defaults.replace(
        cobol_source=args.program,
        input_data=args.data or defaults.input_data,
        model=args.model,
        seed=args.seed,
        replay=args.replay,
    )
    run_dir = args.run_dir or (RUNS_ROOT / f"baseline-{uuid.uuid4().hex[:12]}")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "params.json").write_text(json.dumps(spec.to_dict(), indent=2))

    result = run_baseline_translation(spec, run_dir)

    table = Table(title="Baseline (single-shot, no repair) - FR-8.3")
    table.add_column("Measure")
    table.add_column("Value")
    table.add_row("Compiled", "[green]yes[/green]" if result.compiled else "[red]no[/red]")
    if result.compile_error:
        table.add_row("Compile error", result.compile_error.splitlines()[0])
    table.add_row("Divergences", "n/a" if result.divergence_count is None else str(result.divergence_count))
    table.add_row("Records compared", "n/a" if result.total_records is None else str(result.total_records))
    table.add_row("Verified", "[green]yes[/green]" if result.verified else "[red]no[/red]")
    table.add_row("Equivalence rate", f"{result.equivalence_rate:.1f}%")
    console.print(table)
    console.print(f"[cyan]Run directory:[/cyan] {run_dir}")
    console.print("[dim]AC-7: compare this against a full 'weaver migrate' run of the same program.[/dim]")
    return 0
```

Wire it in `main`:

```python
    if args.command == "baseline":
        return run_baseline(args)
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: no regressions. `weaver --help` now lists six commands matching §3.9.1.

- [ ] **Step 7: Commit**

```bash
git add weaver/agent/baseline.py weaver/cli.py tests/test_baseline.py
git commit -m "feat: add 'weaver baseline' single-shot translation per SRS 3.9.1 / FR-8.3"
```

---

# Part C — Backend B6 and B7

## Task 7: B6 — prove an accepted-but-wrong body is rejected

**Files:**
- Test: `tests/test_backend_service.py`
- Modify: `backend/runs.py` only if a test exposes a defect

**Interfaces:**
- Consumes: `RunManager.decide_escalation` (already implemented, `backend/runs.py:133-175`)
- Produces: no new interface — this task converts "implemented" into "verified"

**Design note.** B6's stated acceptance is exactly one sentence: *"an accepted body that fails verification is rejected and reported as such."* The code appears to do this, and the existing suite covers only the non-escalated-unit rejection path. This is the single place where a well-meaning API could quietly break DC-4, so it gets tested directly rather than assumed. Write the tests first; only touch `runs.py` if one fails.

- [ ] **Step 1: Write the tests**

Add to `tests/test_backend_service.py`:

```python
@dataclass
class _StubAttribution:
    compiled: bool
    report: object


@dataclass
class _StubReport:
    divergence_count: int

    def to_json(self):
        return json.dumps({"divergence_count": self.divergence_count})


def _escalated_run(client, monkeypatch, verify_result):
    """Create a run, force one unit into 'escalated', and stub verify_unit."""
    run_id = client.post("/runs", json=_create_payload()).json()["run_id"]
    _wait_terminal(client, run_id)
    record = app_module.run_manager.get_run(run_id)
    record.orchestrator.results["UNIT-A"] = UnitResult(
        "UNIT-A", "escalated", "int x = 1;", 3, False, 1.0,
    )
    monkeypatch.setattr(runs_module, "verify_unit", lambda *a, **kw: verify_result)
    return run_id


def test_b6_accepted_body_that_fails_verification_is_rejected(client, monkeypatch):
    """BACKEND_PLAN Step B6 acceptance, and the one place a well-meaning API
    could quietly break DC-4. A human accepting a body is not evidence it is
    correct -- the oracle is the only authority."""
    run_id = _escalated_run(client, monkeypatch,
                            _StubAttribution(compiled=True, report=_StubReport(divergence_count=17)))

    resp = client.post(f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is False
    assert body["committed"] is False
    assert body["divergence_count"] == 17

    record = app_module.run_manager.get_run(run_id)
    assert record.orchestrator.results["UNIT-A"].status == "escalated", \
        "a unit that failed verification must not be marked committed"


def test_b6_body_that_fails_to_compile_is_rejected(client, monkeypatch):
    run_id = _escalated_run(client, monkeypatch,
                            _StubAttribution(compiled=False, report=_StubReport(divergence_count=0)))

    body = client.post(f"/runs/{run_id}/escalations/UNIT-A/decision",
                        json={"decision": "body", "body": "not java"}).json()

    assert body["verified"] is False
    assert body["committed"] is False


def test_b6_rejected_body_is_never_written_to_failure_memory(client, monkeypatch):
    """FR-6.4: memory holds verified repairs. Writing an unverified one
    poisons every future retrieval."""
    run_id = _escalated_run(client, monkeypatch,
                            _StubAttribution(compiled=True, report=_StubReport(divergence_count=17)))
    written = []
    monkeypatch.setattr(runs_module.RunManager, "_write_back_escalation",
                        lambda self, *a, **kw: written.append(a))

    client.post(f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"})

    assert written == []


def test_b6_verified_body_is_committed_and_written_back(client, monkeypatch):
    run_id = _escalated_run(client, monkeypatch,
                            _StubAttribution(compiled=True, report=_StubReport(divergence_count=0)))
    written = []
    monkeypatch.setattr(runs_module.RunManager, "_write_back_escalation",
                        lambda self, *a, **kw: written.append(a))

    body = client.post(f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"}).json()

    assert body["verified"] is True
    assert body["committed"] is True
    assert len(written) == 1

    record = app_module.run_manager.get_run(run_id)
    assert record.orchestrator.results["UNIT-A"].status == "committed"


def test_b6_decision_outcome_is_persisted_to_the_run_directory(client, monkeypatch):
    run_id = _escalated_run(client, monkeypatch,
                            _StubAttribution(compiled=True, report=_StubReport(divergence_count=17)))

    client.post(f"/runs/{run_id}/escalations/UNIT-A/decision", json={"decision": "accept"})

    record = app_module.run_manager.get_run(run_id)
    persisted = json.loads((record.run_dir / "escalation_decisions.json").read_text())
    assert persisted["UNIT-A"]["verified"] is False
```

- [ ] **Step 2: Run them**

Run: `python -m pytest tests/test_backend_service.py -v -k b6`
Expected: 5 PASS if `decide_escalation` is correct as written. **If any fail, stop and fix `backend/runs.py` before continuing** — a failure here is a live DC-4 violation, not a test bug.

- [ ] **Step 3: Commit**

```bash
git add tests/test_backend_service.py
git commit -m "test: verify B6 rejects accepted-but-unverified bodies (FR-4.5, DC-4)"
```

---

## Task 8: B7 — expose resume over HTTP and prove kill/resume equivalence

**Files:**
- Modify: `backend/app.py` (add resume route)
- Modify: `backend/runs.py` (`resume_run` must reload records from disk)
- Test: `tests/test_backend_service.py`

**Interfaces:**
- Consumes: `RunManager.resume_run`, `RunManager._scan_for_interrupted_runs`, `RunManager._spec_for` (Task 2)
- Produces: `POST /runs/{run_id}/resume` → `{"run_id", "lifecycle", "resumed_from_units": [unit_id, ...]}`

**Design note.** `_scan_for_interrupted_runs` rewrites `lifecycle.json` on disk at startup, but `self._runs` is an in-memory dict populated only by `create_run`. After a real process restart the registry is empty, so `resume_run` raises `RunNotFoundError` for exactly the runs it exists to serve. Resume must rehydrate a `RunRecord` from the run directory.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_backend_service.py`:

```python
def test_b7_interrupted_run_is_resumable_after_a_registry_restart(client, monkeypatch, tmp_path):
    """NFR-R2. _scan_for_interrupted_runs marks lifecycle.json on disk, but
    a real restart leaves the in-memory registry empty -- resume must
    rehydrate from the run directory or it serves nobody."""
    run_id = client.post("/runs", json=_create_payload()).json()["run_id"]
    _wait_terminal(client, run_id)
    record = app_module.run_manager.get_run(run_id)
    run_dir = record.run_dir

    # Simulate an interruption, then a process restart.
    (run_dir / "lifecycle.json").write_text(json.dumps(
        {"run_id": run_id, "lifecycle": "RUNNING", "error": None}))
    fresh = RunManager()
    monkeypatch.setattr(app_module, "run_manager", fresh)

    assert json.loads((run_dir / "lifecycle.json").read_text())["lifecycle"] == "INTERRUPTED"

    resp = client.post(f"/runs/{run_id}/resume")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id


def test_b7_resume_does_not_re_verify_committed_units(client, monkeypatch):
    """4.5: checkpoint after commit, never before. A resumed run must keep
    committed units as-is; re-running them would waste inference and could
    flip a verified unit on a nondeterministic model."""
    run_id = client.post("/runs", json=_create_payload()).json()["run_id"]
    state = _wait_terminal(client, run_id)
    assert state["lifecycle"] == "COMPLETED"

    record = app_module.run_manager.get_run(run_id)
    record.lifecycle = "INTERRUPTED"

    resp = client.post(f"/runs/{run_id}/resume")

    assert resp.status_code == 200
    assert set(resp.json()["resumed_from_units"]) == {"UNIT-A", "UNIT-B"}


def test_b7_resume_on_a_run_that_is_not_interrupted_is_a_400(client):
    run_id = client.post("/runs", json=_create_payload()).json()["run_id"]
    _wait_terminal(client, run_id)

    resp = client.post(f"/runs/{run_id}/resume")

    assert resp.status_code == 400
    assert resp.json()["error_class"] == "INVALID_REQUEST"


def test_b7_resume_of_an_unknown_run_is_a_404(client):
    resp = client.post("/runs/does-not-exist/resume")

    assert resp.status_code == 404
    assert resp.json()["error_class"] == "RUN_NOT_FOUND"


def test_b7_resumed_run_final_state_matches_an_uninterrupted_run(client, monkeypatch):
    """Step B7's stated acceptance."""
    uninterrupted_id = client.post("/runs", json=_create_payload()).json()["run_id"]
    uninterrupted = _wait_terminal(client, uninterrupted_id)

    resumed_id = client.post("/runs", json=_create_payload()).json()["run_id"]
    _wait_terminal(client, resumed_id)
    app_module.run_manager.get_run(resumed_id).lifecycle = "INTERRUPTED"
    client.post(f"/runs/{resumed_id}/resume")
    resumed = _wait_terminal(client, resumed_id)

    assert resumed["lifecycle"] == uninterrupted["lifecycle"]
    assert (sorted((u["unit_id"], u["status"]) for u in resumed["units"])
            == sorted((u["unit_id"], u["status"]) for u in uninterrupted["units"]))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_backend_service.py -v -k b7`
Expected: FAIL — 404/405 on `POST /runs/{id}/resume` (no such route).

- [ ] **Step 3: Make `resume_run` rehydrate from disk**

In `backend/runs.py`, add this method to `RunManager` directly above `resume_run`:

```python
    def _rehydrate(self, run_id: str) -> RunRecord | None:
        """Rebuild a RunRecord from its run directory.

        _scan_for_interrupted_runs marks lifecycle.json on disk, but the
        in-memory registry is empty after a process restart -- which is
        precisely when resume is needed (NFR-R2). Without this, resume
        raises RunNotFoundError for every run it exists to serve.
        """
        run_dir = RUNS_ROOT / run_id
        params_path = run_dir / "params.json"
        lifecycle_path = run_dir / "lifecycle.json"
        if not params_path.exists() or not lifecycle_path.exists():
            return None
        request = CreateRunRequest(**json.loads(params_path.read_text()))
        record = RunRecord(run_id=run_id, request=request, run_dir=run_dir)
        record.lifecycle = json.loads(lifecycle_path.read_text()).get("lifecycle", "INTERRUPTED")
        with self._registry_lock:
            self._runs[run_id] = record
        return record
```

Change `get_run` to consult the disk before giving up:

```python
    def get_run(self, run_id: str) -> RunRecord:
        with self._registry_lock:
            record = self._runs.get(run_id)
        if record is None:
            record = self._rehydrate(run_id)
        if record is None:
            raise RunNotFoundError(f"no such run: {run_id}")
        return record
```

Change `resume_run` to return the committed unit ids so the endpoint can report them:

```python
    def resume_run(self, run_id: str) -> tuple[RunRecord, list[str]]:
        """Reload an INTERRUPTED run's state and continue from the first
        incomplete unit. Committed units are not re-verified (§4.5)."""
        record = self.get_run(run_id)
        if record.lifecycle != "INTERRUPTED":
            raise InvalidRequestError(f"run {run_id} is not interrupted (state={record.lifecycle})")

        committed_results: dict[str, UnitResult] = {}
        if record.state_path.exists():
            saved = json.loads(record.state_path.read_text())
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
        return record, sorted(committed_results)
```

- [ ] **Step 4: Add the route**

In `backend/app.py`, add after `cancel_run`:

```python
@app.post("/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict:
    """NFR-R2 / Step B7 -- continue an INTERRUPTED run from the first
    incomplete unit. Committed units are replayed from the checkpoint, not
    re-verified (§4.5: checkpoint after commit, never before)."""
    record, resumed_from_units = run_manager.resume_run(run_id)
    return {
        "run_id": record.run_id,
        "lifecycle": record.lifecycle,
        "resumed_from_units": resumed_from_units,
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_backend_service.py -v -k b7`
Expected: 5 PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/app.py backend/runs.py tests/test_backend_service.py
git commit -m "feat: expose run resume over HTTP and rehydrate records from disk (NFR-R2, B7)"
```

---

# Part D — B8 static asset serving

## Task 9: Serve a self-contained trace viewer with zero external references

**Files:**
- Create: `backend/static/index.html`
- Modify: `backend/app.py` (mounting comment)
- Test: `tests/test_backend_service.py`

**Interfaces:**
- Consumes: `GET /runs/{id}/events` (SSE), `GET /runs/{id}` (state)
- Produces: a mounted static route at `/`

**Design note — why one hand-written HTML file.** B8's acceptance is *"the full UI loads with all egress blocked"* and its three requirements are: serve from disk, self-host fonts, no runtime external requests. None of that needs a bundler. §3.9.4 makes the web UI a **[SHOULD]** and names it the first thing to cut, and the demo is in two days. A single file with inline CSS and vanilla JS satisfies B8 exactly, adds no npm dependency to a project whose central claim is offline reproducibility, and cannot acquire a CDN reference through a transitive package.

**Design note — fonts.** B8 says IBM Plex must be a local file. A woff2 binary cannot be created here, and downloading one would violate DC-1 during the build. The stylesheet therefore uses a local system stack with `IBM Plex Mono` named first, so it is used when installed and degrades locally when not. **Under no circumstances add an `@import` or `<link>` to Google Fonts or any CDN** — that is the exact failure B8 warns about. If a vendored `IBMPlexMono-Regular.woff2` is added to `backend/static/fonts/` later, add a matching `@font-face` with a relative `url()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_backend_service.py`:

```python
import re

_EXTERNAL_REF = re.compile(r"""(?:src|href|url)\s*[=(]\s*["']?(?:https?:)?//""", re.IGNORECASE)


def test_b8_static_index_exists_and_is_served():
    """B8: serve the frontend bundle from disk."""
    from backend.app import STATIC_DIR

    index = STATIC_DIR / "index.html"
    assert index.exists(), "B8 requires a UI to serve"

    with TestClient(app) as c:
        resp = c.get("/")
    assert resp.status_code == 200
    assert "<!doctype html" in resp.text.lower()


def test_b8_no_static_asset_references_an_external_host():
    """DC-1 / B8: 'no runtime external requests of any kind'. A CDN font, an
    external favicon, or a source map pointing off-machine all break the
    offline claim -- and would fail live during AC-11."""
    from backend.app import STATIC_DIR

    offenders = []
    for path in STATIC_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _EXTERNAL_REF.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert offenders == [], "external references in static assets:\n" + "\n".join(offenders)


def test_b8_no_static_asset_imports_a_font_from_a_cdn():
    """The specific failure B8 names: 'fonts fall back because a CDN was
    referenced'."""
    from backend.app import STATIC_DIR

    for path in STATIC_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".html", ".css"}:
            text = path.read_text(encoding="utf-8").lower()
            assert "fonts.googleapis" not in text
            assert "fonts.gstatic" not in text
            assert "@import" not in text


def test_b8_static_mount_does_not_shadow_the_api_routes():
    """Mounting StaticFiles at '/' with html=True must not swallow /health
    or /runs -- the UI would load and every call from it would 404."""
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/runs/no-such-run").status_code == 404
        assert c.get("/runs/no-such-run").json()["error_class"] == "RUN_NOT_FOUND"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_backend_service.py -v -k b8`
Expected: FAIL — `assert index.exists()` fails; `backend/static/` holds only `.gitkeep`.

- [ ] **Step 3: Create `backend/static/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LegacyWeaver — run trace</title>
<!-- DC-1 / BACKEND_PLAN B8: every byte of this page is served from disk.
     No CDN, no webfont import, no analytics. Adding an external reference
     here breaks the offline claim and would fail live during AC-11. -->
<style>
  :root {
    --bg: #0e1116; --panel: #161b22; --line: #262d36;
    --fg: #e6edf3; --dim: #8b949e;
    --ok: #3fb950; --warn: #d29922; --bad: #f85149; --info: #58a6ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: "IBM Plex Mono", ui-monospace, "Cascadia Mono", "Consolas", monospace;
    font-size: 13px; line-height: 1.5;
  }
  header {
    padding: 12px 16px; border-bottom: 1px solid var(--line);
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  }
  h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: .02em; }
  .sub { color: var(--dim); }
  input, button {
    font: inherit; background: var(--panel); color: var(--fg);
    border: 1px solid var(--line); border-radius: 4px; padding: 5px 9px;
  }
  button:hover { border-color: var(--info); cursor: pointer; }
  main { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 1px; background: var(--line); }
  section { background: var(--bg); padding: 12px 16px; min-height: 70vh; overflow-x: auto; }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--dim); margin: 0 0 10px; }
  .row { padding: 3px 0; border-bottom: 1px solid var(--line); white-space: pre-wrap; word-break: break-word; }
  .t { color: var(--dim); }
  .commit { color: var(--ok); } .escalate { color: var(--bad); }
  .cancel  { color: var(--warn); } .node { color: var(--info); }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); }
  th { color: var(--dim); font-weight: 500; }
  @media (max-width: 800px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>LegacyWeaver</h1>
  <span class="sub">local run trace · loopback only</span>
  <input id="runId" placeholder="run id" size="34" autocomplete="off">
  <button id="attach">Attach</button>
  <span id="status" class="sub">idle</span>
</header>
<main>
  <section>
    <h2>Trace events (FR-8.1)</h2>
    <div id="trace"></div>
  </section>
  <section>
    <h2>Units</h2>
    <table><thead><tr><th>Unit</th><th>Status</th><th>Calls</th><th>Mem</th></tr></thead>
      <tbody id="units"></tbody></table>
    <h2 style="margin-top:20px">Metrics (FR-8.2)</h2>
    <div id="metrics" class="sub">no run attached</div>
  </section>
</main>
<script>
// Renders what the server sends. It computes nothing: every number shown
// here is produced by the agent and is obtainable from `weaver report`
// (DC-4/DC-5). Deriving a value in this file would put a second decision
// point in the system.
(function () {
  var source = null;
  var el = function (id) { return document.getElementById(id); };

  function addRow(ev) {
    var d = document.createElement('div');
    d.className = 'row';
    var node = ev.node || '?';
    var cls = node === 'commit' ? 'commit' : node === 'escalate' ? 'escalate'
            : node === 'cancel' ? 'cancel' : 'node';
    d.innerHTML = '<span class="t">' + (ev.duration_seconds || 0).toFixed(2) + 's</span>  '
      + '<strong>' + esc(ev.unit || '*') + '</strong>  '
      + '<span class="' + cls + '">' + esc(node) + '</span>'
      + (ev.action ? '  · ' + esc(ev.action) : '')
      + (ev.outcome ? '  · ' + esc(String(ev.outcome)) : '');
    el('trace').appendChild(d);
    d.scrollIntoView({ block: 'nearest' });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function refreshState(id) {
    fetch('/runs/' + encodeURIComponent(id)).then(function (r) { return r.json(); }).then(function (s) {
      el('status').textContent = s.lifecycle;
      el('units').innerHTML = (s.units || []).map(function (u) {
        var cls = u.status === 'committed' ? 'commit' : u.status === 'escalated' ? 'escalate' : '';
        return '<tr><td>' + esc(u.unit_id) + '</td><td class="' + cls + '">' + esc(u.status)
             + '</td><td>' + u.model_calls + '</td><td>' + (u.memory_hit ? 'yes' : '—') + '</td></tr>';
      }).join('');
      el('metrics').textContent = s.metrics ? JSON.stringify(s.metrics, null, 2) : 'not yet available';
    }).catch(function () { el('status').textContent = 'unreachable'; });
  }

  el('attach').addEventListener('click', function () {
    var id = el('runId').value.trim();
    if (!id) { return; }
    if (source) { source.close(); }
    el('trace').innerHTML = '';
    el('status').textContent = 'attached';
    refreshState(id);
    source = new EventSource('/runs/' + encodeURIComponent(id) + '/events');
    source.onmessage = function (m) {
      try { addRow(JSON.parse(m.data)); } catch (e) { /* malformed frame: skip */ }
      refreshState(id);
    };
    source.onerror = function () { el('status').textContent = 'stream closed'; refreshState(id); };
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 4: Update the mounting comment in `backend/app.py`**

Replace the block at the end of `backend/app.py` (currently lines 189–198):

```python
# §5.1 / Step B8 -- serve frontend assets from disk. Mounted last so it
# cannot shadow the API routes declared above; StaticFiles(html=True)
# resolves "/" to index.html and 404s anything it does not hold, which is
# why /health and /runs still reach their handlers.
#
# Every asset under STATIC_DIR must be self-contained: no CDN, no webfont
# import, no external favicon (DC-1). tests/test_backend_service.py asserts
# this by scanning the directory -- a CDN reference added here would pass
# review and fail live during AC-11.
if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_backend_service.py -v -k b8`
Expected: 4 PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: no regressions — in particular `test_b8_static_mount_does_not_shadow_the_api_routes` confirms the existing endpoint tests still route correctly now that something is actually mounted at `/`.

- [ ] **Step 7: Commit**

```bash
git add backend/static/index.html backend/app.py tests/test_backend_service.py
git commit -m "feat: serve a self-contained offline trace viewer (B8, DC-1)"
```

---

# Part E — B9 conformance validation

## Task 10: Make BACKEND_PLAN Part VII §7.1 an executable table

**Files:**
- Create: `tests/test_conformance.py`
- Modify: `docs/specs/BACKEND_PLAN.md` (§2.1 audit row for §3.9.1)
- Modify: `README.md` (status table)

**Interfaces:**
- Consumes: everything built in Tasks 1–9
- Produces: one test per §7.1 row, each named for its SRS id

**Design note — honest skips.** Four rows (NFR-S1 host-execution audit, §7.2 offline test, §7.3 non-regression at 132 divergences, and the FR-8.1 full-run diff) require GnuCOBOL, Docker, or a firewall rule that this environment does not have. They are written as real tests guarded by `pytest.mark.skipif` **with the reason in the skip message**, so `pytest -rs` prints exactly what was not verified. A row that cannot run must never be silently absent — that is the difference between "validated against the SRS" and claiming to be.

**Design note — NFR-S1 is a known open gap.** Generated code compiles and runs on the host (`weaver/agent/attribution.py`, `weaver/execution.py`), not in the containers §3.9.3 requires. The conformance test for it therefore **asserts the gap is disclosed**, not that it is closed. Do not write a test that passes by pretending sandboxing exists.

- [ ] **Step 1: Write the conformance suite**

Create `tests/test_conformance.py`:

```python
"""BACKEND_PLAN.md Part VII §7.1 as executable rows.

One test per SRS id in the conformance table. Rows needing GnuCOBOL,
Docker, or a firewall rule are skipped with the reason stated, never
quietly omitted -- `pytest -rs tests/test_conformance.py` prints exactly
what was and was not verified (CLAUDE.md rule 12, DC-6).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HAS_COBC = shutil.which("cobc") is not None
HAS_JAVAC = shutil.which("javac") is not None
NEEDS_TOOLCHAIN = pytest.mark.skipif(
    not (HAS_COBC and HAS_JAVAC),
    reason="requires GnuCOBOL 3.x and javac on PATH (SRS §2.4); not verified in this environment",
)


# -- §3.9.1 command surface -------------------------------------------------

def test_srs_391_all_six_commands_are_present():
    """SRS §3.9.1 names six commands. All must parse."""
    from weaver.cli import build_parser

    parser = build_parser()
    subparsers = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    commands = set(subparsers[0].choices)

    assert {"migrate", "verify", "baseline", "replay", "memory", "report"} <= commands


def test_srs_391_defaults_are_verbatim():
    """--max-repairs 3, --model qwen2.5-coder:7b, --seed 42."""
    from weaver.agent.runspec import DEFAULT_MAX_REPAIRS, DEFAULT_MODEL, DEFAULT_SEED

    assert DEFAULT_MAX_REPAIRS == 3
    assert DEFAULT_MODEL == "qwen2.5-coder:7b"
    assert DEFAULT_SEED == 42


# -- NFR-M1: dependency direction -------------------------------------------

def test_nfr_m1_agent_imports_without_a_web_framework():
    """§3.3: the API imports the agent; the agent never imports the API.
    Verified in a subprocess where fastapi is blocked from importing."""
    script = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name.split('.')[0] in ('fastapi', 'starlette', 'backend'):\n"
        "            raise ImportError('blocked for NFR-M1: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "import weaver.agent.orchestrator\n"
        "import weaver.cli\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


# -- DC-5: every API number is obtainable from the CLI ----------------------

def test_dc5_api_metrics_come_from_the_same_function_the_cli_calls():
    """There must be exactly one implementation. If the backend computed
    metrics independently, the browser and the CLI could disagree."""
    import inspect

    import backend.runs as runs_module
    import weaver.cli as cli_module

    assert "compute_metrics" in inspect.getsource(runs_module.RunManager.metrics_for)
    assert "compute_metrics" in inspect.getsource(cli_module.run_report)
    assert runs_module.compute_metrics is cli_module.compute_metrics


def test_dc4_backend_contains_no_comparison_or_classification_logic():
    """§1.2: the backend does not compare output or classify defects.
    Importing those modules is how that boundary would erode."""
    forbidden = ("weaver.comparison", "weaver.classification")
    for module_path in Path("backend").glob("*.py"):
        source = module_path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in source, (
                f"{module_path} imports {name}; correctness must be decided in "
                f"exactly one place (DC-4)"
            )


# -- FR-8.1: run directory contract -----------------------------------------

def test_fr_81_run_root_matches_the_spec():
    """FR-8.1 names runs/<run_id>/trace.jsonl literally."""
    import backend.runs as runs_module
    from weaver.agent.orchestrator import RUNS_ROOT

    assert RUNS_ROOT == Path("runs")
    assert runs_module.RUNS_ROOT == RUNS_ROOT


# -- NFR-D1: reproducibility record -----------------------------------------

def test_nfr_d1_every_runspec_field_survives_a_round_trip():
    """A parameter that cannot be read back cannot reproduce a run."""
    import dataclasses

    from weaver.agent.runspec import RunSpec

    spec = RunSpec.default().replace(seed=7, max_repairs=9, model="m:1b", replay=True)
    restored = RunSpec.from_dict(spec.to_dict())

    for f in dataclasses.fields(RunSpec):
        assert getattr(restored, f.name) == getattr(spec, f.name), f.name


# -- §3.9.2 / AC-12: loopback enforcement -----------------------------------

def test_ac12_non_loopback_inference_host_aborts():
    from weaver.agent.inference import OfflineViolationError, _assert_loopback

    _assert_loopback("http://127.0.0.1:11434")
    _assert_loopback("http://localhost:11434")
    with pytest.raises(OfflineViolationError):
        _assert_loopback("http://198.51.100.7:11434")


# -- DC-1: no external references in served assets --------------------------

def test_dc1_static_assets_are_fully_self_contained():
    import re

    from backend.app import STATIC_DIR

    pattern = re.compile(r"""(?:src|href|url)\s*[=(]\s*["']?(?:https?:)?//""", re.IGNORECASE)
    for path in STATIC_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".html", ".css", ".js"}:
            assert not pattern.search(path.read_text(encoding="utf-8")), path


# -- NFR-S1: the known open gap, asserted as disclosed -----------------------

def test_nfr_s1_host_execution_gap_is_disclosed_not_hidden():
    """Generated code currently compiles and runs on the host, not in the
    containers §3.9.3 requires. CLAUDE.md rule 12 requires this stay
    explicitly marked not-implemented until it is built. This test fails if
    someone quietly drops the disclosure -- it does NOT assert sandboxing
    exists, because it does not.
    """
    readme = Path("README.md").read_text(encoding="utf-8").lower()
    assert "sandbox" in readme
    assert "nfr-s1" in readme or "3.9.3" in readme


# -- Toolchain-gated rows ----------------------------------------------------

@NEEDS_TOOLCHAIN
def test_ac9_self_comparison_yields_zero_divergences(tmp_path):
    """§7.3 non-regression: the CLI must work with the service stopped."""
    report = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, "-m", "weaver.cli", "verify",
         "--cobol", "fixtures/cobol/interest.cob",
         "--java", "baseline/Baseline.java",
         "--data", "fixtures/data/accounts.dat",
         "--report", str(report)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(report.read_text())
    assert payload["total_records"] == 201
    assert payload["divergence_count"] == 132


@pytest.mark.skip(reason="§7.2 offline test requires a firewall rule or physical "
                         "disconnection; must be executed manually and recorded (AC-11)")
def test_ac11_full_migration_with_all_egress_blocked():
    """Executed by hand per BACKEND_PLAN §7.2. Kept here so the row is
    visible in the conformance output rather than absent from it."""


@pytest.mark.skip(reason="NFR-R3 requires stopping the inference server mid-suite; "
                         "not automated to avoid a third environment dependency")
def test_nfr_r3_inference_unavailable_degrades_without_a_500():
    """Deterministic repairs proceed; status is degraded; no 500."""
```

- [ ] **Step 2: Run it and read the skip report**

Run: `python -m pytest tests/test_conformance.py -v -rs`
Expected: the non-gated rows PASS; the toolchain and manual rows report as SKIPPED **with their reasons printed**. Record this output — it is the B9 deliverable.

- [ ] **Step 3: Correct the BACKEND_PLAN conformance audit row**

In `docs/specs/BACKEND_PLAN.md`, the §2.1 table currently reads:

```
| §3.9.1 | CLI command surface | **PARTIAL** | `migrate`, `verify`, `report` implemented; `baseline`, `replay`, `memory` absent. Backend must not diverge from it. §3.4 |
```

Replace with:

```
| §3.9.1 | CLI command surface | **PASS** | All six commands implemented (`migrate`, `verify`, `baseline`, `replay`, `memory`, `report`); asserted by tests/test_conformance.py::test_srs_391_all_six_commands_are_present |
```

- [ ] **Step 4: Update the README status table**

In `README.md`, replace the Phase 3 row and the known-gaps list under **Status & roadmap**:

```markdown
| 3 | Local run service (`backend/`) — loopback HTTP API, SSE trace streaming, offline trace viewer | **Complete** — B1–B9; conformance rows executable via `pytest tests/test_conformance.py -rs` |
```

And replace the gaps list with:

```markdown
Known gaps, tracked rather than hidden (CLAUDE.md rule 12 — scope stays disclosed):

- Sandboxed execution of generated code (§3.9.3 / NFR-S1) — generated Java compiles and runs on the host, not inside a `--network=none --read-only` container. This is the largest outstanding gap and it gates AC-11's strongest form.
- Four conformance rows cannot run in a toolchain-less environment and are reported as skipped with reasons, not passed: the 201/132 end-to-end verification, the §7.2 all-egress-blocked run, and the NFR-R3 inference-unavailable path. Run `pytest tests/test_conformance.py -rs` to see the current list.
```

- [ ] **Step 5: Run the full suite one final time**

Run: `python -m pytest tests/ -v -rs`
Expected: all tests pass or skip with a stated reason. Zero failures. Capture the summary line.

- [ ] **Step 6: Commit**

```bash
git add tests/test_conformance.py docs/specs/BACKEND_PLAN.md README.md
git commit -m "test: make BACKEND_PLAN Part VII conformance table executable (B9)"
```

---

## Deviations logged, not fixed here

Real gaps that remain after this plan. Do not let any document imply otherwise.

1. **NFR-S1 / §3.9.3 sandboxing.** Generated code executes on the host. Task 10 asserts the *disclosure* survives; it does not close the gap. Closing it means routing `javac`/`java` and `cobc` through containers with `--network=none`, `--read-only` (writable `/out` tmpfs only), `--memory=2g`, `--cpus=2`, and a 30-second wall-clock kill. That is its own plan.
2. **§7.2 offline test.** Requires a firewall rule or physical disconnection. Must be executed by hand and recorded; it is AC-11 and is scheduled to run live.
3. **NFR-R3 degraded inference.** The error class `INFERENCE_UNAVAILABLE` exists in `backend/errors.py` and is never raised. Verifying that deterministic repairs still proceed with the model server down needs an integration harness that stops Ollama mid-run.
4. **`m4_baseline.json` is a single hand-recorded observation.** Task 6 gives `weaver baseline` the ability to regenerate it honestly, but `metrics.compute_metrics` still reads the committed file by default. Re-running baseline against the real fixture and replacing that file is a follow-up, and until it happens `equivalence_rate_unassisted` reflects an August 7 measurement, not a current one.
5. **Failure memory holds two cases, both SIGN.** Task 4 makes the store inspectable and portable; it does not enlarge it. The Phase S memory-reuse demonstration still rests on a thin corpus.

---

## Self-Review

**1. Spec coverage.**

| Requirement | Task |
|---|---|
| B6 escalation depth (FR-4.5, FR-6.4, FR-7.3) | Task 7 |
| B7 checkpoint/resume (NFR-R2) | Task 8 |
| B8 static serving, self-hosted assets (DC-1) | Task 9 |
| B9 conformance validation (Part VII §7.1) | Task 10 |
| §3.9.1 `report <run_id>` | Task 3 |
| §3.9.1 `memory list\|export\|import` | Task 4 |
| §3.9.1 `replay <run_id>` (FR-8.4) | Task 5 |
| §3.9.1 `baseline` (FR-8.3, AC-7) | Task 6 |
| FR-8.1 run root | Task 1 |
| NFR-D1 parameter threading | Task 2 |
| DC-4 / DC-5 boundary | Tasks 7, 10 |
| NFR-M1 import direction | Task 10 |

Rows deliberately **not** covered, and stated as such in "Deviations logged": NFR-S1 sandboxing, §7.2 offline execution, NFR-R3 degraded inference.

**2. Placeholder scan.** No TBDs. Every code step carries literal, runnable code. Task 7 is deliberately test-only with an explicit instruction to stop and fix `runs.py` if a test fails, rather than inventing a change to code that may already be correct — stated inline rather than left implicit. Task 9's font decision is stated as a constraint with its reason, not deferred.

**3. Type consistency.**
- `RunSpec.from_dict` is defined in Task 2 and consumed in Tasks 5 and 10 under that exact name.
- `RunSpec.model_digest` is added in Task 2 and asserted in Task 2's own test; `to_dict`/`from_dict` round-trip covers it in Task 10.
- `resolve_run_dir(target: Path) -> Path` is defined in Task 3 and called in Task 5.
- `FailureMemory.merge_from(other_path) -> tuple[int, int]` is defined in Task 4 and used only by `run_memory`.
- `RunManager._spec_for(req) -> RunSpec` is a `@staticmethod` in Task 2, called as `self._spec_for(...)` in both workers (valid) and as `RunManager._spec_for(req)` in its test (valid).
- **`resume_run` changes signature** from `-> RunRecord` to `-> tuple[RunRecord, list[str]]` in Task 8. The only caller is the new endpoint added in the same task; `grep -rn "resume_run" --include=*.py .` returns `backend/runs.py` and `backend/app.py` only. Re-run that grep after Task 8 to confirm nothing new landed.
- `BaselineResult` field names in Task 6's dataclass match every assertion in `tests/test_baseline.py` and the `baseline.json` keys read in Task 6's CLI table.
- `_compile_and_measure` is monkeypatched by string path `"weaver.agent.baseline._compile_and_measure"` in tests and defined at module level in `baseline.py` — consistent.
- The CLI `report` argument is renamed `run_dir` → `run` in Task 3; `tests/test_backend_service.py::test_cli_report_and_api_metrics_are_byte_identical` may construct the namespace directly and is explicitly called out in Task 3 Step 4.

**4. Ordering.** Tasks 1 and 2 are prerequisites for 3, 5, 8 and 10. Tasks 3–6 are independent of each other. Task 10 depends on all of 1–9.
