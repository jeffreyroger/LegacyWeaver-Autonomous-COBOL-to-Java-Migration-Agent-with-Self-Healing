"""backend/runs.py's RunSpec construction and candidate-supplied-mode
validation — regression coverage for the 2026-08-12 audit fix (RunSpec
silently dropped copybook_dir/seed/model_name/max_repair_attempts/replay)
and for the candidate-supplied-mode feature built the same day.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend.errors import InvalidRequestError
from backend.models import CreateRunRequest
from backend.runs import RunManager, _build_run_spec
from weaver.agent.runspec import RunSpec


def test_build_run_spec_threads_every_parameter():
    req = CreateRunRequest(
        cobol_source="fixtures/cobol/interest.cob",
        copybook_dir="fixtures/cobol/copybooks",
        data_file="fixtures/data/accounts.dat",
        seed=99,
        model_name="some-other-model:1b",
        max_repair_attempts=7,
        replay=True,
    )
    spec = _build_run_spec(req)

    assert spec.copybook_dir == Path("fixtures/cobol/copybooks")
    assert spec.seed == 99
    assert spec.model == "some-other-model:1b"
    assert spec.max_repairs == 7
    assert spec.replay is True
    assert spec.candidate_body_path is None  # synthesis_mode defaults True


def test_build_run_spec_threads_the_2026_08_26_opt_in_flags():
    """use_text_refinement/use_delta_debugging/use_batch_synthesis/
    redefines_as_subclasses (weaver/cli.py's `migrate` flags of the same
    names) were reachable only from the CLI until this test existed --
    CreateRunRequest never carried them, so a backend-launched run could
    not opt into any of the four. All default False; a request that omits
    them must produce a spec byte-identical to before these fields
    existed."""
    req_on = CreateRunRequest(
        cobol_source="fixtures/cobol/interest.cob",
        data_file="fixtures/data/accounts.dat",
        use_text_refinement=True,
        use_delta_debugging=True,
        use_batch_synthesis=True,
        redefines_as_subclasses=True,
    )
    spec_on = _build_run_spec(req_on)
    assert spec_on.use_text_refinement is True
    assert spec_on.use_delta_debugging is True
    assert spec_on.use_batch_synthesis is True
    assert spec_on.scaffold_spec.redefines_as_subclasses is True

    req_off = CreateRunRequest(cobol_source="fixtures/cobol/interest.cob",
                                data_file="fixtures/data/accounts.dat")
    spec_off = _build_run_spec(req_off)
    assert spec_off.use_text_refinement is False
    assert spec_off.use_delta_debugging is False
    assert spec_off.use_batch_synthesis is False
    assert spec_off.scaffold_spec.redefines_as_subclasses is False


def test_build_run_spec_skips_program_profile_resolution_for_a_leaf_first_request(tmp_path):
    """leaf_first=True means cobol_source is a DIRECTORY of *.cob files,
    not a single program file -- program_profile() parses one file
    through the real COBOL frontend and would raise on a directory.
    LeafOrchestrator._run_file_based re-resolves each DAG node's own
    profile individually; this base spec must stay at plain defaults."""
    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    req = CreateRunRequest(
        cobol_source=str(program_dir), data_file="fixtures/data/multiprog/accounts.dat", leaf_first=True,
    )
    spec = _build_run_spec(req)  # must not raise (program_profile() on a directory would)
    assert spec.cobol_source == program_dir
    # RunSpec itself has no leaf_first concept -- LeafOrchestrator.
    # _run_file_based resolves each DAG node's real scaffold_spec/
    # golden_output individually; this base spec stays at plain defaults.
    assert spec.scaffold_spec == RunSpec.default().scaffold_spec


def test_build_run_spec_resolves_program_profile_not_interest_defaults():
    req = CreateRunRequest(cobol_source="fixtures/cobol_feecalc/feecalc.cob",
                            data_file="fixtures/data_feecalc/fees.dat")
    spec = _build_run_spec(req)

    assert spec.scaffold_spec.paragraph_id == "COMPUTE-FEE"
    assert "feecalc" in str(spec.golden_output)


def test_build_run_spec_sets_candidate_body_path_when_synthesis_mode_false():
    req = CreateRunRequest(
        cobol_source="fixtures/cobol/interest.cob",
        data_file="fixtures/data/accounts.dat",
        synthesis_mode=False,
        candidate_path="reference/process_record.body.java",
    )
    spec = _build_run_spec(req)

    assert spec.candidate_body_path == Path("reference/process_record.body.java")


def test_create_run_rejects_synthesis_mode_false_without_candidate_path(tmp_path, monkeypatch):
    import backend.runs as runs_module

    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    manager = RunManager()
    req = CreateRunRequest(cobol_source="fixtures/cobol/interest.cob",
                            data_file="fixtures/data/accounts.dat", synthesis_mode=False)
    with pytest.raises(InvalidRequestError):
        manager.create_run(req)


def test_create_run_rejects_nonexistent_candidate_path(tmp_path, monkeypatch):
    import backend.runs as runs_module

    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    manager = RunManager()
    req = CreateRunRequest(cobol_source="fixtures/cobol/interest.cob",
                            data_file="fixtures/data/accounts.dat", synthesis_mode=False,
                            candidate_path="does/not/exist.body.java")
    with pytest.raises(InvalidRequestError):
        manager.create_run(req)
