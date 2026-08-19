"""UnitCache storage — GRAPH_PLAN.md M6 (storage half).

Persists a harvested UnitFixture collection to
`generated/graph_cache/<program_stem>/<paragraph_id>.json`, keyed by a
hash of (program source, paragraph source) for invalidation (FR-9.3).
Follows Report.to_json()/RunSpec.to_dict()'s existing convention: an
explicit payload dict, never raw dataclasses.asdict() (UnitFixture's
dict-of-dict fields round-trip cleanly through asdict() here, but the
explicit form keeps this module consistent with the rest of the repo and
resilient to a future field that wouldn't).

`verify_unit_from_cache` -- the fast-path verifier that replays these
fixtures against a candidate body -- is not implemented in this module.
It needs a generated Java comparison harness mapping cached string field
values back into typed values via ScaffoldSpec and comparing through
weaver.comparison's byte-for-byte machinery; that is real, separate
design work (GRAPH_PLAN.md M7's equivalence gate depends on it) and is
follow-up, not bundled into storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent.trace_harvest import UnitFixture


def cache_key(program_source: str, paragraph_source: str) -> str:
    """Hash of (program source, paragraph source) -- either changing
    invalidates the cache (FR-9.3)."""
    h = hashlib.sha256()
    h.update(program_source.encode("utf-8"))
    h.update(b"\x00")
    h.update(paragraph_source.encode("utf-8"))
    return h.hexdigest()


@dataclass(frozen=True)
class UnitCache:
    program_id: str
    cache_key: str
    fixtures: list[UnitFixture] = field(default_factory=list)


def cache_path(cache_dir: Path, program_stem: str, paragraph_id: str) -> Path:
    return cache_dir / program_stem / f"{paragraph_id}.json"


def save(cache: UnitCache, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "program_id": cache.program_id,
        "cache_key": cache.cache_key,
        "fixtures": [
            {
                "paragraph_id": f.paragraph_id,
                "record_index": f.record_index,
                "input_state": f.input_state,
                "output_state": f.output_state,
            }
            for f in cache.fixtures
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_valid(cache_dir: Path, program_stem: str, paragraph_id: str,
                program_source: str, paragraph_source: str) -> UnitCache | None:
    """Load the cache for `paragraph_id` only if it exists AND its stored
    key still matches the current (program source, paragraph source)
    pair -- None on either a missing file or a stale key. This is the
    single decision point AC-17 requires: the caller (Orchestrator, M8)
    must fall back to a real verify on any miss, never trust a cache
    silently."""
    cache = load(cache_path(cache_dir, program_stem, paragraph_id))
    if cache is None:
        return None
    if cache.cache_key != cache_key(program_source, paragraph_source):
        return None
    return cache


def load(path: Path) -> UnitCache | None:
    """Returns None if the file doesn't exist. Does not itself compare
    against a current cache_key -- that's the caller's job (AC-17: fall
    back on mismatch, never silently trust a stale cache)."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixtures = [
        UnitFixture(
            paragraph_id=f["paragraph_id"],
            record_index=f["record_index"],
            input_state=f["input_state"],
            output_state=f["output_state"],
        )
        for f in payload["fixtures"]
    ]
    return UnitCache(program_id=payload["program_id"], cache_key=payload["cache_key"], fixtures=fixtures)
