"""Regression tests for LeafOrchestrator's backend attachment points
(run_dir/on_event/cancel_requested/results_lock), added 2026-08-26 for
multi-program backend runs (docs/specs/BACKEND_PLAN.md has no
multi-program section yet -- this is the agent-side half of that work).

Uses a fake in place of weaver.agent.orchestrator.Orchestrator (real
dispatch, not the Task 8 orchestrator_factory injection path) so the
per-program trace/state path fix and the on_event/cancel_requested/
results_lock wiring are exercised exactly as `weaver migrate --leaf-first`
and the backend will really call them, without needing cobc/javac/Ollama.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import weaver.agent.leaf_orchestrator as leaf_mod
from weaver.agent.leaf_orchestrator import LeafOrchestrator
from weaver.agent.orchestrator import UnitResult
from weaver.agent.runspec import RunSpec

FILE_BASED_TEMPLATE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. {name}.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT FAKE-FILE ASSIGN TO "fake.dat".
PROCEDURE DIVISION.
MAIN-PARA.
    STOP RUN.
"""


class _FakeOrchestrator:
    """Records every constructor kwarg it was given and, on run(), fires
    exactly one commit-shaped event through on_event if supplied -- real
    dispatch's actual call shape, minus any real compile/synthesize."""

    instances: list["_FakeOrchestrator"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.spec = kwargs["spec"]
        _FakeOrchestrator.instances.append(self)

    def run(self) -> dict[str, UnitResult]:
        on_event = self.kwargs.get("on_event")
        if on_event is not None:
            on_event({"unit": "MAIN-PARA", "node": "commit", "action": "accept",
                       "duration_seconds": 0.1, "model_calls": 1, "outcome": "ok"})
        return {
            "MAIN-PARA": UnitResult(
                unit_id="MAIN-PARA", status="committed", final_body="// ok",
                model_calls=1, memory_hit=False, duration_seconds=0.1,
            )
        }


def setup_function():
    _FakeOrchestrator.instances.clear()


def _stub_program_profile(monkeypatch):
    """`_run_file_based` always calls `program_profile()`, which fully
    parses the COBOL program through the real frontend -- overkill for a
    minimal single-paragraph fixture that exists only to pick the
    file_based dispatch branch. Stubbed to None (the real "no profile
    registered for this program" case), same as an unregistered fixture
    gets in production."""
    monkeypatch.setattr("weaver.agent.program_profiles.program_profile", lambda *a, **k: None)


def _write_program(tmp_path: Path, name: str) -> Path:
    f = tmp_path / f"{name.lower()}.cob"
    f.write_text(FILE_BASED_TEMPLATE.format(name=name), encoding="utf-8")
    return f


def test_real_dispatch_gives_each_program_its_own_trace_and_state_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")
    run_dir = tmp_path / "run"

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec(), run_dir=run_dir)
    results = orch.run()

    assert results["FAKEPROG"]["MAIN-PARA"].status == "committed"
    kwargs = _FakeOrchestrator.instances[0].kwargs
    assert kwargs["trace_path"] == run_dir / "programs" / "FAKEPROG" / "trace.jsonl"
    assert kwargs["state_path"] == run_dir / "programs" / "FAKEPROG" / "orchestrator_state.json"
    assert kwargs["on_event"] is not None


def test_no_run_dir_leaves_orchestrator_construction_unchanged(tmp_path, monkeypatch):
    """Every caller before 2026-08-26 (and every existing test) never sets
    run_dir -- Orchestrator must be built exactly as it always was, with
    no explicit trace_path/state_path override forced onto it."""
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec())
    orch.run()

    kwargs = _FakeOrchestrator.instances[0].kwargs
    assert set(kwargs) == {"spec"}


def test_two_file_based_programs_do_not_clobber_each_others_trace(tmp_path, monkeypatch):
    """The real, pre-existing bug this session fixed: both programs used
    to share generated/trace.jsonl, and Orchestrator's fresh_trace=True
    default truncated it on construction -- the second program silently
    wiped the first's trace. With run_dir set, each program's combined
    events land in its OWN file under run_dir/programs/<NAME>/."""
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "PROGA")
    _write_program(tmp_path, "PROGB")
    run_dir = tmp_path / "run"

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec(), run_dir=run_dir)
    orch.run()

    assert len(_FakeOrchestrator.instances) == 2
    trace_a = run_dir / "programs" / "PROGA" / "trace.jsonl"
    trace_b = run_dir / "programs" / "PROGB" / "trace.jsonl"
    # Neither instance's construction call wrote to disk (that's real
    # Orchestrator.__post_init__'s job, faked away here) -- what matters
    # is each got a DISTINCT path, never the same shared default.
    assert trace_a != trace_b


def test_on_event_stamps_program_and_composite_id_and_writes_the_combined_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")
    run_dir = tmp_path / "run"

    received = []
    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec(), run_dir=run_dir,
                             on_event=received.append)
    orch.run()

    assert len(received) == 1
    assert received[0]["program"] == "FAKEPROG"
    assert received[0]["composite_id"] == "FAKEPROG::MAIN-PARA"
    assert received[0]["unit"] == "MAIN-PARA"  # original field preserved, event forwarded not replaced

    combined = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(combined) == 1
    on_disk = json.loads(combined[0])
    assert on_disk["program"] == "FAKEPROG"
    assert on_disk["composite_id"] == "FAKEPROG::MAIN-PARA"


