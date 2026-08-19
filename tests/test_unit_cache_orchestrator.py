"""Orchestrator/RunSpec unit-cache wiring — GRAPH_PLAN.md M8.

Opt-in only (RunSpec.use_unit_cache=False by default): tests_candidate_
supplied.py's existing suite already proves the default path is unchanged
by this feature's addition (same file, same tests, still green). These
tests cover the two states use_unit_cache=True can be in:

1. No valid cache present -> fall back to attribution.verify_unit,
   exactly as if the flag were off (AC-17 -- never silently skip
   verification just because the cache lookup missed).
2. A valid cache present -> the fast path
   (weaver.agent.replay_verify.verify_unit_from_cache) is actually used,
   with the exact same committed outcome as the non-cached run (M7's
   equivalence proof is what makes this a safe claim to test for).

State 2 needs a real harvested cache (real GnuCOBOL run) and lives in
test_unit_cache_orchestrator_live.py, skipped without cobc.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from weaver.agent.orchestrator import Orchestrator
from weaver.agent.runspec import RunSpec

REPO_REFERENCE_BODY = Path(__file__).resolve().parent.parent / "reference" / "process_record.body.java"

requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_unit_cache_enabled_but_no_cache_present_falls_back_and_still_commits(tmp_path):
    spec = RunSpec.default().replace(
        candidate_body_path=REPO_REFERENCE_BODY,
        use_unit_cache=True,
        unit_cache_dir=tmp_path / "nonexistent_cache",
    )
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")
    results = orch.run()

    result = results["PROCESS-RECORD"]
    assert result.status == "committed"
    assert result.last_report.divergence_count == 0

    trace = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "unit cache miss" in trace


@requires_javac
def test_unit_cache_disabled_never_mentions_the_cache_in_the_trace(tmp_path):
    """Sanity check on the trace-message wiring itself: with the flag off,
    the fallback-specific message must never appear (it would be
    confusing/misleading in a run that never opted in)."""
    spec = RunSpec.default().replace(candidate_body_path=REPO_REFERENCE_BODY, use_unit_cache=False)
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")
    orch.run()

    trace = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "unit cache" not in trace
