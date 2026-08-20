"""Phase X4 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X4) -- a real, unassisted local Ollama synthesis run commits LEAF-A and
LEAF-B without a hand-written seed body.
"""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import requests

from weaver.agent.runspec import RunSpec
from weaver.agent.subprogram_orchestrator import SubprogramOrchestrator

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"
WITNESSES = [Decimal("100.00"), Decimal("250.50"), Decimal("0.00"),
             Decimal("9999.99"), Decimal("1.01"), Decimal("12345.67")]


def _ollama_reachable() -> bool:
    try:
        requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"
requires_full_stack = pytest.mark.skipif(
    not (_have_cobc and shutil.which("javac") and _ollama_reachable()),
    reason="requires cobc (or WEAVER_COBC_VIA_WSL=1), javac, and a reachable Ollama daemon",
)


@requires_full_stack
def test_leaf_a_commits_via_real_unassisted_synthesis(tmp_path):
    orch = SubprogramOrchestrator(
        cobol_source=FIXTURE_DIR / "leaf_a.cob",
        witnesses=WITNESSES,
        spec=RunSpec.default(),
        trace_path=tmp_path / "trace.jsonl",
        work_dir=tmp_path / "work",
    )
    result = orch.run()
    assert result.status == "committed", (result.escalation_reason, result.final_body)
    assert result.verify_result.divergence_count == 0
    assert (tmp_path / "trace.jsonl").exists()


@requires_full_stack
def test_leaf_b_commits_via_real_unassisted_synthesis(tmp_path):
    orch = SubprogramOrchestrator(
        cobol_source=FIXTURE_DIR / "leaf_b.cob",
        witnesses=WITNESSES,
        spec=RunSpec.default(),
        trace_path=tmp_path / "trace.jsonl",
        work_dir=tmp_path / "work",
    )
    result = orch.run()
    assert result.status == "committed", (result.escalation_reason, result.final_body)
    assert result.verify_result.divergence_count == 0
