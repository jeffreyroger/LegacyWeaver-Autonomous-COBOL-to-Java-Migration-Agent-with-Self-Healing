from pathlib import Path

from weaver.agent.leaf_orchestrator import LeafOrchestrator
from weaver.agent.orchestrator import UnitResult
from weaver.agent.runspec import RunSpec

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"


class _FakeOrchestrator:
    """Stands in for weaver.agent.orchestrator.Orchestrator so DAG
    sequencing and stub-cache threading are testable without a registered
    ScaffoldSpec/reference body for the multiprog fixture's LINKAGE-SECTION
    subprograms (see leaf_orchestrator.py's module docstring scope note)."""

    def __init__(self, spec: RunSpec, *, order_log: list[str], cache_dirs: dict[str, Path]):
        self.spec = spec
        self._order_log = order_log
        self._cache_dirs = cache_dirs

    def run(self) -> dict[str, UnitResult]:
        program_name = self.spec.cobol_source.stem.upper().replace("_", "-")
        self._order_log.append(program_name)
        cache_dir = self._cache_dirs.get(program_name)
        if cache_dir is not None:
            self.spec = self.spec.replace(unit_cache_dir=cache_dir)
        return {
            "MAIN-PARA": UnitResult(
                unit_id="MAIN-PARA", status="committed", final_body="// ok",
                model_calls=0, memory_hit=False, duration_seconds=0.01,
            )
        }


def _make_factory(order_log: list[str], cache_dirs: dict[str, Path], specs_seen: list[RunSpec]):
    def factory(spec: RunSpec):
        specs_seen.append(spec)
        return _FakeOrchestrator(spec, order_log=order_log, cache_dirs=cache_dirs)
    return factory


def test_migrates_leaves_before_root():
    order_log: list[str] = []
    factory = _make_factory(order_log, cache_dirs={}, specs_seen=[])
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec(), orchestrator_factory=factory)
    orch.run()
    assert order_log.index("LEAF-A") < order_log.index("ROOT")
    assert order_log.index("LEAF-B") < order_log.index("ROOT")


def test_all_three_programs_run_and_commit():
    order_log: list[str] = []
    factory = _make_factory(order_log, cache_dirs={}, specs_seen=[])
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec(), orchestrator_factory=factory)
    results = orch.run()
    assert set(results.keys()) == {"LEAF-A", "LEAF-B", "ROOT"}
    for program_results in results.values():
        assert all(r.status == "committed" for r in program_results.values())


def test_root_receives_a_verified_childs_unit_cache_dir(tmp_path):
    leaf_a_cache = tmp_path / "leaf_a_cache"
    order_log: list[str] = []
    specs_seen: list[RunSpec] = []
    factory = _make_factory(order_log, cache_dirs={"LEAF-A": leaf_a_cache}, specs_seen=specs_seen)
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec(), orchestrator_factory=factory)
    orch.run()

    assert orch.verified_children["LEAF-A"] == leaf_a_cache

    root_spec = next(s for s in specs_seen if s.cobol_source.stem.upper().replace("_", "-") == "ROOT")
    assert root_spec.unit_cache_dir == leaf_a_cache
    assert root_spec.use_unit_cache is True


def test_leaf_with_no_committed_children_gets_unmodified_spec():
    order_log: list[str] = []
    specs_seen: list[RunSpec] = []
    factory = _make_factory(order_log, cache_dirs={}, specs_seen=specs_seen)
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec(), orchestrator_factory=factory)
    orch.run()

    leaf_a_spec = next(s for s in specs_seen if s.cobol_source.stem.upper().replace("_", "-") == "LEAF-A")
    assert leaf_a_spec.unit_cache_dir is None
    assert leaf_a_spec.use_unit_cache is False
