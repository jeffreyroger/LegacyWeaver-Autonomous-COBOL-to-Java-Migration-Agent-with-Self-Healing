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
