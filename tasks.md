# Migration Framework — Task Checklist

Tracks every task/phase `migration-framework-spec.md` and its two
implementation plans (`docs/superpowers/plans/2026-08-19-migration-framework-upgrade.md`
= Phase W, `docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md` = Phase X) actually
call for. ✅ = built and proven (real toolchain/tests passing). ❌ = not
finished. A task marked ⚠️ is code-complete but its exit criteria could not
be proven end-to-end yet, for a disclosed reason — not the same as untouched.

---

## Phase W — Migration Framework Upgrade (merged to `main` 2026-08-19)

| # | Task | Status |
|---|---|---|
| 1 | CLAUDE.md rule 10 amendment (Text Refinement exception) | ✅ |
| 2 | `weaver/agent/text_refine.py` — opt-in hosted refinement pass | ✅ |
| 3 | `GO TO` target extraction (`weaver/cobol/callgraph.py`) | ✅ |
| 4 | `weaver/cobol/reducibility.py` — classify/rewrite `GO TO` control flow | ✅ |
| 5 | REDEFINES-as-subclass byte-buffer accessors (`scaffold.py`) | ✅ |
| 6 | Multi-program `CALL` fixture (`fixtures/cobol/multiprog/`) | ✅ |
| 7 | `weaver/cobol/program_dag.py` — cross-program leaf-first DAG | ✅ |
| 8 | `weaver/agent/leaf_orchestrator.py` — DAG sequencing + stub-cache threading | ✅ (real dispatch proven in Phase X6) |

---

## Phase X — Subprogram Verification & Real Leaf-First Migration

| # | Phase | Status |
|---|---|---|
| X1 | `weaver/cobol/subprogram.py` — `LINKAGE SECTION` subprogram parser | ✅ |
| X2 | `weaver/agent/subprogram_scaffold.py` — subprogram scaffold generator | ✅ |
| X3 | `weaver/agent/subprogram_verify.py` — real parity verification axis (blocking gate) | ✅ |
| X4 | `weaver/agent/subprogram_orchestrator.py` — synthesis + repair wiring | ✅ real, unassisted local Ollama synthesis commits `LEAF-A` and `LEAF-B` with 0 divergences (proven 2026-08-20 via Ollama running in WSL) |
| X5 | Real `UnitCache` harvest for a subprogram leaf | ✅ |
| X6 | `LeafOrchestrator` real dispatch (`_program_kind`, no fake factory) | ✅ real end-to-end run proven: `LEAF-A`/`LEAF-B` commit for real via Ollama before `ROOT`, real `UnitCache` dir created, Task 8's fake-orchestrator tests still pass unmodified |
| X7 | `ROOT.cob` totals-optional frontend relaxation + resolved `CALL` translation (stretch) | ✅ real, unassisted Ollama synthesis resolves both `CALL "LEAF-A"`/`CALL "LEAF-B"`; assembled 3-program Java translation matches `golden_multiprog.out` byte-for-byte, 0 divergences |
| X8 | Six witness-search algorithms (`weaver/agent/witness_search.py`), generic over any subprogram/program field count (stretch) | ✅ real pairwise/three-way/LHS/adaptive-random/MAP-Elites/UCB1, generic `FieldDomain`-based, never hardcoded to a fixture; widened `weaver/cobol/subprogram.py` to N-input LINKAGE grammar; `witnesses_for_program`/`synthetic_records.py` full-program adapter proven against real `interest.cob` |

---

## Phase Y — Delta Debugging (2026-08-20, migration-framework-spec.md §2.2)

| # | Phase | Status |
|---|---|---|
| Y1 | `weaver/agent/delta_debug.py` (generic Zeller `ddmin`) + `weaver/agent/input_minimize.py` (real candidate-re-run adapter), wired into `repair_loop.py` behind `RunSpec.use_delta_debugging` | ✅ real: `test_input_minimize.py` minimizes a real multi-divergence corruption of `PROCESS-RECORD` down to a proven-minimal single record; `test_repair_loop_delta_debug.py` proves the repair loop's model prompt actually receives the minimized counterexample instead of `divergences[0]` |

---

## Phase Z — Dynamic Mocking & Paragraphs-Hit / External-Stub-Log Axes (2026-08-20, migration-framework-spec.md §2.1/§2.2)

