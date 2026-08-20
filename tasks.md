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
| X7 | `ROOT.cob` totals-optional frontend relaxation + resolved `CALL` translation (stretch) | ❌ not started |

---

## Explicitly out of scope (roadmap — deferred with reasons, not built)

- ❌ Six witness-search algorithms (pairwise, three-way, Latin hypercube, adaptive random, MAP-Elites, UCB1 bandit) — `migration-framework-spec.md` §5.2; a fixed, hand-verified 6-value witness set is this plan's declared floor instead.
- ❌ Delta debugging / input minimization — §2.2; no existing failure case needs it.
- ❌ `EXEC SQL`/`EXEC CICS` dynamic mocking, "Paragraphs Hit"/"External Stub Log" parity axes — §2.1/§2.2; no fixture uses them.
- ❌ PostgreSQL / RabbitMQ / REST-for-CICS connector substitution — §4.2; no fixture exercises a database, queue, or CICS transaction.
- ❌ Hierarchical recursive segment-and-merge for massive files — §3.1; all fixtures are small enough for flat `segment()`.
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

## Only outstanding item

X7 (stretch) — `ROOT.cob`'s totals-optional frontend relaxation and
resolved `CALL` translation. Not started; not required for X1–X6 to stand
on their own.
