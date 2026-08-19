# LegacyWeaver — Subprogram Verification & Real Leaf-First Migration (Phase X)

**Companion to `migration-framework-spec.md`, `GRAPH_PLAN.md`, and
`docs/superpowers/plans/2026-08-19-migration-framework-upgrade.md` (Phase W,
merged 2026-08-19). Phase W built `LeafOrchestrator`'s DAG sequencing and
stub-cache threading, tested against a fake orchestrator — `LEAF-A.cob`/
`LEAF-B.cob` (pure `LINKAGE SECTION` subprograms) have no registered
`ScaffoldSpec` and cannot run through the real per-program `Orchestrator`.
This plan closes that gap, phase by phase, each phase independently mergeable
and independently valuable.**

---

## 0. Why this needs its own plan (findings from 2026-08-19/20 investigation)

Three separate blockers were found, not one:

1. **No subprogram frontend.** `weaver/cobol/frontend.py`'s `load_program()`
   is scoped, by design (Phase U), to exactly one input file + one output
   file + one accumulator. `LEAF-A.cob`/`LEAF-B.cob` have no `FILE-CONTROL`
   at all — a fundamentally different program shape.
2. **No non-file verification axis.** The entire harness
   (`weaver.execution`/`weaver.comparison`) diffs two *files*. A subprogram
   produces no file; verifying it needs a parametrized call-in/call-out
   comparison, which does not exist anywhere in this repo.
3. **`LeafOrchestrator`'s DAG resolves programs by literal name.** A
   file-based "harness" workaround around `LEAF-A.cob` does not help —
   `ROOT.cob` literally `CALL`s `"LEAF-A"`, so the DAG's real target is
   `LEAF-A.cob` itself, not a proxy.

None of these are wrong to need — they are exactly what real leaf-first,
cross-program migration requires (`migration-framework-spec.md` §5.2's
"Witness Input Search & Output Caching" step is, in fact, the parity axis
this plan builds a first, minimal version of). They are just bigger than a
follow-up patch, so this plan breaks them into independently-shippable
phases instead of one sitting.

---

## 1. Scope Contract

### IN (across all phases X1–X7)
- Parsing a narrowly-scoped `LINKAGE SECTION` subprogram shape: one
  `PROGRAM-ID`, a `LINKAGE SECTION` with exactly two numeric elementary
  items (one input, one output, matching `PROCEDURE DIVISION USING` order),
  and exactly one paragraph.
