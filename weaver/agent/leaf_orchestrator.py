"""Leaf-first cross-program migration -- migration-framework-spec.md
Section 5, FR-13.3; real dispatch added in Phase X6
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md).

Drives one per-program orchestrator run per program, in ProgramDAG
leaf-first order (weaver/cobol/program_dag.py, Task 7). Once a program's
run commits and it has a valid UnitCache directory, that cache directory
is threaded into its parents' `unit_cache_dir` as a stub source --
GRAPH_PLAN.md's existing UnitCache mechanism, reused at the cross-program
call boundary rather than the intra-program paragraph boundary it was
originally built for.

**Real dispatch (Phase X6).** When `orchestrator_factory` is left at its
default (`None`), each DAG node's own source file decides which real
orchestrator runs it: a `LINKAGE SECTION` subprogram with no
`FILE-CONTROL` (Phase X1's shape, e.g. `LEAF-A.cob`/`LEAF-B.cob`) runs
through `weaver.agent.subprogram_orchestrator.SubprogramOrchestrator`
(Phase X4) and, on commit, is harvested for real via Phase X5's
`harvest_subprogram_fixtures` into a real `UnitCache` -- no fake, no
injected factory. A file-based program (`FILE-CONTROL` present) still runs
through the ordinary `weaver.agent.orchestrator.Orchestrator`.

**Task 8 compatibility, preserved exactly.** Passing an explicit
`orchestrator_factory` (as `tests/test_leaf_orchestrator.py`'s Task 8
tests do) bypasses kind-based dispatch entirely -- that factory is called
uniformly for every program name, exactly as it always was, so those
tests keep passing unmodified. The scope note Task 8 originally recorded
here (registering `ROOT.cob` with the file-based frontend, Phase X7) is
still outstanding and still governs `_run_file_based`'s own use of the
real `Orchestrator` against `ROOT.cob` specifically.

Never replaces per-program Orchestrator/SubprogramOrchestrator or their
verification -- this module only sequences DAG order and supplies the
stub lookup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from weaver.agent.orchestrator import Orchestrator
from weaver.agent.runspec import RunSpec
from weaver.cobol.program_dag import from_directory

OrchestratorFactory = Callable[[RunSpec], Orchestrator]

# Task 6's own hand-verified witness values (fixtures/data/multiprog/accounts.dat) --
# SUBPROGRAM_VERIFICATION_PLAN.md's declared scope floor: a fixed,
# hand-verified witness set, never a witness-search algorithm (roadmap,
# explicitly out of scope).
DEFAULT_SUBPROGRAM_WITNESSES = [
    Decimal("100.00"), Decimal("250.50"), Decimal("0.00"),
    Decimal("9999.99"), Decimal("1.01"), Decimal("12345.67"),
]


def _default_orchestrator_factory(spec: RunSpec) -> Orchestrator:
    return Orchestrator(spec=spec)


def _program_kind(cobol_source: Path) -> str:
    """"file_based" (has FILE-CONTROL, the Orchestrator/frontend.py shape)
    or "subprogram" (a LINKAGE SECTION with no FILE-CONTROL, Phase X1's
    shape). Raises rather than guessing on anything else."""
    upper = cobol_source.read_text(encoding="utf-8").upper()
    if "FILE-CONTROL" in upper:
        return "file_based"
    if "LINKAGE SECTION" in upper:
        return "subprogram"
    raise ValueError(f"{cobol_source}: cannot determine program kind (no FILE-CONTROL, no LINKAGE SECTION)")


@dataclass
class LeafOrchestrator:
    program_dir: Path
    base_spec: RunSpec
    # None (the default) -> real kind-based dispatch (Phase X6). An
    # explicit factory bypasses kind-based dispatch entirely and is used
    # for every program, preserving Task 8's original tests unmodified.
    orchestrator_factory: OrchestratorFactory | None = None
    work_root: Path = field(default_factory=lambda: Path("generated/leaf_orchestrator"))
    # program name -> its per-program run's UnitCache directory, once that
    # program's run has committed every unit (FR-13.3 stub source).
    verified_children: dict[str, Path] = field(default_factory=dict, init=False)
    # program name -> the run's dict[str, UnitResult]-shaped result, for callers/tests.
    program_results: dict[str, dict] = field(default_factory=dict, init=False)

    def run(self) -> dict[str, dict]:
        dag = from_directory(self.program_dir)
        for layer in dag.topological_order():
            for program_name in layer:
                self._run_one(program_name, dag)
        return self.program_results

    def _run_one(self, program_name: str, dag) -> None:
        cobol_file = self._resolve_source_file(program_name)
        # Stub availability: this program's own CALLees (per the DAG) that
        # have already committed become available via unit_cache_dir --
        # only meaningful when the program actually calls an already-
        # verified child; a leaf with no callees gets the base spec
        # unmodified.
        callee_names = {e.callee for e in dag.edges if e.caller == program_name}
        stub_dir = self._select_stub_dir(callee_names)

        if self.orchestrator_factory is not None:
            self._run_with_injected_factory(program_name, cobol_file, stub_dir)
            return

        kind = _program_kind(cobol_file)
        if kind == "subprogram":
            self._run_subprogram(program_name, cobol_file)
        else:
            self._run_file_based(program_name, cobol_file, stub_dir)

    def _run_with_injected_factory(self, program_name: str, cobol_file: Path, stub_dir: Path | None) -> None:
        program_spec = self.base_spec.replace(
            cobol_source=cobol_file,
            **({"unit_cache_dir": stub_dir, "use_unit_cache": True} if stub_dir is not None else {}),
        )
        orchestrator = self.orchestrator_factory(program_spec)
        results = orchestrator.run()
        self.program_results[program_name] = results
        if results and all(r.status == "committed" for r in results.values()):
            cache_dir = getattr(orchestrator.spec, "unit_cache_dir", None)
            if cache_dir is not None:
                self.verified_children[program_name] = cache_dir

    def _run_file_based(self, program_name: str, cobol_file: Path, stub_dir: Path | None) -> None:
        program_spec = self.base_spec.replace(
            cobol_source=cobol_file,
            **({"unit_cache_dir": stub_dir, "use_unit_cache": True} if stub_dir is not None else {}),
        )
        orchestrator = _default_orchestrator_factory(program_spec)
        results = orchestrator.run()
        self.program_results[program_name] = results
        if results and all(r.status == "committed" for r in results.values()):
            cache_dir = getattr(orchestrator.spec, "unit_cache_dir", None)
            if cache_dir is not None:
                self.verified_children[program_name] = cache_dir

    def _run_subprogram(self, program_name: str, cobol_file: Path) -> None:
        from weaver.agent import unit_cache
        from weaver.agent.subprogram_orchestrator import SubprogramOrchestrator
        from weaver.agent.subprogram_verify import harvest_subprogram_fixtures
        from weaver.cobol.subprogram import load_subprogram

        program_work_dir = self.work_root / program_name
        orch = SubprogramOrchestrator(
            cobol_source=cobol_file,
            witnesses=DEFAULT_SUBPROGRAM_WITNESSES,
            spec=self.base_spec,
            trace_path=program_work_dir / "trace.jsonl",
            work_dir=program_work_dir / "verify",
        )
        result = orch.run()
        self.program_results[program_name] = {result.program_id: result}

        if result.status != "committed":
            return
        model = load_subprogram(cobol_file)
        program_source = model.source_path.read_text(encoding="utf-8")
        fixtures = harvest_subprogram_fixtures(
            model, DEFAULT_SUBPROGRAM_WITNESSES, program_work_dir / "harvest"
        )
        cache_dir = self.work_root / "unit_cache"
        key = unit_cache.cache_key(program_source, model.paragraph_source)
        cache = unit_cache.UnitCache(program_id=model.program_id, cache_key=key, fixtures=fixtures)
        path = unit_cache.cache_path(cache_dir, cobol_file.stem, model.paragraph_id)
        unit_cache.save(cache, path)
        self.verified_children[program_name] = cache_dir

    def _select_stub_dir(self, callee_names: set[str]) -> Path | None:
        # All of a program's already-verified callees must share one
        # unit_cache_dir for this single-flag RunSpec threading to make
        # sense; if none of them have committed yet (or the program has no
        # callees), there is nothing to stub.
        dirs = {self.verified_children[c] for c in callee_names if c in self.verified_children}
        if not dirs:
            return None
        return next(iter(dirs))

    def _resolve_source_file(self, program_name: str) -> Path:
        for cob_file in sorted(self.program_dir.glob("*.cob")):
            text = cob_file.read_text(encoding="utf-8")
            if f"PROGRAM-ID. {program_name}" in text.upper() or f"PROGRAM-ID.{program_name}" in text.upper():
                return cob_file
        raise FileNotFoundError(f"no source file for program {program_name}")
