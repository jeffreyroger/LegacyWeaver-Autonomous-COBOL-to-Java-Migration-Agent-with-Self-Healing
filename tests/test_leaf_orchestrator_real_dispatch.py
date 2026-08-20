"""Phase X6 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X6) -- real (non-fake) dispatch. LeafOrchestrator's default constructor
(no injected orchestrator_factory) sends a LINKAGE SECTION subprogram
through the real SubprogramOrchestrator and a file-based program through
the real Orchestrator, purely by inspecting each DAG node's own source
file.

ROOT.cob still has no registered ScaffoldSpec in program_profiles.py
(Phase X7, not this phase's scope, tracked separately in
SUBPROGRAM_VERIFICATION_PLAN.md) -- its real Orchestrator run is expected
to fail for that reason, which is itself proof the dispatch reached the
real Orchestrator rather than silently no-op'ing.
"""

import os
import shutil
from pathlib import Path

import pytest
import requests

from weaver.agent.leaf_orchestrator import LeafOrchestrator, _program_kind
from weaver.agent.runspec import RunSpec

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"


def _ollama_reachable() -> bool:
    try:
        r = requests.post("http://127.0.0.1:11434/api/generate",
                           json={"model": "qwen2.5-coder:7b", "prompt": "reply OK", "stream": False}, timeout=15)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"


def test_program_kind_detects_subprogram_vs_file_based():
    assert _program_kind(FIXTURE_DIR / "leaf_a.cob") == "subprogram"
    assert _program_kind(FIXTURE_DIR / "leaf_b.cob") == "subprogram"
    assert _program_kind(FIXTURE_DIR / "root.cob") == "file_based"


def test_default_constructor_has_no_injected_factory():
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec())
    assert orch.orchestrator_factory is None


@pytest.mark.skipif(not _have_cobc, reason="requires cobc on PATH or WEAVER_COBC_VIA_WSL=1")
@pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")
@pytest.mark.skipif(not _ollama_reachable(), reason="requires a working Ollama /api/generate")
def test_real_dispatch_migrates_leaves_for_real_before_root(tmp_path):
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec(), work_root=tmp_path / "work")
    results = orch.run()

    assert "LEAF-A" in results and "LEAF-B" in results and "ROOT" in results
    leaf_a_result = next(iter(results["LEAF-A"].values()))
    assert leaf_a_result.status == "committed", leaf_a_result
    leaf_b_result = next(iter(results["LEAF-B"].values()))
    assert leaf_b_result.status == "committed", leaf_b_result

    # Real harvest for a real commit -- a non-fake UnitCache dir.
    assert "LEAF-A" in orch.verified_children
    assert orch.verified_children["LEAF-A"].exists()