| # | Phase | Status |
|---|---|---|
| Z1 | `weaver/cobol/mock_directives.py` (EXEC SQL/CICS parser) + `weaver/agent/mock_generator.py` (deterministic mock + source rewriter) + `weaver/agent/parity_axes.py` (Paragraphs Hit, External Stub Log) + `weaver/agent/mocked_verify.py` (real parity check over all 3 axes) + `fixtures/cobol/mocked/billing.cob` | ✅ real: `test_mocked_verify.py` -- real `cobc` compiles a source-rewritten oracle (EXEC SQL block replaced by its deterministic mock), real `javac`/`java` runs a candidate calling the matching `WeaverMockRuntime`; a correct candidate matches all 3 axes, a candidate that skips the mock call is caught by the External Stub Log axis, a candidate with a wrong paragraph trace is caught by the Paragraphs Hit axis |
| Z2 | `weaver/agent/connector_map.py` (EXEC SQL/CICS verb -> PostgreSQL/RabbitMQ/REST) + `weaver/agent/connector_codegen.py` (real adapters + `schema.sql`/`docker-compose.yml`/`connectors.properties`) + `weaver connectors` CLI + `fixtures/cobol/mocked/orders.cob` | ✅ real, disclosed asymmetry: `PostgresDataSource.java`/`RestTransactionGateway.java`/`OfflineAdapters.java` are JDK-only and proven by real `javac` with an **empty classpath** (`test_connector_codegen.py`); `RabbitMqQueue.java` needs `com.rabbitmq.client` at compile time (proven it genuinely fails without the jar, same test file) -- opt-in live lane (`WEAVER_LIVE_CONNECTORS=1`, CLAUDE.md rule 10 exception) proves a real HTTP round trip through the generated REST gateway now, and real postgres/rabbitmq container round trips whenever Docker's daemon is reachable (`test_connectors_live.py`) |

---

## Phase AA — Hierarchical Recursive Segment-and-Merge (2026-08-20, migration-framework-spec.md §3.1)

