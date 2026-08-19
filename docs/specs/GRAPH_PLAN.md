# LegacyWeaver — Knowledge Graph & Unit-Level Execution Memoization

**Problem 1 implementation plan · companion to `LEGACYWEAVER_PLAN.md` / `LEGACYWEAVER_SRS.md`**

---

## 0. Scope Contract

### IN
- A PERFORM graph over paragraphs, plus same-file `CALL` edges
- Per-paragraph read/write field sets
- `ProgramGraph`: nodes, edges, read/write sets, JSON serialization, and a query
  surface (`callees`, `callers`, `readers_of(field)`, `writers_of(field)`,
  `topological_order`)
- A source-instrumentation pass that derives a **separate compiled variant** of
  each oracle program, emitting a `DISPLAY` trace of read/write-set field values
  at paragraph entry/exit
- One harvest run per program producing a frozen, per-record, per-paragraph
  input→output state table (`UnitCache`)
- `verify_unit_from_cache()`: a table-lookup verifier usable by the repair loop as
  a faster substitute for `attribution.verify_unit()`, gated on proving exact
  agreement with it
- Applies to all 8 existing fixture programs (interest, feecalc, taxcalc,
  tieraccum, compound, shipcost, whseproc, bankproc)

### OUT — say "roadmap" on stage, do not build here
- Cross-program (separately compiled) `CALL` graphs — needs Problem 2's program-shape
  generalization first
- JCL-driven graph construction, CICS/DB2 seams — Problem 2
- Using the graph for agent tool-calling or multi-role orchestration — Problem 3
- Retiring `attribution.verify_unit` — it remains the ground truth forever; the
  cache accelerates repeated calls, it never becomes the sole authority
- Any change to `golden_interest.out`, its checksum, or the comparison contract

### The line to say out loud
> "The graph doesn't replace the oracle. It replaces re-running the oracle."

---

## 1. Non-Negotiable Design Decisions

**1. Instrumentation never touches the oracle that produces golden output.** The
instrumented binary is a separately compiled, separately named artifact, used
exactly once per program to harvest fixtures. `golden_interest.out` and its
checksum are produced by the same uninstrumented oracle as before, unchanged.

**2. The cache memoizes a real execution, never a simulation.** Every fixture in
it was produced by actually compiling and running GnuCOBOL — never inferred,
never hand-typed, never approximated.

**3. Cache correctness is proven, not assumed.** Before `verify_unit_from_cache`
is allowed anywhere near a real repair loop, it must reproduce — unit for unit —
the exact `divergence_count` and classification that `attribution.verify_unit`
produces against all 8 existing fixtures. Any disagreement blocks the phase. This
is the single hard gate in this document.

**4. The graph is additive, never a second source of truth for scaffold
generation.** `weaver/agent/scaffold.py` continues to read only `ScaffoldSpec`
(the Phase V invariant: parsing happens once, upstream, and emits data). The
graph answers a different question — relationships and captured runtime state —
not layout.

---

## 2. Relationship to the SRS

This is not wholly new scope. `LEGACYWEAVER_SRS.md` already specifies, and never
implements, most of the graph half of this work:

| SRS requirement | Status before this plan | What this plan does |
|---|---|---|
| `FR-1.5` Data-flow analysis **[SHOULD]** | Unimplemented; degrades to "pass the whole field table as context" (the actual current behavior) | Implements per-paragraph read/write sets; promotes from SHOULD to done |
| `FR-2.1` Dependency graph **[MUST]** | Unimplemented; no `weaver/agent/graph.py` exists | Implements `ProgramGraph` (PERFORM edges + shared-field writer→reader edges) |
| `FR-2.2` Migration ordering **[MUST]** | Unimplemented | Implements `topological_order()`; cycles collapse into one composite unit and are flagged, per the requirement's existing wording |
| `FR-2.3` Plan exposure **[MUST]** | Unimplemented | `ProgramGraph.to_json()` persists the plan; a future CLI step renders it before generation (not in this phase's scope — see §5, M7) |
| `A4` "no inter-program CALL" | Full assumption | Partially lifted: same-file `CALL` is now tracked. Cross-program `CALL` stays an open assumption — that's Problem 2 |

Execution memoization has no existing SRS coverage — the SRS's `MigrationUnit`
model (§4.3) assumes whole-program verification throughout. This plan proposes a
**Requirements Addendum** below; merging it into `LEGACYWEAVER_SRS.md` itself is a
separate, later edit, done only with sign-off, not as part of this phase.

### Requirements Addendum (proposed — not yet merged into the SRS)

**New §3.11 Execution Memoization Subsystem**

| ID | Requirement |
|---|---|
| `FR-9.1` **[MUST]** | The system shall derive an instrumented COBOL source variant from a parsed `ProgramModel` and its `ProgramGraph`, compiled to a binary distinct from the oracle binary used to produce golden output. |
| `FR-9.2` **[MUST]** | The system shall execute the instrumented binary exactly once per program against its fixture data and harvest a per-record, per-paragraph input→output state table. |
| `FR-9.3` **[MUST]** | The harvested table shall be persisted as `UnitCache`, keyed by a hash of (program source, paragraph source), invalidated on either changing. |
| `FR-9.4` **[MUST]** | `verify_unit_from_cache` shall be proven, before any operational use, to produce identical `divergence_count` and classification to `attribution.verify_unit` on every existing fixture. A single disagreement blocks this requirement from being marked satisfied. |

**New acceptance criteria** (continuing the SRS's existing `AC-1`–`AC-13`):

| ID | Criterion | Method |
|---|---|---|
| `AC-14` | Instrumented and oracle binaries are never the same artifact | Build-path audit: distinct output filenames/directories, checked in CI |
| `AC-15` | Golden output checksum is unchanged by this phase | `sha256sum` comparison against the frozen value before and after introducing instrumentation |
| `AC-16` | Cache-based verification agrees with whole-program attribution on every fixture | `tests/test_unit_cache_equivalence.py`: zero disagreements across all 8 programs' known divergences |
| `AC-17` | A cache miss or key mismatch falls back to `attribution.verify_unit`, never silently returns a stale result | Deliberately stale a cache entry; assert fallback fires and is logged |

---

## 3. Architecture / Data Flow

```
COBOL source ──▶ weaver/cobol/ (extended: callgraph.py, dataflow.py) ──▶ ProgramGraph
                                                                             │
                                                       informs instrumentation
                                                                             │
                                                                             ▼
oracle binary (unmodified) ──▶ golden_output (unchanged, untouched)   instrumented oracle
                                                                        (separate build)
                                                                             │
                                                                    one harvest run
                                                                             │
                                                                             ▼
                                                          paragraph state-transition trace
                                                                             │
                                                                             ▼
                                                                        UnitCache
                                                                     (frozen JSON)
                                                    ┌────────────────────────┴────────────────────────┐
                                                    ▼                                                    ▼
                                     verify_unit_from_cache()                          attribution.verify_unit()
                                     fast path — spec.use_unit_cache=True              ground truth — always available,
                                     falls back to the right column on any miss        used for the one-time equivalence
                                                                                        proof (FR-9.4) and as fallback
```

---

## 4. New Modules

- **`weaver/cobol/callgraph.py`** — `Perform(source, target, kind)`,
  `Call(source, program)` dataclasses. Extends `procedure.py`'s existing
  regex-scrape style (its `Move`/`Add` dataclasses are the direct pattern:
  small, source-text-scoped, no AST).

- **`weaver/cobol/dataflow.py`** — `ReadWriteSet(paragraph_id, reads: set[str],
  writes: set[str])`, derived by walking each paragraph's statements and
  classifying identifiers against the `DataItem` table from `data_division.py`:
  `MOVE src TO dst` → src read, dst written; `ADD a TO b` → both read, b written;
  `COMPUTE b = expr` → expr's identifiers read, b written; `IF`/`EVALUATE`
  conditions → read only.

- **`weaver/agent/graph.py`** — `ProgramGraph` dataclass (nodes, edges,
  read/write sets), with `to_dict()`/`to_json()` following `Report.to_json()` /
  `RunSpec.to_dict()`'s existing convention: an explicit payload dict, `Path`/
  `Decimal` special-cased, never raw `asdict()` on anything non-JSON-native.
  Query methods: `callees`, `callers`, `readers_of`, `writers_of`,
  `topological_order` (Kahn's algorithm; a cycle collapses into one composite
  unit and is flagged, per `FR-2.2`).

- **`weaver/agent/instrument.py`** — given a `ProgramModel` + `ProgramGraph`,
  emits an instrumented COBOL source variant
  (`DISPLAY 'WEAVER-TRACE:<paragraph>:<field>=<value>'` at paragraph entry for
  reads, exit for writes), compiled separately via `cobc -x` into a distinctly
  named binary in its own build subdirectory.

- **`weaver/agent/trace_harvest.py`** — runs the instrumented binary once,
  reusing `weaver/execution.py`'s existing `_run_in_isolated_dir` subprocess
  mechanics rather than duplicating them; parses `WEAVER-TRACE:` lines from
  stdout into `UnitFixture(paragraph_id, record_index, input_state, output_state)`.

- **`weaver/agent/unit_cache.py`** — `UnitCache` load/save to
  `generated/graph_cache/<program_stem>/<paragraph_id>.json`; cache key = hash of
  (COBOL source, paragraph source) for invalidation;
  `verify_unit_from_cache(unit_id, candidate_body, work_dir, *, spec) ->
  AttributionResult`-shaped result — compiles only the candidate body against a
  small per-record replay harness, comparing its output state to the frozen
  `output_state` using the existing `weaver.comparison` byte-for-byte machinery.
  Never a new or parallel comparison rule — the comparison contract stays
  singular, per CLAUDE.md rule 3.

---

## 5. Milestones

| ID | Deliverable | Depends on | Exit criteria |
|---|---|---|---|
| M1 | PERFORM/CALL extraction (`callgraph.py`) | — | Correct edges on all 8 fixtures, hand-verified against source |
| M2 | Read/write set extraction (`dataflow.py`) | — | Sets hand-verified for `interest.cob`'s `PROCESS-RECORD` against a paper trace |
| M3 | `ProgramGraph` data model + query surface | M1, M2 | Round-trips through `to_json()`/reload with no data loss; `topological_order` correct on all 8 fixtures |
| M4 | Instrumentation pass (`instrument.py`) | M3 | Instrumented variant compiles under GnuCOBOL 3.x for all 8 fixtures |
| M5 | Harvest (`trace_harvest.py`) | M4 | One harvest run per fixture produces a complete per-record, per-paragraph trace with no gaps |
| M6 | `UnitCache` storage + `verify_unit_from_cache` | M5 | Cache round-trips; fast-path verify runs without invoking the whole-program pipeline |
| M7 | **Equivalence gate** (`test_unit_cache_equivalence.py`) | M6 | Zero disagreements with `attribution.verify_unit` across all 8 fixtures (`AC-16`) — blocking |
| M8 | `RunSpec`/`Orchestrator` integration, opt-in | M7 | `use_unit_cache=True` reproduces identical orchestrator outcomes to `use_unit_cache=False` on every fixture, with a fallback path exercised deliberately (`AC-17`) |

M7 is a hard stop: M8 does not start until M7 passes.

---

## 6. Data Model

```python
ReadWriteSet:
    paragraph_id: str
    reads: set[str]      # field ids
    writes: set[str]      # field ids

ProgramGraph:
    program_id: str
    paragraphs: list[str]
    performs: list[Perform]        # source, target, kind (TO/THRU)
    calls: list[Call]              # source, program (same-file only, this phase)
    read_write_sets: dict[str, ReadWriteSet]   # keyed by paragraph_id

UnitFixture:
    paragraph_id: str
    record_index: int
    input_state: dict[str, str]    # field id -> raw value at paragraph entry
    output_state: dict[str, str]   # field id -> raw value at paragraph exit

UnitCache:
    program_id: str
    cache_key: str                  # hash(program_source, paragraph_source)
    fixtures: list[UnitFixture]
```

---

## 7. Acceptance Criteria

See the Requirements Addendum (§2) for `AC-14`–`AC-17`. Summary:

| ID | Criterion |
|---|---|
| `AC-14` | Instrumented and oracle binaries are never the same artifact |
| `AC-15` | Golden output checksum is unchanged by this phase |
| `AC-16` | Cache-based verification agrees with whole-program attribution on every fixture — **blocking** |
| `AC-17` | A cache miss or key mismatch falls back to the real verifier, never silently |

---

## 8. Cut List — In Order

When behind, cut from the top:

1. Cross-paragraph `CALL` edges — PERFORM-only is sufficient for every existing
   single-compilation-unit fixture
2. Cycle-collapse handling — none of the 8 fixtures has a PERFORM cycle;
   confirmed nice-to-have, not load-bearing
3. Per-iteration state inside `tieraccum`'s inner `PERFORM VARYING` — per-record
   granularity is the floor; per-iteration is a refinement
4. `RunSpec`/`Orchestrator` integration (M8) — the graph and cache remain
   independently valuable and demoable without ever being wired into a live run

**Never cut:** the harvest-vs-oracle separation (design decision 1), the cache
equivalence gate (design decision 3, M7/`AC-16`).

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Instrumentation `DISPLAY` output changes program timing/behavior enough to affect the oracle | Instrumented and oracle binaries are never the same artifact (design decision 1); golden output checksum is diffed before/after (`AC-15`) |
| GnuCOBOL `DISPLAY` buffering/interleaving across paragraph calls corrupts per-record attribution | One `DISPLAY` per statement, explicit record-index tag on every line, hand-verified against a fixture's known trace before trusting the harvester on the rest |
| Cache silently goes stale after a source edit | Cache key is a hash of (program source, paragraph source); any change invalidates, forcing re-harvest rather than serving stale fixtures |

---

## 10. What Changes in Existing Code

Kept surgical:

- `RunSpec` gains `use_unit_cache: bool = False` and
  `unit_cache_dir: Path | None = None`, threaded explicitly and covered by
  `tests/test_param_plumbing.py`'s existing guard against accepted-but-unused
  parameters.
- `Orchestrator._process_unit` gains one conditional branch: call
  `verify_unit_from_cache` instead of `attribution.verify_unit` when the flag is
  set and a valid cache entry exists; fall back to the real verifier on any cache
  miss or key mismatch — never silently.
- Nothing else in the existing pipeline changes. `weaver/agent/scaffold.py`,
  `program_profiles.py`, and the comparison/classification modules are untouched.

---

## Tests

New test files, one per module, following this repo's existing convention:

- `tests/test_cobol_callgraph.py`
- `tests/test_dataflow.py`
- `tests/test_graph.py`
- `tests/test_instrument.py` — skip-if-no-`cobc`, mirroring the existing
  `requires_javac` pattern in `tests/test_candidate_supplied.py`
- `tests/test_unit_cache.py`
- `tests/test_unit_cache_equivalence.py` — the hard-gate test `AC-16` cashes out
  as: compares cache-based vs whole-program verification across all 8 fixtures
