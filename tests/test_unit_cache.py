"""UnitCache storage — GRAPH_PLAN.md M6 (storage half) + M8's `load_valid`.

Covers persistence, cache-key invalidation, and the "load only if the key
still matches, else None" helper that `Orchestrator` (M8) uses to decide
between the fast path (`verify_unit_from_cache`, weaver/agent/
replay_verify.py, proven equivalent to the whole-program path by M7's
live tests) and its required fallback on any miss (GRAPH_PLAN.md AC-17).
"""

from __future__ import annotations

from pathlib import Path

from weaver.agent.trace_harvest import UnitFixture
from weaver.agent.unit_cache import UnitCache, cache_key, cache_path, load, load_valid, save


def test_cache_key_is_stable_for_identical_source_pairs():
    assert cache_key("PROGRAM SOURCE", "PARAGRAPH SOURCE") == cache_key("PROGRAM SOURCE", "PARAGRAPH SOURCE")


def test_cache_key_changes_when_program_source_changes():
    assert cache_key("A", "P") != cache_key("B", "P")


def test_cache_key_changes_when_paragraph_source_changes():
    assert cache_key("A", "P1") != cache_key("A", "P2")


def test_save_then_load_round_trips(tmp_path):
    fixtures = [
        UnitFixture("PROCESS-RECORD", 0, {"AR-ID": "ACC001"}, {"RL-ID": "ACC001"}),
        UnitFixture("PROCESS-RECORD", 1, {"AR-ID": "ACC002"}, {"RL-ID": "ACC002"}),
    ]
    key = cache_key("SRC", "PARA")
    cache = UnitCache(program_id="INTEREST", cache_key=key, fixtures=fixtures)

    path = tmp_path / "PROCESS-RECORD.json"
    save(cache, path)
    reloaded = load(path)

    assert reloaded == cache


def test_load_of_a_missing_file_returns_none(tmp_path):
    assert load(tmp_path / "nonexistent.json") is None


def test_load_rejects_a_stale_cache_key(tmp_path):
    """A cache whose stored key no longer matches the current source pair
    must not be silently trusted -- the caller re-harvests instead
    (GRAPH_PLAN.md AC-17: fall back on mismatch, never silently)."""
    fixtures = [UnitFixture("P", 0, {"A": "1"}, {"B": "2"})]
    cache = UnitCache(program_id="X", cache_key=cache_key("OLD-SRC", "OLD-PARA"), fixtures=fixtures)
    path = tmp_path / "P.json"
    save(cache, path)

    reloaded = load(path)
    current_key = cache_key("NEW-SRC", "NEW-PARA")

    assert reloaded is not None
    assert reloaded.cache_key != current_key


def test_default_cache_dir_layout(tmp_path):
    from weaver.agent.unit_cache import cache_path

    path = cache_path(tmp_path, "interest", "PROCESS-RECORD")
    assert path == tmp_path / "interest" / "PROCESS-RECORD.json"


def test_load_valid_returns_none_when_no_cache_file_exists(tmp_path):
    assert load_valid(tmp_path, "interest", "PROCESS-RECORD", "SRC", "PARA") is None


def test_load_valid_returns_none_when_the_key_no_longer_matches(tmp_path):
    """AC-17: a stale cache (source changed since it was harvested) must
    never be silently trusted -- the caller falls back to a real verify."""
    fixtures = [UnitFixture("PROCESS-RECORD", 0, {"A": "1"}, {"B": "2"})]
    cache = UnitCache(program_id="interest", cache_key=cache_key("OLD-SRC", "OLD-PARA"), fixtures=fixtures)
    save(cache, cache_path(tmp_path, "interest", "PROCESS-RECORD"))

    assert load_valid(tmp_path, "interest", "PROCESS-RECORD", "NEW-SRC", "NEW-PARA") is None


def test_load_valid_returns_the_cache_when_the_key_matches(tmp_path):
    fixtures = [UnitFixture("PROCESS-RECORD", 0, {"A": "1"}, {"B": "2"})]
    key = cache_key("SRC", "PARA")
    cache = UnitCache(program_id="interest", cache_key=key, fixtures=fixtures)
    save(cache, cache_path(tmp_path, "interest", "PROCESS-RECORD"))

    result = load_valid(tmp_path, "interest", "PROCESS-RECORD", "SRC", "PARA")

    assert result == cache