| # | Phase | Status |
|---|---|---|
| AA1 | `weaver/agent/hierarchical_segment.py` (intra-file PERFORM call graph, leaf-first cycle-tolerant topological order, recursive size-bounded block splitting) + `weaver/agent/batch_prompt.py` + `weaver/agent/batch_synthesize.py` (one LLM call per block, "topological call rankings" = already-translated sibling methods named in each later block's prompt) + `fixtures/cobol/hierarchical/big_program.cob` | ✅ real: `test_hierarchical_segment.py` proves real recursive splitting (depth > 0) and leaf-first ordering against a real 9-paragraph fixture parsed by the real `segment()`, plus a genuinely cyclic case handled deterministically; `test_batch_synthesize.py` proves leaf-first context actually reaches later prompts, reuses `validate.py`'s hardened `auto_qualify`/`static_reject` unmodified, and merges via the real, unmodified `assemble()` into real `javac`-compiled, `java`-executed, order-verified output |

---

## Explicitly out of scope (roadmap — deferred with reasons, not built)

- ✅ ~~Six witness-search algorithms~~ — built 2026-08-20, Phase X8. See `docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md` X8 and `weaver/agent/witness_search.py`.
- ✅ ~~Delta debugging / input minimization~~ — built 2026-08-20, Phase Y1. `weaver/agent/delta_debug.py` (generic Zeller ddmin) + `weaver/agent/input_minimize.py` (real candidate re-run adapter), wired into `repair_loop.py` behind `RunSpec.use_delta_debugging` (default False).
- ✅ ~~`EXEC SQL`/`EXEC CICS` dynamic mocking, "Paragraphs Hit"/"External Stub Log" parity axes~~ — built 2026-08-20, Phase Z1. See `weaver/agent/mocked_verify.py`, `weaver/agent/parity_axes.py`, `fixtures/cobol/mocked/billing.cob`. Terminal State remains `weaver/comparison.py`'s existing, untouched byte-for-byte axis (CLAUDE.md rule 3).
- ✅ ~~PostgreSQL / RabbitMQ / REST-for-CICS connector substitution~~ — built 2026-08-20, Phase Z2. See `weaver/agent/connector_codegen.py`, `weaver connectors` CLI, `fixtures/cobol/mocked/orders.cob`. Generated code is migration output only; every `weaver verify`/`weaver migrate` run still binds the offline adapter (CLAUDE.md rule 10) — never the real connectors.
- ✅ ~~Hierarchical recursive segment-and-merge for massive files~~ — built 2026-08-20, Phase AA1. See `weaver/agent/hierarchical_segment.py`, `weaver/agent/batch_synthesize.py`, `fixtures/cobol/hierarchical/big_program.cob`. A generic capability over any `Paragraph` list, not wired into `ScaffoldSpec`'s existing single-paragraph-per-program synthesis path (that widening is further work).
- ❌ Application-wide Class Designer dedup across modules — §3.2's stronger claim; no fixture proves out cross-program class sharing yet.

---

## Resolved blocker (2026-08-20)

The native Windows Ollama install was returning `400 "does not support
generate"` for every model on both `/api/generate` and `/api/chat`; a
process restart did not fix it. Fixed by running Ollama inside WSL instead
(`ollama serve` in WSL, `qwen2.5-coder:7b`/`nomic-embed-text` pulled there)
— WSL2's localhost forwarding exposes it to the Windows-side Python process
at `127.0.0.1:11434` unchanged, satisfying `inference.py`'s loopback-only
guarantee. A `wsl --shutdown` + restart was needed once to unstick flaky
port forwarding. X4 and X6's real-synthesis exit criteria both pass now.

## All planned phases complete

Phase W (8/8) and Phase X (X1–X7, including the X7 stretch phase) are all
built and proven for real: real `cobc`/`javac` compilation, real
unassisted local Ollama synthesis, real byte-for-byte comparison against
frozen golden outputs. Two genuine prompt-quality bugs were found and
fixed along the way during X7 (see commit `e1f83b0`): a broken
"write to ws." prohibition text for totals-optional programs, and a
missing worked example for cross-class CALL resolution that caused the
deterministic (temperature=0) model to repeatedly return an empty body.

Only the "Explicitly out of scope" roadmap items above remain — each
requires its own new spec/plan before any code, per CLAUDE.md's
scope discipline.

## Verification pass (2026-08-20)

Re-checked this file against `docs/specs/migration-framework-spec.md` and
the actual codebase, module by module:

| Spec section | Capability | Module | Present? |
|---|---|---|---|
| §1.1 Code Processing Agent | local paragraph/subprogram synthesis | `weaver/agent/inference.py` (`qwen2.5-coder:7b` via Ollama, substituted for the spec's example `granite-34b`/`granite-20b-code-cobol` — not available locally through Ollama; disclosed substitution, not a gap) | ✅ (substituted model) |
| §1.1 Text Processing Agent | opt-in hosted refinement | `weaver/agent/text_refine.py` (`gpt-4o-mini` — matches spec's named model) | ✅ |
| §2.1 `GO TO`/`PERFORM THRU` control-flow reduction | Method Designer | `weaver/cobol/reducibility.py`, `weaver/cobol/callgraph.py` | ✅ |
| §2.2 Failure Memory | persistent repair-loop memory | `weaver/agent/memory.py` (built under `AGENT_LAYER_PLAN.md`, predates this spec) | ✅ |
| §2.1/2.2 `EXEC SQL`/`EXEC CICS` mocking, Paragraphs-Hit / External-Stub-Log axes | dynamic mock generator | `weaver/agent/mock_generator.py` + `weaver/agent/parity_axes.py` (Phase Z1, 2026-08-20) | ✅ real cobc/javac, deterministic canned values |
| §2.2 Delta debugging | input minimizer | `weaver/agent/delta_debug.py` + `weaver/agent/input_minimize.py` (Phase Y1, 2026-08-20) | ✅ real ddmin over real candidate re-runs, opt-in via `RunSpec.use_delta_debugging` |
| §3.1 Hierarchical recursive segment-and-merge | large-file splitting | `weaver/agent/hierarchical_segment.py` (Phase AA1, 2026-08-20) | ✅ real recursive splitting + leaf-first topological order, not yet wired into `ScaffoldSpec`'s single-paragraph path |
| §3.2 Class Designer (app-wide dedup) | cross-module class sharing | per-program only, no app-wide dedup | ❌ not built |
| §3.2 Method Designer | CFG reduction → Java methods | `weaver/cobol/reducibility.py` | ✅ |
| §4.1 REDEFINES byte-buffer mirroring | subclass + getBytes/setBytes | `weaver/agent/scaffold.py` (confirmed present) | ✅ |
| §4.1 COMP-3 → BigDecimal | exact decimal | `weaver/layout.py`, `weaver/cobol/data_division.py` | ✅ |
| §4.2 PostgreSQL/RabbitMQ/REST connectors | cloud substitution | `weaver/agent/connector_codegen.py` (Phase Z2, 2026-08-20) | ✅ real adapters + descriptors, offline-bound at verify time |
| §5.1 DAG + topological sort | leaf/root classification | `weaver/cobol/program_dag.py` | ✅ |
| §5.2 Step 1 leaf isolation & translation | subprogram parse+scaffold+synth | `weaver/cobol/subprogram.py`, `weaver/agent/subprogram_scaffold.py`, `weaver/agent/subprogram_orchestrator.py` | ✅ |
| §5.2 Step 2 six-algorithm witness search | pairwise/3-way/LHS/adaptive/MAP-Elites/UCB1 | `weaver/agent/witness_search.py` (Phase X8, 2026-08-20) | ✅ generic over any field count, not fixture-hardcoded |
| §5.2 Step 3 upstream propagation/stubbing | parent-consumes-cached-leaf-output | `weaver/agent/leaf_orchestrator.py`, `weaver/agent/subprogram_verify.py` (`UnitCache`) | ✅ |

Confirmed via `python -m pytest -q`: 231 passed, 18 skipped (real-toolchain
tests gated on `javac`/reachable Ollama), 2 failed — the same pre-existing
Windows path-separator assertions in `tests/test_backend_run_spec.py`
(`\` vs `/` in a stringified `Path`), unrelated to this spec and unchanged
since before this session. No regressions. Table above reconfirms: nothing
newly built, nothing silently missing from the existing status rows above.
