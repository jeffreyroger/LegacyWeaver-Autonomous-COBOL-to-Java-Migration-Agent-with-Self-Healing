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

import contextlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from weaver.agent.orchestrator import Orchestrator
from weaver.agent.result_view import composite_id, normalize_program_results
from weaver.agent.runspec import RunSpec
from weaver.atomic_json import write_json_atomic
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
    # Backend attachment points, added 2026-08-26 for multi-program runs
    # (docs/specs/BACKEND_PLAN.md has no multi-program section yet -- this
    # mirrors weaver.agent.orchestrator.Orchestrator's own on_event/
    # cancel_requested/results_lock signature exactly, so the two read
    # alike). All optional and None by default: an existing caller that
    # never sets them (every current test, weaver/cli.py before this
    # change) gets byte-identical behavior.
    #
    # run_dir, when set, is where this run's OWN combined trace/state live
    # (run_dir/trace.jsonl, run_dir/orchestrator_state.json) and where each
    # DAG node's nested orchestrator gets its own
    # run_dir/programs/<NAME>/{trace.jsonl,orchestrator_state.json} --
    # fixing a real pre-existing bug: _default_orchestrator_factory built
    # Orchestrator(spec=spec) with no explicit trace_path/state_path, so
    # every file-based node in one directory shared
    # generated/trace.jsonl/generated/orchestrator_state.json, and
    # Orchestrator's fresh_trace=True default TRUNCATES that shared file on
    # construction -- the second file-based program in a directory silently
    # wiped the first one's trace and state. When run_dir is None (every
    # caller before this change), that old shared-default behavior is
    # unchanged; this is opt-in via passing run_dir, not a default change.
    run_dir: Path | None = None
    on_event: Callable[[dict], None] | None = None
    cancel_requested: threading.Event | None = None
    results_lock: threading.Lock | None = None
    # DAG-level resume (2026-08-26): program_name -> that program's
    # ALREADY-COMMITTED {unit_id: raw_result} dict from a prior,
    # interrupted attempt at this same run_dir (backend/runs.py's
    # resume_run reconstructs this from orchestrator_state.json exactly
    # the way the single-program Orchestrator resume path already does).
    # A listed program is never re-run or re-verified (BACKEND_PLAN.md
    # §4.5, "committed units are not re-verified") -- run() just adopts
    # its result and reconstructs verified_children/call_semantics from
    # artefacts already on disk (see _skip_committed_program). None (the
    # default) means "fresh run, nothing to skip" -- every caller before
    # this field existed is unaffected.
    resume_committed: dict[str, dict[str, object]] | None = None
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
                # Checked at a PROGRAM boundary -- never mid-program, which
                # would leave a nested orchestrator's containers running
                # and its state inconsistent. The same threading.Event is
                # also handed straight to each nested Orchestrator (see
                # _run_file_based), which additionally checks it at its own
                # UNIT boundary -- both granularities, one mechanism.
                if self.cancel_requested is not None and self.cancel_requested.is_set():
                    return self.program_results
                if self.resume_committed and program_name in self.resume_committed:
                    self._skip_committed_program(program_name)
                else:
                    self._run_one(program_name, dag)
                # Checkpoint after this program's run is fully terminal,
                # never before (BACKEND_PLAN.md §4.5's "checkpoint after
                # commit, not before", applied at program granularity).
                self._persist_state()
        return self.program_results

    def _skip_committed_program(self, program_name: str) -> None:
        """DAG-level resume: adopt a program's already-committed result
        from a prior interrupted attempt, without re-running or
        re-verifying it (BACKEND_PLAN.md §4.5). `verified_children`/
        `call_semantics` -- the two pieces of state a LATER, still-to-run
        program in this same DAG might depend on -- are reconstructed from
        real artefacts already persisted to disk by the interrupted
        attempt (the shared subprogram UnitCache directory), never
        fabricated: if that cache is missing or stale, this program's
        downstream callers simply get no stub/CALL-semantics context, the
        same honest degrade a fresh run gets on any other cache miss."""
        with self._results_guard():
            self.program_results[program_name] = self.resume_committed[program_name]

        cobol_file = self.resolve_source_file(program_name)
        if _program_kind(cobol_file) != "subprogram":
            return
        cache_dir = self.work_root / "unit_cache"
        from weaver.agent import unit_cache
        from weaver.cobol.subprogram import load_subprogram

        model = load_subprogram(cobol_file)
        program_source = model.source_path.read_text(encoding="utf-8")
        cache = unit_cache.load_valid(cache_dir, cobol_file.stem, model.paragraph_id,
                                       program_source, model.paragraph_source)
        if cache is None:
            return
        self.verified_children[program_name] = cache_dir
        self.call_semantics[program_name] = self._render_call_semantics(program_name, model, cache.fixtures)

    def _persist_state(self) -> None:
        """Flat, composite-id-keyed checkpoint of every unit committed or
        escalated so far, written to run_dir/orchestrator_state.json --
        the same on-disk shape a single-program Orchestrator writes, so
        weaver/agent/metrics.py's compute_metrics reads a multi-program
        run's state file completely unmodified. A no-op when this
        LeafOrchestrator wasn't given a run_dir (every caller before
        2026-08-26, including every existing test)."""
        if self.run_dir is None:
            return
        with self._results_guard():
            flat = normalize_program_results(self.program_results)
        write_json_atomic(self.run_dir / "orchestrator_state.json", flat)

    def _results_guard(self):
        return self.results_lock if self.results_lock is not None else contextlib.nullcontext()

    def _run_one(self, program_name: str, dag) -> None:
        cobol_file = self.resolve_source_file(program_name)
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
        with self._results_guard():
            self.program_results[program_name] = results
        if results and all(r.status == "committed" for r in results.values()):
            cache_dir = getattr(orchestrator.spec, "unit_cache_dir", None)
            if cache_dir is not None:
                self.verified_children[program_name] = cache_dir

    def _program_dir(self, program_name: str) -> Path:
        """Where this program's own artefacts (trace/state, subprogram
        verify workspace) live for this run. Under run_dir when the
        backend gave us one (multi-program runs get real isolation);
        under the old work_root otherwise -- unchanged for every caller
        before 2026-08-26."""
        base = (self.run_dir / "programs") if self.run_dir is not None else self.work_root
        return base / program_name

    def _make_on_event(self, program_name: str) -> Callable[[dict], None] | None:
        """Wraps this program's nested orchestrator's on_event so every
        event it emits is stamped with `program`/`composite_id` before
        being appended to the run's OWN combined trace and forwarded to
        the backend's on_event -- the `program` field originates here, in
        the agent, never invented by the backend (BACKEND_PLAN.md §4.3:
        events forwarded verbatim). A no-op (returns None) when this
        LeafOrchestrator has no run_dir, since there is nowhere to write
        a combined trace and no caller listening anyway."""
        if self.run_dir is None:
            return None
        combined_trace_path = self.run_dir / "trace.jsonl"
        combined_trace_path.parent.mkdir(parents=True, exist_ok=True)

        def _on_event(event: dict) -> None:
            stamped = dict(event)
            stamped["program"] = program_name
            stamped["composite_id"] = composite_id(program_name, event.get("unit", ""))
            with combined_trace_path.open("a") as f:
                f.write(json.dumps(stamped) + "\n")
            if self.on_event is not None:
                self.on_event(stamped)

        return _on_event

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
        # Real dispatch's own trace/state paths (fixing the pre-existing
        # shared-generated/trace.jsonl clobbering bug -- see this
        # dataclass's run_dir field docstring): only overridden when this
        # LeafOrchestrator has a run_dir; otherwise Orchestrator's own
        # defaults apply exactly as before 2026-08-26.
        orchestrator_kwargs: dict[str, object] = {"spec": program_spec}
        # cancel_requested/results_lock propagate regardless of run_dir --
        # they need no path to write to, only the same shared objects this
        # LeafOrchestrator itself was given. trace_path/state_path/
        # on_event DO need run_dir (somewhere real to write), so those
        # stay gated on it.
        if self.cancel_requested is not None:
            orchestrator_kwargs["cancel_requested"] = self.cancel_requested
        if self.results_lock is not None:
            orchestrator_kwargs["results_lock"] = self.results_lock
        if self.run_dir is not None:
            program_dir = self._program_dir(program_name)
            orchestrator_kwargs.update(
                trace_path=program_dir / "trace.jsonl",
                state_path=program_dir / "orchestrator_state.json",
                on_event=self._make_on_event(program_name),
            )
        orchestrator = Orchestrator(**orchestrator_kwargs)
        results = orchestrator.run()
        with self._results_guard():
            self.program_results[program_name] = results
        if results and all(r.status == "committed" for r in results.values()):
            cache_dir = getattr(orchestrator.spec, "unit_cache_dir", None)
            if cache_dir is not None:
                self.verified_children[program_name] = cache_dir

    def _witnesses_for(self, model, program_work_dir: Path, mocked: bool = False) -> list[Decimal]:
        """Phase X8: real witness-search algorithms by default
        (`RunSpec.use_witness_search`), falling back to the fixed,
        hand-verified `DEFAULT_SUBPROGRAM_WITNESSES` set when disabled or
        when the model has more than one input field (multi-field
        subprograms aren't yet wired into SubprogramOrchestrator's
        single-scalar witness API -- see witness_search.witnesses_for_subprogram).

        Always falls back for a mocked (EXEC SQL/EXEC CICS) subprogram
        (Phase Z1/Z3, 2026-08-26): `make_oracle_fn` compiles the RAW source
        with `cobc`, which cannot compile an EXEC SQL/CICS block at all --
        witness search would just crash setting up its own oracle driver."""
        if mocked or not self.base_spec.use_witness_search or len(model.input_params) != 1:
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
        from weaver.cobol.mock_directives import find_mock_directives
        from weaver.cobol.subprogram import load_subprogram

        program_work_dir = self._program_dir(program_name)
        model = load_subprogram(cobol_file)
        program_source = model.source_path.read_text(encoding="utf-8")
        mocked = bool(find_mock_directives(program_source))
        witnesses = self._witnesses_for(model, program_work_dir, mocked=mocked)

        orch = SubprogramOrchestrator(
            cobol_source=cobol_file,
            witnesses=witnesses,
            spec=self.base_spec,
            trace_path=program_work_dir / "trace.jsonl",
            work_dir=program_work_dir / "verify",
            on_event=self._make_on_event(program_name),
        )
        result = orch.run()
        with self._results_guard():
            self.program_results[program_name] = {result.program_id: result}

        if result.status != "committed":
            return
        if mocked:
            # Dynamic Mocking subprograms (Phase Z1) have no real unmocked
            # `cobc` oracle to harvest fixtures from (see _witnesses_for) --
            # they commit via the Parity Gate above but don't yet propagate
            # CALL semantics upstream. Out of scope here: no file-based
            # fixture in this project calls a mocked subprogram today.
            return
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

    def resolve_source_file(self, program_name: str) -> Path:
        for cob_file in sorted(self.program_dir.glob("*.cob")):
            text = cob_file.read_text(encoding="utf-8")
            if f"PROGRAM-ID. {program_name}" in text.upper() or f"PROGRAM-ID.{program_name}" in text.upper():
                return cob_file
        raise FileNotFoundError(f"no source file for program {program_name}")
