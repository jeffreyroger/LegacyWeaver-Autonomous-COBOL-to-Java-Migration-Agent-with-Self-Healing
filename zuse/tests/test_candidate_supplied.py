"""Candidate-supplied mode — BACKEND_PLAN.md §4.2 ("candidate path or
synthesis mode"), implemented 2026-08-12.

Orchestrator.candidate_body_path lets a caller supply a Java method body
directly instead of synthesizing one, with zero model calls. These tests
exercise the real Orchestrator against the real interest.cob fixture
(requires javac; no cobc/GnuCOBOL needed since verify_unit compares
against the already-frozen golden output, never re-invokes the oracle).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from zuse.agent.orchestrator import Orchestrator
from zuse.agent.runspec import RunSpec

REPO_REFERENCE_BODY = Path(__file__).resolve().parent.parent / "examples" / "reference" / "process_record.body.java"

requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_correct_supplied_candidate_commits_with_zero_model_calls(tmp_path):
    spec = RunSpec.default().replace(candidate_body_path=REPO_REFERENCE_BODY)
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")
    results = orch.run()

    assert set(results) == {"PROCESS-RECORD"}
    result = results["PROCESS-RECORD"]
    assert result.status == "committed"
    assert result.model_calls == 0
    assert result.memory_hit is False
    assert result.last_report.divergence_count == 0


@requires_javac
def test_supplied_candidate_that_fails_to_compile_escalates_without_model_call(tmp_path):
    broken = tmp_path / "broken.body.java"
    broken.write_text("this is not valid java {{{", encoding="utf-8")
    spec = RunSpec.default().replace(candidate_body_path=broken, max_repairs=0)
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")
    results = orch.run()

    result = results["PROCESS-RECORD"]
    # model_calls counts synthesis calls only (0, since the body was
    # supplied) -- the repair loop budget is exhausted at max_repairs=0
    # without a model call either, since best_result.compiled is False on
    # the very first check and there are zero attempts left to try.
    assert result.model_calls == 0
    assert result.status == "escalated"


def test_run_raises_for_multi_unit_program_with_supplied_candidate(tmp_path, monkeypatch):
    """A single candidate_body_path can't disambiguate which of several
    synthesis units it belongs to -- Orchestrator.run() must fail loudly,
    not silently apply it to the first unit only."""
    from zuse.agent import orchestrator as orch_module
    from zuse.agent.segment import Paragraph

    fake_units = [
        Paragraph(identifier="UNIT-A", source="", start_line=1, end_line=1),
        Paragraph(identifier="UNIT-B", source="", start_line=2, end_line=2),
    ]
    monkeypatch.setattr(orch_module.Orchestrator, "_plan", lambda self: fake_units)

    spec = RunSpec.default().replace(candidate_body_path=tmp_path / "whatever.body.java")
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")
    with pytest.raises(ValueError, match="single.*paragraph body"):
        orch.run()
