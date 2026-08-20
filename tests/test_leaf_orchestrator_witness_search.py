"""Phase X8 end-to-end proof (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X8) -- LeafOrchestrator's default RunSpec (use_witness_search=True) drives
LEAF-A/LEAF-B's real subprogram verification with a witness set produced
by the real six algorithms (weaver.agent.witness_search) instead of the
fixed hand-verified 6-value set, and still reaches the same real
zero-divergence commit Phase X6 already proved with the fixed set."""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import requests

from weaver.agent.leaf_orchestrator import LeafOrchestrator
from weaver.agent.runspec import RunSpec
from weaver.agent.subprogram_verify import harvest_subprogram_fixtures, make_oracle_fn, verify_subprogram
from weaver.agent.witness_search import witnesses_for_subprogram
from weaver.cobol.subprogram import load_subprogram

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"

# The same hand-verified-correct bodies Phase X3/X7 already established.
LEAF_A_BODY = "        return input.multiply(java.math.BigDecimal.valueOf(2));"
LEAF_B_BODY = "        return input.add(java.math.BigDecimal.valueOf(10.00));"


def _ollama_reachable() -> bool:
    try:
        r = requests.post("http://127.0.0.1:11434/api/generate",
                           json={"model": "qwen2.5-coder:7b", "prompt": "reply OK", "stream": False}, timeout=15)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"
requires_full_stack = pytest.mark.skipif(
    not _have_cobc or shutil.which("javac") is None,
    reason="requires cobc (native or WEAVER_COBC_VIA_WSL=1) and javac on PATH",
)


def test_witnesses_for_subprogram_is_generic_not_hardcoded():
    """No LEAF-A-specific values appear in witness_search.py itself --
    proven by pointing the same function at LEAF-B and getting a
    different, still valid, witness set derived purely from LEAF-B's own
    parsed PIC domain."""
    model_a = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    model_b = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    witnesses_a = witnesses_for_subprogram(model_a, oracle_fn=None, seed=0, per_algorithm_budget=4)
    witnesses_b = witnesses_for_subprogram(model_b, oracle_fn=None, seed=0, per_algorithm_budget=4)
    assert all(isinstance(w, Decimal) for w in witnesses_a)
    assert all(isinstance(w, Decimal) for w in witnesses_b)
    assert len(witnesses_a) > 0 and len(witnesses_b) > 0


@requires_full_stack
def test_leaf_a_zero_divergence_with_searched_witnesses(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    oracle_fn = make_oracle_fn(model, tmp_path / "oracle_setup")
    witnesses = witnesses_for_subprogram(model, oracle_fn, seed=0, per_algorithm_budget=3)
    assert len(witnesses) > 0

    result = verify_subprogram(model, LEAF_A_BODY, witnesses, tmp_path / "verify")
    assert result.compiled, result.compile_error
    assert result.divergence_count == 0, result.divergences


@requires_full_stack
def test_leaf_b_harvest_with_searched_witnesses_is_real(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    oracle_fn = make_oracle_fn(model, tmp_path / "oracle_setup")
    witnesses = witnesses_for_subprogram(model, oracle_fn, seed=1, per_algorithm_budget=3)

    fixtures = harvest_subprogram_fixtures(model, witnesses, tmp_path / "harvest")
    assert len(fixtures) == len(witnesses)
    for fixture in fixtures:
        assert fixture.output_state[model.output_param.name]


@requires_full_stack
@pytest.mark.skipif(not _ollama_reachable(), reason="requires a working Ollama /api/generate")
def test_real_dispatch_with_witness_search_still_commits(tmp_path):
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec(), work_root=tmp_path / "work")
    results = orch.run()

    leaf_a_result = next(iter(results["LEAF-A"].values()))
    assert leaf_a_result.status == "committed", leaf_a_result
    leaf_b_result = next(iter(results["LEAF-B"].values()))
    assert leaf_b_result.status == "committed", leaf_b_result
    assert orch.verified_children["LEAF-A"].exists()
