"""Orchestrator unit-cache fast path, with a real valid cache — GRAPH_PLAN.md
M8's exit criterion: "use_unit_cache=True reproduces identical orchestrator
outcomes to use_unit_cache=False on every fixture."

Builds a real harvested UnitCache (real GnuCOBOL compile + run, same as
test_trace_harvest.py's live test), saves it under a RunSpec's
unit_cache_dir, then runs the Orchestrator once with use_unit_cache=True
and once with it False, on the same real fixture, and confirms both reach
the exact same committed outcome -- with the cached run's trace actually
showing the fast path was taken, not a coincidental fallback.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.graph import from_paragraphs
from weaver.agent.instrument import instrument
from weaver.agent.orchestrator import Orchestrator
from weaver.agent.runspec import RunSpec
from weaver.agent.segment import segment
from weaver.agent.trace_harvest import harvest
from weaver.agent.unit_cache import UnitCache, cache_key, cache_path, save

requires_cobc = pytest.mark.skipif(shutil.which("cobc") is None, reason="requires GnuCOBOL (cobc) on PATH")

REPO_REFERENCE_BODY = Path(__file__).resolve().parent.parent / "reference" / "process_record.body.java"


def _build_real_cache(spec: RunSpec, cache_dir: Path) -> None:
    source = spec.cobol_source.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)
    copybook_dir = spec.cobol_source.parent / "copybooks"
    instrumented = instrument(source, paragraphs, graph, copybook_dir=copybook_dir)

    build_root = cache_dir / "_build"
    build_root.mkdir(parents=True)
    src_path = build_root / "interest_instrumented.cob"
    src_path.write_text(instrumented, encoding="utf-8")
    shutil.copy2(copybook_dir / "ACCOUNT-REC.cpy", build_root / "ACCOUNT-REC.cpy")
    proc = subprocess.run(["cobc", "-x", "interest_instrumented.cob"], cwd=build_root,
                           capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    binary = build_root / "interest_instrumented"
    fixtures = harvest(binary, build_root / "harvest_run", spec.input_data, "interest.out")
    process_record_fixtures = [f for f in fixtures if f.paragraph_id == "PROCESS-RECORD"]

    process_record = next(p for p in paragraphs if p.identifier == "PROCESS-RECORD")
    key = cache_key(source, process_record.source)
    cache = UnitCache(program_id="interest", cache_key=key, fixtures=process_record_fixtures)
    save(cache, cache_path(cache_dir, spec.cobol_source.stem, "PROCESS-RECORD"))


@requires_cobc
def test_orchestrator_uses_the_unit_cache_fast_path_and_matches_the_uncached_outcome(tmp_path):
    reference_body = REPO_REFERENCE_BODY.read_text(encoding="utf-8")
    base_spec = RunSpec.default().replace(candidate_body_path=REPO_REFERENCE_BODY)

    cache_dir = tmp_path / "unit_cache"
    cache_dir.mkdir()
    _build_real_cache(base_spec, cache_dir)

    uncached_spec = base_spec
    orch_uncached = Orchestrator(spec=uncached_spec, trace_path=tmp_path / "trace_uncached.jsonl",
                                  state_path=tmp_path / "state_uncached.json")
    uncached_results = orch_uncached.run()

    cached_spec = base_spec.replace(use_unit_cache=True, unit_cache_dir=cache_dir)
    orch_cached = Orchestrator(spec=cached_spec, trace_path=tmp_path / "trace_cached.jsonl",
                                state_path=tmp_path / "state_cached.json")
    cached_results = orch_cached.run()

    uncached_result = uncached_results["PROCESS-RECORD"]
    cached_result = cached_results["PROCESS-RECORD"]

    assert uncached_result.status == cached_result.status == "committed"
    assert uncached_result.last_report.divergence_count == cached_result.last_report.divergence_count == 0

    cached_trace = (tmp_path / "trace_cached.jsonl").read_text(encoding="utf-8")
    assert "unit cache hit" in cached_trace
    assert "unit cache miss" not in cached_trace
