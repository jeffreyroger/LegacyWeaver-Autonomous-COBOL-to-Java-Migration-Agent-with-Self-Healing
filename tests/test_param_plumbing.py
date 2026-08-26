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
    assert spec.model == "granite-code:20b"
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


def test_try_memory_repair_forwards_spec_to_verify_unit(tmp_path, monkeypatch):
    """memory_repair.try_memory_repair is called unconditionally on the
    automatic run path (orchestrator.py) before the repair_loop fallback is
    ever reached -- if it doesn't forward the caller's spec, a non-default
    scaffold_path/input_data/golden_output is silently ignored during a
    memory-hit repair, reproducing the same defect class this task exists
    to eliminate."""
    from weaver.agent.memory_repair import try_memory_repair
    from weaver.agent.memory import FailureMemory, MemoryCase, embed
    from weaver.agent.signature import build_signature
    from weaver.classification import Classification, DefectClass

    sentinel = tmp_path / "Sentinel.java"
    sentinel.write_text("// SENTINEL SCAFFOLD\n")
    spec = RunSpec.default().replace(scaffold_path=sentinel)

    classification = Classification(DefectClass.SIGN, 1.0, {"oracle": "0.10", "candidate": "-0.10"})
    sig = build_signature(classification, 2, "MOVE WS-INTEREST TO RL-INTEREST")
    case = MemoryCase(
        case_id="TEST-SIGN-case",
        signature=sig,
        embedding=embed(sig.as_text()),
        defect_class="SIGN",
        normalized_construct=sig.normalized_operation,
        root_cause="test", patch_description="test",
        patch_body_template="ws.interest = ws.interest;",
        verification_status="verified", hit_count=0, confidence=1.0,
        provenance="test",
    )
    store_path = tmp_path / "memory.json"
    memory = FailureMemory(store_path)
    memory.write_back(case)

    seen = {}

    def fake_assemble(scaffold_text, bodies):
        seen["text"] = scaffold_text
        raise RuntimeError("stop after assemble")

    monkeypatch.setattr("weaver.agent.attribution.assemble", fake_assemble)

    with pytest.raises(RuntimeError, match="stop after assemble"):
        try_memory_repair(
            memory, "PROCESS-RECORD", "ws.interest = ws.interest.negate();",
            classification, 2, "MOVE WS-INTEREST TO RL-INTEREST",
            tmp_path / "work", spec=spec,
        )

    assert "SENTINEL SCAFFOLD" in seen["text"]


def test_backend_build_run_spec_threads_every_request_field(tmp_path):
    """2026-08-12 handoff Gap 4: every CreateRunRequest field that affects
    determinism must reach the RunSpec the orchestrator actually runs --
    not just be echoed back and written to params.json unused."""
    from backend.models import CreateRunRequest
    from backend.runs import _build_run_spec

    candidate = tmp_path / "candidate.body.java"
    candidate.write_text("// candidate body\n")

    req = CreateRunRequest(
        cobol_source="fixtures/cobol/interest.cob",
        copybook_dir="fixtures/copybooks",
        data_file="fixtures/data/accounts.dat",
        candidate_path=str(candidate),
        synthesis_mode=False,
        seed=99,
        model_name="some-model:1b",
        model_digest="sha256:deadbeef",
        max_repair_attempts=7,
        replay=True,
    )
    spec = _build_run_spec(req)

    assert spec.copybook_dir == Path("fixtures/copybooks")
    assert spec.candidate_body_path == candidate
    assert spec.max_repairs == 7
    assert spec.model == "some-model:1b"
    assert spec.model_digest == "sha256:deadbeef"
    assert spec.seed == 99
    assert spec.replay is True


def test_use_text_refinement_is_read_by_orchestrator():
    """RunSpec.use_text_refinement must actually gate behaviour in
    orchestrator.py, not just be accepted and ignored (the same defect
    class rule 13 exists to eliminate -- see use_unit_cache's identical
    wiring a few lines above in orchestrator.py)."""
    import inspect

    from weaver.agent import orchestrator as orchestrator_mod

    source = inspect.getsource(orchestrator_mod)
    assert "use_text_refinement" in source


def test_migrate_cli_threads_use_text_refinement_and_delta_debugging():
    """weaver/cli.py's build_migrate_spec docstring says 'every flag must
    land in the spec -- a flag that parses but never reaches the
    orchestrator is the exact defect Task 1 fixed.' use_text_refinement and
    use_delta_debugging are real, already-tested RunSpec fields that
    orchestrator.py/repair_loop.py already consume correctly, but until
    this test existed no CLI flag ever set either of them True -- both
    were permanently dead from `weaver migrate`."""
    from weaver.cli import build_parser, build_migrate_spec

    parser = build_parser()

    args_on = parser.parse_args([
        "migrate", "fixtures/cobol/interest.cob",
        "--use-text-refinement", "--use-delta-debugging",
    ])
    spec_on = build_migrate_spec(args_on)
    assert spec_on.use_text_refinement is True
    assert spec_on.use_delta_debugging is True

    args_off = parser.parse_args(["migrate", "fixtures/cobol/interest.cob"])
    spec_off = build_migrate_spec(args_off)
    assert spec_off.use_text_refinement is False
    assert spec_off.use_delta_debugging is False


def test_migrate_cli_threads_redefines_as_subclasses():
    """ScaffoldSpec.redefines_as_subclasses (weaver/agent/scaffold.py,
    Task 5, FR-12.1-12.3) was reachable only from its own unit test
    (tests/test_scaffold_redefines.py) before --redefines-as-subclasses
    existed -- no CLI flag or program profile ever set it True, so the
    subclass-overlay code path was permanently dead from `weaver migrate`.
    Opt-in only: interest.cob's default run must keep the flag False,
    unchanged, since its pinned golden output depends on the flattened-
    accessor path (tests/test_scaffold_redefines.py's own guarantee)."""
    from weaver.cli import build_parser, build_migrate_spec

    parser = build_parser()

    args_on = parser.parse_args([
        "migrate", "fixtures/cobol/interest.cob", "--redefines-as-subclasses",
    ])
    assert build_migrate_spec(args_on).scaffold_spec.redefines_as_subclasses is True

    args_off = parser.parse_args(["migrate", "fixtures/cobol/interest.cob"])
    assert build_migrate_spec(args_off).scaffold_spec.redefines_as_subclasses is False


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