- A new, real, byte-for-byte parity verification axis over a fixed witness
  set of inputs (no witness-search algorithms — those stay explicitly out
  of scope, per the Phase W plan's own deferral).
- Real synthesis (local Ollama) and a lightweight repair path for a
  subprogram unit.
- Real `UnitCache` harvesting for a subprogram leaf, consumed as a real stub
  by `LeafOrchestrator` when migrating `ROOT.cob`.
- A real, portable execution path — CI's native Linux runners already have
  `cobc`; this plan does not require a new execution mechanism for CI. Local
  Windows dev-machine execution (this environment has no native `cobc`) is
  handled by an explicit, disclosed WSL delegation shim, gated the same way
  the existing Groq CI exception is (CLAUDE.md rule 10 pattern) — never a
  silent behavior change to the default execution path.

### OUT (every phase — say "roadmap", do not build)
- The six witness-search algorithms (`migration-framework-spec.md` §5.2) —
  a fixed, hand-verified witness set (reusing Task 6's own 6 accounts.dat
  values) is the floor for this plan.
- `EXEC SQL`/`EXEC CICS` mocking, PostgreSQL/RabbitMQ connectors — no
  fixture uses them.
- Cross-program class/entity dedup — single-parameter subprograms have
  nothing to dedup yet.
- Changing any of the 8 existing fixtures' frontend contract, golden
  checksums, or the 132-divergence number. `load_program()`'s existing
  file-based contract is not touched by this plan at all — subprogram
  parsing is a new, parallel module, never a modification to it.

### The line to say out loud
> "A subprogram's contract is its parameters, not a file. Verification
> follows the contract it actually has."

---

## 2. Non-Negotiable Design Decisions

1. **`weaver/cobol/frontend.py` is untouched.** Every phase below adds a new,
   parallel module (`weaver/cobol/subprogram.py`) rather than extending
   `load_program()`'s existing, hardened, 8-fixture-tested contract. Two
   small parsers, cleanly separated by program shape, is safer than one
   parser with a growing set of special cases.
2. **The comparison contract stays singular (CLAUDE.md rule 3).** The new
   parity axis reuses `weaver.comparison`'s existing byte-for-byte /
   `Decimal` machinery on each witness's output value — it does not invent
   a second equivalence rule.
3. **No witness is fabricated.** Every witness input's expected output comes
   from actually compiling and running the real `cobc`-compiled subprogram
   (or, for CI, the real GnuCOBOL 3.x oracle) — never hand-typed, mirroring
   CLAUDE.md rule 6's discipline for the whole-program fixtures.
4. **A cache miss or an unresolvable unit escalates, never guesses.** Same
   posture as `verify_unit_from_cache`'s `AC-17` and `reducibility.py`'s
   `UNSTRUCTURED_UNRESOLVED` — a subprogram outside this plan's narrow shape
   (more than 2 linkage params, non-numeric, more than one paragraph) raises
   `UnsupportedProgramError`-style, never silently falls back to guessing a
   shape.
5. **Local WSL delegation is opt-in and disclosed, never a default-path
   change.** Exactly like the existing Groq CI exception and the Text
   Refinement exception (CLAUDE.md rule 10), any WSL delegation is gated by
   an explicit environment flag, documented as a third named exception if
   it lands, and never read anywhere else.

---

## 3. Phases

Each phase is independently mergeable. Phase N+1 does not start until Phase
N's exit criteria pass — same discipline as GRAPH_PLAN.md's M-numbered
milestones and this repo's existing CLAUDE.md rule 1.

### Phase X1 — Subprogram frontend parser

**Deliverable:** `weaver/cobol/subprogram.py`:
`SubprogramModel(program_id, source_path, input_param: Field, output_param: Field, paragraph_id, paragraph_source)`,
`load_subprogram(cobol_source: Path) -> SubprogramModel`. Reuses
`weaver.cobol.data_division.parse_items`/`flatten`/`weaver.cobol.pic.parse`
on the `LINKAGE SECTION` block (same PIC-parsing machinery Phase U already
hardened, applied to a different section) — no new PIC-clause logic.

**Scope, exactly:** `PROGRAM-ID` + `LINKAGE SECTION` with exactly 2 numeric
elementary items, `PROCEDURE DIVISION USING <in> <out>` naming them in that
order, exactly one paragraph (via `weaver.agent.segment.segment()`, reused
unchanged). Anything else raises `UnsupportedSubprogramError`.

**Exit criteria:**
- `load_subprogram(LEAF_A)` and `load_subprogram(LEAF_B)` produce correct
  models, hand-verified against the source text.
- A source with an FD, more than 2 linkage params, or more than one
  paragraph raises, with a test proving each case.
- Zero changes to `weaver/cobol/frontend.py`, `weaver/cobol/data_division.py`'s
  public surface, or any of the 8 existing fixtures' tests.

### Phase X2 — Subprogram scaffold generator

**Deliverable:** `weaver/agent/subprogram_scaffold.py`:
`generate(model: SubprogramModel, method_body: str | None = None) -> str` —
a standalone Java class (`public final class <ClassName>`) with one
`public static BigDecimal <method>(BigDecimal <inputParam>)`, body either a
synthesis-slot placeholder (`method_body is None`, for the scaffold-only
step) or the supplied body (for X3's driver generation and X4's real runs).

**Exit criteria:**
- Generated scaffold for `LEAF-A` compiles under `javac` with a hand-written
  correct body substituted in (`return input.multiply(TWO);` or equivalent) —
  proves the generated class shape is valid Java, independent of any
  synthesis/verification machinery.
- Field naming/rounding conventions match this repo's existing
  `_decode_field_expr`/`BigDecimal` conventions (`weaver/agent/scaffold.py`)
  for consistency, not reinvented.

### Phase X3 — Real parity verification axis (hard gate)

**Deliverable:** `weaver/agent/subprogram_verify.py`:
`verify_subprogram(model, candidate_method_body, witnesses: list[Decimal], work_dir: Path) -> SubprogramVerifyResult`
(`compiled: bool`, `divergences: list[SubprogramDivergence(input, oracle_output, candidate_output)]`).

Mechanics:
- Generates a small COBOL driver (`<program>_driver.cob`, deterministic
  template, not hand-authored per subprogram) that reads one decimal per
  line from stdin, `CALL`s the target subprogram by literal name, writes one
  decimal per line to stdout. Compiles it together with the real
  already-compiled subprogram (`cobc -m`/`cobc -x`, same technique proven in
  Task 6) — this is the **oracle** side, run once per witness set, real
  GnuCOBOL, never simulated.
- Generates a small Java driver with the same stdin/stdout protocol around
  X2's scaffold + the candidate body, compiles and runs it the same way —
  the **candidate** side.
- Diffs oracle vs. candidate output per witness line using
  `weaver.comparison`'s existing `Decimal`-exact comparison — no new
  equivalence rule (Non-Negotiable Design Decision 2).
- Execution goes through `weaver/execution.py`'s existing
  `_run_in_isolated_dir` convention unchanged on a platform with native
  `cobc`/`javac` (CI). On a platform without native `cobc` (this dev
  machine), a `WEAVER_COBC_VIA_WSL=1`-gated shim wraps the same command in
  `wsl -e`, added as a small, disclosed, opt-in branch in `execution.py` —
  never the default, never silent (mirrors CLAUDE.md rule 10's existing
  exceptions; requires its own CLAUDE.md rule 10 addendum before landing).

**Exit criteria (blocking, mirrors GRAPH_PLAN.md M7's discipline):**
- `verify_subprogram(LEAF_A_model, <correct body>, witnesses=<Task 6's 6
  accounts.dat values>, ...)` reports zero divergences, using a **real**
  `cobc`-compiled `LEAF-A.cob` run for the oracle side — proven on this
  machine via the WSL shim, and documented as needing re-confirmation on a
  native-`cobc` CI runner before this phase is considered portable-proven.
- `verify_subprogram(LEAF_A_model, <deliberately wrong body, e.g. add
  instead of multiply>, ...)` reports a nonzero divergence at the exact
  witness where behavior differs — proves the axis actually discriminates,
  not just a green rubber stamp.
- No fabricated witness output anywhere in the test suite (Non-Negotiable
  Design Decision 3) — every expected value in a test is either computed by
  hand and cross-checked against a live run, or captured from a live run
  directly, with the capture command shown in the test file's docstring
  (mirrors Task 6's own discipline).

### Phase X4 — Synthesis + repair wiring for a subprogram unit

**Deliverable:** a `SubprogramOrchestrator` (new, small — `weaver/agent/subprogram_orchestrator.py`),
sibling to `Orchestrator`, not a modification of it (Non-Negotiable Design
Decision 1's spirit extended: file-based and subprogram-based units are
different enough shapes to keep their driving loops separate rather than
branching one class on program shape). Reuses `synthesize_paragraph`/
`InferenceClient` (both already generic over a `Paragraph`, no change
needed) for the model call, X3's `verify_subprogram` in place of
`attribution.verify_unit`, and a minimal repair loop (re-prompt with the
failing witness's oracle vs. candidate values on divergence, bounded by
`spec.max_repairs`, reusing `RunSpec.max_repairs`'s existing field rather
than adding a new one).

**Exit criteria:**
- A real Ollama run (`qwen2.5-coder`, this repo's existing default model)
  synthesizes a body for `LEAF-A`'s paragraph that `verify_subprogram`
  accepts with zero divergences, without a hand-written seed body — the
  first real, unassisted synthesis-to-verified-commit run for a subprogram
  unit.
- Same for `LEAF-B`.
- A trace event stream (reusing `Orchestrator._emit`'s JSON-lines
  convention) records the run, so it is inspectable the same way a
  file-based run's `trace.jsonl` is.

### Phase X5 — Real `UnitCache` harvest for a subprogram leaf

**Deliverable:** extend `weaver/agent/unit_cache.py`'s `UnitCache`/
`UnitFixture` (GRAPH_PLAN.md M6 artifact) to accept subprogram-shaped
fixtures directly from X3's witness run (input/output pairs are already
exactly what `UnitFixture(paragraph_id, record_index, input_state,
output_state)` models — record_index becomes witness index, input_state/
output_state become the single input/output param) — additive reuse, not a
new cache format.

**Exit criteria:**
- After X4's `SubprogramOrchestrator` commits `LEAF-A`, a `UnitCache`
  directory exists on disk with `LEAF-A`'s 6 witness fixtures, loadable by
  the existing `weaver.agent.unit_cache.load_valid`.
- `verify_unit_from_cache`-equivalent fast-path lookup for a subprogram
  witness (new tiny function, not a rewrite of the file-based one) agrees
  with a live `verify_subprogram` re-run on all 6 witnesses — same
  equivalence-gate discipline as GRAPH_PLAN.md M7/`AC-16`, scaled to this
  smaller surface.

### Phase X6 — `LeafOrchestrator` real dispatch

**Deliverable:** `weaver/agent/leaf_orchestrator.py`'s
`_default_orchestrator_factory` (or a new `_resolve_program_kind` step)
inspects each DAG node's source file — `LINKAGE SECTION` + no
`FILE-CONTROL` → dispatches to X4's `SubprogramOrchestrator`; `FILE-CONTROL`
present → dispatches to the existing `Orchestrator`, unchanged. `_select_stub_dir`
(already built in Task 8) starts actually receiving a real cache directory
for `LEAF-A`/`LEAF-B` instead of nothing.

**Exit criteria:**
- `LeafOrchestrator(FIXTURE_DIR, RunSpec()).run()` — no fake, no injected
  factory — migrates `LEAF-A` and `LEAF-B` for real (X4), before `ROOT`
  (DAG order, already correct since Task 7), and `ROOT`'s spec receives a
  real, non-`None` `unit_cache_dir` pointing at a committed leaf's cache.
- Existing Task 8 tests (against the fake orchestrator) keep passing
  unmodified — the factory injection point they rely on is preserved, not
  removed.

### Phase X7 — `ROOT.cob` real translation with resolved `CALL`s (stretch, own exit criteria)

**Deliverable:** `ROOT.cob` gets its own frontend path (Phase X1's module
does not cover it — it has `FILE-CONTROL`, so it is `load_program()`'s
shape, but `load_program()` currently requires a totals line `ROOT.cob`
does not have). This phase is scoped separately and may be cut without
blocking X1–X6, which stand on their own: **a totals-optional relaxation
to `load_program()`**, tested to leave all 8 existing fixtures' exact
code path (and hence their frozen checksums) untouched — gated behind
`len(output_records) == 1` being a new, additive branch, never a
replacement of the existing `== 2` path.

**Exit criteria:**
- All 8 existing fixtures' golden checksums and the 132-divergence number
  are bit-for-bit unchanged (hard gate, CLAUDE.md rule 6/7 — same discipline
  Task 5's `redefines_as_subclasses` opt-in used for exactly this kind of
  risk).
- `ROOT.cob` parses via `load_program()`'s new optional branch.
- `ROOT.cob`'s synthesized `PROCESS-RECORD` body, produced by real
  synthesis, correctly resolves its two `CALL "LEAF-A"`/`CALL "LEAF-B"`
  statements to real Java method calls against X4's committed, verified
  leaf translations (new prompt context: the leaf's public method signature,
  supplied the same way `weaver/agent/scaffold.py` already supplies
  accessor context today) — final end-to-end proof: `weaver verify` against
  `golden_multiprog.out` (Task 6's already-frozen number) passes with the
  assembled 3-program Java translation, zero divergences.

---

## 4. Milestones Table

| ID | Deliverable | Depends on | Exit criteria |
|---|---|---|---|
| X1 | `weaver/cobol/subprogram.py` | — | Correct models for LEAF-A/LEAF-B, hand-verified; out-of-scope shapes raise |
| X2 | `weaver/agent/subprogram_scaffold.py` | X1 | Generated class compiles with a hand-written body |
| X3 | `weaver/agent/subprogram_verify.py` | X1, X2 | **Blocking**: 0 divergences on a correct body, nonzero on a deliberately wrong one, real cobc-compiled oracle |
| X4 | `weaver/agent/subprogram_orchestrator.py` | X3 | Real Ollama synthesis commits LEAF-A and LEAF-B unassisted |
| X5 | `UnitCache` extension for subprogram fixtures | X4 | Cache round-trips; fast-path lookup agrees with live `verify_subprogram` on all witnesses |
| X6 | `LeafOrchestrator` real dispatch | X4, X5 | Real (non-fake) `LeafOrchestrator.run()` migrates LEAF-A/LEAF-B before ROOT with a real stub cache dir threaded |
| X7 (stretch) | `load_program()` totals-optional + ROOT.cob real translation | X6 | 8 existing fixtures unchanged; `weaver verify` on assembled 3-program translation passes against `golden_multiprog.out` |

X3 is a hard stop, same posture as GRAPH_PLAN.md's M7: X4 does not start
until X3's real-vs-wrong-body discrimination test passes.

---

## 5. Cut List — In Order

When behind, cut from the bottom:

1. X7 — the whole plan is valuable and demoable without it; `ROOT.cob`
   staying unmigrated does not diminish X1–X6's proof that subprogram
   verification and leaf-first dispatch are real.
2. X5's fast-path equivalence gate — X6 can thread a real cache directory
   without a proven-equivalent fast lookup; the slow (always re-verify)
   path stays correct, only slower, matching GRAPH_PLAN.md's own M8
   "opt-in, never required" posture for `use_unit_cache`.
3. The WSL shim in X3 — if this repository moves primary development to a
   machine/CI with native `cobc`, the shim is a local convenience only, not
   load-bearing for correctness.

**Never cut:** X1–X4's real-witness, real-execution, non-fabricated-output
discipline (Non-Negotiable Design Decision 3) — this plan does not "pass"
by asserting against invented numbers, ever, at any phase.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| WSL shim silently becomes load-bearing for CI too | Gated behind an explicit env var, only referenced in `execution.py`'s new branch, documented as a third CLAUDE.md rule 10 exception before it lands (X3) |
| Subprogram parser scope creeps to "support any LINKAGE SECTION shape" | Phase X1's scope is written as exactly 2 numeric params, one paragraph — anything else raises, per Non-Negotiable Design Decision 4 |
| `SubprogramOrchestrator` duplicates `Orchestrator` logic and drifts | Both call the same `synthesize_paragraph`/`InferenceClient`; only the verify/repair step differs by construction (file-diff vs. parity-check) — reviewed explicitly at X4's task review for duplication vs. genuine necessary difference |
| X7's totals-optional relaxation accidentally changes an existing fixture's code path | New branch is `if len(output_records) == 1` before the existing `== 2` check ever runs for a program that has 2 — existing fixtures never reach the new branch; proven by re-running all 8 fixtures' tests unchanged, hard gate before X7 merges |

---

## 7. Implementation Note

Each phase (X1...X7) is intended to be implemented, reviewed, and merged
**one at a time**, in its own session/turn — this plan exists specifically
so no single sitting has to hold X1 through X7's full scope at once. Start
at X1; do not begin X2 until X1's exit criteria are shown passing.
