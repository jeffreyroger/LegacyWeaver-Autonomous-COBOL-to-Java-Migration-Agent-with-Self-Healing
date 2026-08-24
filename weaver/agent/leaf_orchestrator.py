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
tests keep passing unmodified.

**Cross-program CALL semantics, added 2026-08-23.** A file-based parent's
paragraph source routinely contains an opaque `CALL "LEAF-A" USING ...` --
the synthesis prompt otherwise has no way to tell the model what that
subprogram actually does. Once a subprogram commits, `_run_subprogram`
renders a few of its just-harvested real witness input/output pairs into
`self.call_semantics[program_name]`; `_run_file_based` looks up its own
DAG callees' entries and threads them into the parent's
`RunSpec.extra_prompt_context` (`weaver/agent/prompt.py`), so the model
sees real, currently-verified oracle behavior instead of guessing from a
program name. Never fabricated -- only ever built from committed
subprograms' real `cobc` output.

**Phase X7, closed 2026-08-23 (weaver migrate --leaf-first wiring).**
`ROOT.cob` is registered in `weaver/agent/program_profiles.py`, with a
real golden output (`fixtures/data/multiprog/expected/golden_root.out`,
produced by compiling `root.cob`/`leaf_a.cob`/`leaf_b.cob` together via
one real `cobc -x` invocation and hand-verified on 3 of 6 records).
`_run_file_based` now resolves each file-based DAG node's own
golden_output/scaffold_spec/scaffold_path/reference_* via
`program_profiles.program_profile(cobol_file)` instead of reusing
`base_spec`'s blindly -- the gap this note used to describe.

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
    # program name -> real-witness "what this subprogram actually does"
    # text, built once a subprogram commits (2026-08-23, migration-
    # framework-spec.md Section 5 "Upstream Propagation") -- threaded into
    # a calling file-based program's synthesis prompt via
    # RunSpec.extra_prompt_context so the parent's paragraph, which only
    # ever sees an opaque `CALL "LEAF-A" USING ...`, can learn the
    # subprogram's real observed behavior instead of guessing from its name.
    call_semantics: dict[str, str] = field(default_factory=dict, init=False)

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
            self._run_file_based(program_name, cobol_file, stub_dir, dag)

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

    def _call_semantics_for(self, program_name: str, dag) -> str:
        callee_names = {e.callee for e in dag.edges if e.caller == program_name}
        blocks = [self.call_semantics[c] for c in sorted(callee_names) if c in self.call_semantics]
        return "\n\n".join(blocks)

    def _run_file_based(self, program_name: str, cobol_file: Path, stub_dir: Path | None, dag=None) -> None:
        # Phase X7 (previously outstanding, see module docstring): each
        # file-based DAG node gets its OWN golden_output/scaffold_spec/
        # scaffold_path/reference_* resolved via program_profiles.py,
        # exactly like a single-program `weaver migrate` run would --
        # never base_spec's blindly reused across every file-based program
        # in the directory, which would silently verify e.g. ROOT.cob
        # against whatever program base_spec happened to be built for.
        from weaver.agent.program_profiles import program_profile

        profile = program_profile(cobol_file)
        profile_kwargs: dict[str, object] = {}
        if profile is not None:
            profile_kwargs = {
                "golden_output": profile.golden_output or self.base_spec.golden_output,
                "scaffold_spec": profile.scaffold_spec or self.base_spec.scaffold_spec,
                "scaffold_path": profile.scaffold_path or self.base_spec.scaffold_path,
                "reference_body_path": profile.reference_body_path or self.base_spec.reference_body_path,
                "reference_paragraph_id": profile.reference_paragraph_id or self.base_spec.reference_paragraph_id,
                "input_data": profile.input_data or self.base_spec.input_data,
            }
        call_semantics = self._call_semantics_for(program_name, dag) if dag is not None else ""
        if call_semantics:
            profile_kwargs["extra_prompt_context"] = call_semantics
        program_spec = self.base_spec.replace(
            cobol_source=cobol_file,
            **profile_kwargs,
            **({"unit_cache_dir": stub_dir, "use_unit_cache": True} if stub_dir is not None else {}),
        )
        orchestrator = _default_orchestrator_factory(program_spec)
        results = orchestrator.run()
        self.program_results[program_name] = results
        if results and all(r.status == "committed" for r in results.values()):
            cache_dir = getattr(orchestrator.spec, "unit_cache_dir", None)
            if cache_dir is not None:
                self.verified_children[program_name] = cache_dir

    def _witnesses_for(self, model, program_work_dir: Path) -> list[Decimal]:
        """Phase X8: real witness-search algorithms by default
        (`RunSpec.use_witness_search`), falling back to the fixed,
        hand-verified `DEFAULT_SUBPROGRAM_WITNESSES` set when disabled or
        when the model has more than one input field (multi-field
        subprograms aren't yet wired into SubprogramOrchestrator's
        single-scalar witness API -- see witness_search.witnesses_for_subprogram)."""
        if not self.base_spec.use_witness_search or len(model.input_params) != 1:
            return DEFAULT_SUBPROGRAM_WITNESSES
        from weaver.agent.subprogram_verify import make_oracle_fn
        from weaver.agent.witness_search import witnesses_for_subprogram

        oracle_fn = make_oracle_fn(model, program_work_dir / "witness_search_oracle")
        # Small per-algorithm budget: each witness costs one real cobc +
        # one real javac/java round trip inside the repair loop, so the
        # union of six algorithms must stay a modest multiple of the old
        # fixed 6-value set, not an unbounded search.
        witnesses = witnesses_for_subprogram(model, oracle_fn, seed=self.base_spec.seed, per_algorithm_budget=3)
        return witnesses or DEFAULT_SUBPROGRAM_WITNESSES

    def _run_subprogram(self, program_name: str, cobol_file: Path) -> None:
        from weaver.agent import unit_cache
        from weaver.agent.subprogram_orchestrator import SubprogramOrchestrator
        from weaver.agent.subprogram_verify import harvest_subprogram_fixtures
        from weaver.cobol.subprogram import load_subprogram

        program_work_dir = self.work_root / program_name
        model = load_subprogram(cobol_file)
        witnesses = self._witnesses_for(model, program_work_dir)

        orch = SubprogramOrchestrator(
            cobol_source=cobol_file,
            witnesses=witnesses,
            spec=self.base_spec,
            trace_path=program_work_dir / "trace.jsonl",
            work_dir=program_work_dir / "verify",
        )
        result = orch.run()
        self.program_results[program_name] = {result.program_id: result}

        if result.status != "committed":
            return
        program_source = model.source_path.read_text(encoding="utf-8")
        fixtures = harvest_subprogram_fixtures(
            model, witnesses, program_work_dir / "harvest"
        )
        cache_dir = self.work_root / "unit_cache"
        key = unit_cache.cache_key(program_source, model.paragraph_source)
        cache = unit_cache.UnitCache(program_id=model.program_id, cache_key=key, fixtures=fixtures)
        path = unit_cache.cache_path(cache_dir, cobol_file.stem, model.paragraph_id)
        unit_cache.save(cache, path)
        self.verified_children[program_name] = cache_dir
        self.call_semantics[program_name] = self._render_call_semantics(program_name, model, fixtures)

    @staticmethod
    def _render_call_semantics(program_name: str, model, fixtures) -> str:
        """Real witness input/output pairs from the just-harvested UnitCache
        (never fabricated -- every value came from a real, currently-
        compiled cobc run), rendered as worked examples a calling program's
        synthesis prompt can read.

        Found 2026-08-23: showing raw (input, output) pairs alone and
        asking the model to translate the CALL directly was not enough --
        granite-code:20b ignored the examples and fell back to a memorized
        COBOL idiom (`ar.isDormant()`, which doesn't exist in this
        program's context at all) instead of reasoning about the numbers.
        A step-by-step probe (compute the ratio/difference yourself, THEN
        write the assignment) reliably worked instead. So: fit the
        smallest-magnitude witnesses (least likely to have hit an overflow
        truncation boundary) against the two shapes this project's fixture
        set actually needs -- constant multiplier, constant additive
        offset -- and state the fitted relationship as an already-verified
        fact when one fits exactly. This is a disclosed narrow subshape,
        not general function inference: a subprogram whose real behavior
        is neither of these two shapes gets only the raw examples below,
        same as before.
        """
        from weaver.agent.subprogram_verify import _from_raw

        in_scale = model.input_param.decimal_scale
        out_scale = model.output_param.decimal_scale
        decoded = []
        for fx in fixtures:
            in_raw = fx.input_state[model.input_param.name]
            out_raw = fx.output_state[model.output_param.name]
            decoded.append((_from_raw(in_raw, in_scale), _from_raw(out_raw, out_scale)))
        decoded.sort(key=lambda pair: abs(pair[0]))
        sample = decoded[:5]

        lines = [f"    input={i} -> output={o}" for i, o in sample]
        examples = "\n".join(lines)

        formula_note = ""
        nonzero = [(i, o) for i, o in sample if i != 0]
        ratios = {o / i for i, o in nonzero}
        diffs = {o - i for i, o in sample}
        if nonzero and len(ratios) == 1:
            k = ratios.pop()
            formula_note = (
                f"\n\nFitted relationship, verified exactly on every example above: "
                f"output = input * {k}. This IS this subprogram's real behavior on these "
                f"witnesses -- use it directly, do not re-derive it differently. If your "
                f"own paragraph's output field is narrower than this subprogram's, the real "
                f"oracle may truncate high-order digits on overflow (see this prompt's "
                f"overflow-truncation rule, if present, for how to replicate that)."
            )
        elif len(diffs) == 1:
            k = diffs.pop()
            formula_note = (
                f"\n\nFitted relationship, verified exactly on every example above: "
                f"output = input + {k}. This IS this subprogram's real behavior on these "
                f"witnesses -- use it directly, do not re-derive it differently."
            )

        return (
            f'CALL "{program_name}" behavior (observed from the real, currently-compiled '
            f"COBOL oracle -- not a guess; treat as ground truth):\n{examples}{formula_note}"
        )

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
