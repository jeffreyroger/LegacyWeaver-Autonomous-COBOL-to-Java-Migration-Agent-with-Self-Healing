"""Leaf-first cross-program migration -- migration-framework-spec.md
Section 5, FR-13.3.

Drives one weaver.agent.orchestrator.Orchestrator run per program, in
ProgramDAG leaf-first order (weaver/cobol/program_dag.py, Task 7). A leaf
program (out-degree 0 in the DAG) is migrated and verified exactly as any
single-program run today. Once a program's per-program run commits and it
has a valid GRAPH_PLAN.md M6 UnitCache directory, that cache directory is
threaded into its parents' RunSpec.unit_cache_dir as a stub source --
GRAPH_PLAN.md's existing UnitCache/verify_unit_from_cache mechanism, reused
at the cross-program call boundary rather than the intra-program paragraph
boundary it was originally built for.

Scope note, disclosed rather than hidden (CLAUDE.md's "flag rather than
silently invent"): running a REAL per-program Orchestrator against
fixtures/cobol/multiprog/{leaf_a,leaf_b,root}.cob end to end requires those
three programs to have a registered ScaffoldSpec/reference body in
weaver/agent/program_profiles.py (CLAUDE.md rule 9) -- they do not yet
(their LINKAGE-SECTION subprogram shape is new to this repo's COBOL
frontend and out of this task's scope; Task 6's own fixture task never
claimed frontend support, only compilability). LeafOrchestrator therefore
takes an injectable `orchestrator_factory` (default: the real Orchestrator
class) so DAG sequencing and stub-cache threading are independently
testable today; wiring a real end-to-end run against the multiprog fixture
is follow-up work gated on registering those programs with the frontend,
not part of FR-13.3 as scoped here.

Never replaces per-program Orchestrator or its verification -- this module
only sequences DAG order and supplies the stub lookup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent.orchestrator import Orchestrator, UnitResult
from weaver.agent.runspec import RunSpec
from weaver.cobol.program_dag import from_directory

OrchestratorFactory = Callable[[RunSpec], Orchestrator]


def _default_orchestrator_factory(spec: RunSpec) -> Orchestrator:
    return Orchestrator(spec=spec)


@dataclass
class LeafOrchestrator:
    program_dir: Path
    base_spec: RunSpec
    orchestrator_factory: OrchestratorFactory = field(default=_default_orchestrator_factory)
    # program name -> its per-program run's spec.unit_cache_dir, once that
    # program's run has committed every unit (FR-13.3 stub source).
    verified_children: dict[str, Path] = field(default_factory=dict, init=False)
    # program name -> the run's dict[str, UnitResult], for callers/tests.
    program_results: dict[str, dict[str, UnitResult]] = field(default_factory=dict, init=False)

    def run(self) -> dict[str, dict[str, UnitResult]]:
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
