"""backend/runs.py's RunSpec construction and candidate-supplied-mode
validation — regression coverage for the 2026-08-12 audit fix (RunSpec
silently dropped copybook_dir/seed/model_name/max_repair_attempts/replay)
and for the candidate-supplied-mode feature built the same day.
"""

from __future__ import annotations

import threading

import pytest

from backend.errors import InvalidRequestError
from backend.models import CreateRunRequest
from backend.runs import RunManager, _build_run_spec


def test_build_run_spec_threads_every_parameter():
    req = CreateRunRequest(
        cobol_source="zuse/examples/input/interest.cob",
        copybook_dir="zuse/examples/input/copybooks",
        data_file="zuse/examples/input/data/accounts.dat",
        seed=99,
        model_name="some-other-model:1b",
        max_repair_attempts=7,
        replay=True,
    )
    spec = _build_run_spec(req)

    assert str(spec.copybook_dir) == "zuse/examples/input/copybooks"
    assert spec.seed == 99
    assert spec.model == "some-other-model:1b"
    assert spec.max_repairs == 7
    assert spec.replay is True
    assert spec.candidate_body_path is None  # synthesis_mode defaults True


def test_build_run_spec_resolves_program_profile_not_interest_defaults():
    req = CreateRunRequest(cobol_source="zuse/examples/input/feecalc.cob",
                            data_file="zuse/examples/input/data/fees.dat")
    spec = _build_run_spec(req)

    assert spec.scaffold_spec.paragraph_id == "COMPUTE-FEE"
    assert "feecalc" in str(spec.golden_output)


def test_build_run_spec_sets_candidate_body_path_when_synthesis_mode_false():
    req = CreateRunRequest(
        cobol_source="zuse/examples/input/interest.cob",
        data_file="zuse/examples/input/data/accounts.dat",
        synthesis_mode=False,
        candidate_path="zuse/examples/reference/process_record.body.java",
    )
    spec = _build_run_spec(req)

    assert str(spec.candidate_body_path) == "zuse/examples/reference/process_record.body.java"


def test_create_run_rejects_synthesis_mode_false_without_candidate_path(tmp_path, monkeypatch):
    import backend.runs as runs_module

    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    manager = RunManager()
    req = CreateRunRequest(cobol_source="zuse/examples/input/interest.cob",
                            data_file="zuse/examples/input/data/accounts.dat", synthesis_mode=False)
    with pytest.raises(InvalidRequestError):
        manager.create_run(req)


def test_create_run_rejects_nonexistent_candidate_path(tmp_path, monkeypatch):
    import backend.runs as runs_module

    monkeypatch.setattr(runs_module, "RUNS_ROOT", tmp_path / "runs")
    manager = RunManager()
    req = CreateRunRequest(cobol_source="zuse/examples/input/interest.cob",
                            data_file="zuse/examples/input/data/accounts.dat", synthesis_mode=False,
                            candidate_path="does/not/exist.body.java")
    with pytest.raises(InvalidRequestError):
        manager.create_run(req)