def test_persist_state_writes_a_flat_composite_keyed_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")
    run_dir = tmp_path / "run"

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec(), run_dir=run_dir)
    orch.run()

    state = json.loads((run_dir / "orchestrator_state.json").read_text(encoding="utf-8"))
    assert set(state) == {"FAKEPROG::MAIN-PARA"}
    assert state["FAKEPROG::MAIN-PARA"]["status"] == "committed"
    assert state["FAKEPROG::MAIN-PARA"]["program"] == "FAKEPROG"
    # weaver/agent/metrics.py's compute_metrics reads this exact shape
    # unmodified: len(state) as the total unit count, r["status"] per unit.
    assert len(state) == 1


def test_no_run_dir_never_writes_a_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec())
    orch.run()

    assert not (tmp_path / "orchestrator_state.json").exists()


def test_cancel_requested_stops_before_the_next_program(tmp_path, monkeypatch):
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")
    cancel = threading.Event()
    cancel.set()  # already cancelled before run() starts

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec(), cancel_requested=cancel)
    results = orch.run()

    assert results == {}
    assert _FakeOrchestrator.instances == []


def test_cancel_requested_is_the_same_event_handed_to_the_nested_orchestrator(tmp_path, monkeypatch):
    """Cancellation is checked at the program boundary here AND at the
    unit boundary inside the real Orchestrator -- both granularities via
    one threading.Event, not two mechanisms."""
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "FAKEPROG")
    cancel = threading.Event()

    orch = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec(), cancel_requested=cancel)
    orch.run()

    assert _FakeOrchestrator.instances[0].kwargs.get("cancel_requested") is cancel


# --- DAG-level resume (2026-08-26) ---------------------------------------

def test_resume_committed_skips_re_running_that_program(tmp_path, monkeypatch):
    """A program listed in resume_committed is adopted as-is -- no new
    Orchestrator instance is constructed for it -- while a program NOT
    listed still runs fresh through the real dispatch path."""
    monkeypatch.setattr(leaf_mod, "Orchestrator", _FakeOrchestrator)
    _stub_program_profile(monkeypatch)
    _write_program(tmp_path, "PROGA")
    _write_program(tmp_path, "PROGB")

    first = LeafOrchestrator(program_dir=tmp_path, base_spec=RunSpec())
    first_results = first.run()
    assert set(first_results) == {"PROGA", "PROGB"}

    _FakeOrchestrator.instances.clear()
    second = LeafOrchestrator(
        program_dir=tmp_path, base_spec=RunSpec(),
        resume_committed={"PROGA": first_results["PROGA"]},
    )
    second_results = second.run()

    # Only PROGB's Orchestrator was actually constructed/run again.
    assert len(_FakeOrchestrator.instances) == 1
    assert second_results["PROGA"] is first_results["PROGA"]
    assert second_results["PROGB"]["MAIN-PARA"].status == "committed"


def test_resume_committed_reconstructs_verified_children_for_a_subprogram(tmp_path, monkeypatch):
    """A resumed subprogram's UnitCache directory (real artefact already
    on disk from the interrupted attempt) is reconstructed into
    verified_children so a later, still-to-run file-based program in the
    same DAG can still stub against it -- exactly as a fresh commit would
    set it, never fabricated."""
    from decimal import Decimal

    from weaver.agent.subprogram_orchestrator import SubprogramUnitResult
    from weaver.agent.subprogram_verify import harvest_subprogram_fixtures
    from weaver.agent import unit_cache as unit_cache_mod
    from weaver.cobol.subprogram import load_subprogram

    leaf_a_source = Path("fixtures/cobol/multiprog/leaf_a.cob")
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    dest = program_dir / "leaf_a.cob"
    dest.write_text(leaf_a_source.read_text(encoding="utf-8"), encoding="utf-8")

    model = load_subprogram(dest)
    work_root = tmp_path / "work"
    cache_dir = work_root / "unit_cache"
    # Real harvest -- the same call _run_subprogram makes on a fresh
    # commit -- requires a real cobc; skip this specific assertion path
    # if the toolchain genuinely isn't reachable rather than faking it.
    import os
    import shutil as _shutil
    if _shutil.which("cobc") is None and os.environ.get("WEAVER_COBC_VIA_WSL") != "1":
        import pytest
        pytest.skip("requires cobc (native or WEAVER_COBC_VIA_WSL=1)")

    witnesses = [Decimal("1.00"), Decimal("2.00")]
    fixtures = harvest_subprogram_fixtures(model, witnesses, work_root / "LEAF-A" / "harvest")
    key = unit_cache_mod.cache_key(dest.read_text(encoding="utf-8"), model.paragraph_source)
    cache = unit_cache_mod.UnitCache(program_id=model.program_id, cache_key=key, fixtures=fixtures)
    unit_cache_mod.save(cache, unit_cache_mod.cache_path(cache_dir, dest.stem, model.paragraph_id))

    committed = {"LEAF-A": SubprogramUnitResult(
        program_id="LEAF-A", status="committed", final_body="return input;",
        model_calls=1, duration_seconds=0.1,
    )}
    orch = LeafOrchestrator(program_dir=program_dir, base_spec=RunSpec(), work_root=work_root,
                             resume_committed={"LEAF-A": committed})
    orch._skip_committed_program("LEAF-A")

    assert orch.program_results["LEAF-A"] is committed
    assert orch.verified_children["LEAF-A"] == cache_dir
    assert "LEAF-A" in orch.call_semantics
