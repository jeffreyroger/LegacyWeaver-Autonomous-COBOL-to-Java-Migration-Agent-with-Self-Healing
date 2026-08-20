"""Phase X5 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X5) -- real UnitCache harvest for a subprogram leaf. A UnitCache directory
exists on disk with LEAF-A's 6 witness fixtures, loadable by the existing
weaver.agent.unit_cache.load_valid, and the fast-path lookup agrees with a
live verify_subprogram re-run on all witnesses (equivalence gate, same
discipline as GRAPH_PLAN.md M7/AC-16, scaled to this smaller surface).
"""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from weaver.agent import unit_cache
from weaver.agent.subprogram_verify import (
    harvest_subprogram_fixtures, verify_subprogram, verify_subprogram_from_cache,
)
from weaver.cobol.subprogram import load_subprogram

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"
WITNESSES = [Decimal("100.00"), Decimal("250.50"), Decimal("0.00"),
             Decimal("9999.99"), Decimal("1.01"), Decimal("12345.67")]

_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"
requires_cobol_toolchain = pytest.mark.skipif(
    not _have_cobc, reason="requires cobc on PATH or WEAVER_COBC_VIA_WSL=1"
)
requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_cobol_toolchain
def test_harvest_produces_six_real_fixtures_for_leaf_a(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    fixtures = harvest_subprogram_fixtures(model, WITNESSES, tmp_path)
    assert len(fixtures) == 6
    assert {f.record_index for f in fixtures} == set(range(6))
    for fixture in fixtures:
        assert fixture.paragraph_id == "MAIN-PARA"
        assert "LA-INPUT" in fixture.input_state
        assert "LA-OUTPUT" in fixture.output_state
    # Real oracle output, hand-verified: witness 100.00 doubles to 200.00.
    zero_index_fixture = next(f for f in fixtures if f.record_index == 0)
    assert zero_index_fixture.output_state["LA-OUTPUT"] == "0020000"


@requires_cobol_toolchain
def test_harvested_cache_round_trips_through_save_and_load_valid(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    fixtures = harvest_subprogram_fixtures(model, WITNESSES, tmp_path / "harvest")

    program_source = model.source_path.read_text(encoding="utf-8")
    key = unit_cache.cache_key(program_source, model.paragraph_source)
    cache = unit_cache.UnitCache(program_id=model.program_id, cache_key=key, fixtures=fixtures)

    cache_dir = tmp_path / "cache"
    path = unit_cache.cache_path(cache_dir, "leaf_a", model.paragraph_id)
    unit_cache.save(cache, path)

    loaded = unit_cache.load_valid(cache_dir, "leaf_a", model.paragraph_id, program_source, model.paragraph_source)
    assert loaded is not None
    assert len(loaded.fixtures) == 6
    assert loaded.cache_key == key

    # A stale key (paragraph source changed) must not load -- AC-17's
    # "never silently trust a stale cache" posture.
    stale = unit_cache.load_valid(cache_dir, "leaf_a", model.paragraph_id, program_source, "CHANGED SOURCE")
    assert stale is None


@requires_cobol_toolchain
@requires_javac
def test_fast_path_agrees_with_live_verify_on_correct_body(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    fixtures = harvest_subprogram_fixtures(model, WITNESSES, tmp_path / "harvest")
    cache = unit_cache.UnitCache(program_id=model.program_id, cache_key="irrelevant-for-this-test",
                                  fixtures=fixtures)

    body = "        return input.multiply(java.math.BigDecimal.valueOf(2));"
    live = verify_subprogram(model, body, WITNESSES, tmp_path / "live")
    cached = verify_subprogram_from_cache(model, body, cache, tmp_path / "cached")

    assert live.compiled and cached.compiled
    assert live.divergence_count == cached.divergence_count == 0


@requires_cobol_toolchain
@requires_javac
def test_fast_path_agrees_with_live_verify_on_wrong_body(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    fixtures = harvest_subprogram_fixtures(model, WITNESSES, tmp_path / "harvest")
    cache = unit_cache.UnitCache(program_id=model.program_id, cache_key="irrelevant-for-this-test",
                                  fixtures=fixtures)

    wrong_body = "        return input.add(java.math.BigDecimal.valueOf(2));"
    live = verify_subprogram(model, wrong_body, WITNESSES, tmp_path / "live")
    cached = verify_subprogram_from_cache(model, wrong_body, cache, tmp_path / "cached")

    assert live.compiled and cached.compiled
    assert live.divergence_count == cached.divergence_count
    live_inputs = {d.witness_input for d in live.divergences}
    cached_inputs = {d.witness_input for d in cached.divergences}
    assert live_inputs == cached_inputs
