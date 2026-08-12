# Latest changes (2026-08-12)

This document summarizes what changed in the most recent round of work, for
teammates who weren't in the room. It covers one new capability
(candidate-supplied verification), a set of bug fixes found by a full-project
audit, and four new COBOL fixture programs.

Branch: `fix/audit-findings-and-candidate-supplied-mode`, merged to `main`
at commit `f314f9a`.

---

## 1. New capability: verify your own Java file directly ("candidate-supplied mode")

**What it is.** Previously, the only way to get a Java translation of a
COBOL paragraph was to let the local LLM synthesize one (`weaver migrate`,
or the backend's default run mode). Now you can hand the system a Java
method body you already wrote — by hand, from an old migration, from a
hunch about a fix — and ask it to verify that specific file instead of
generating a new one. Zero model calls, straight to compile + differential
comparison.

**Why it matters.** This was already possible at the single-command level
(`weaver verify <cobol> <java> <data>` has always done exactly this). What's
new is that it's now wired into the *backend's* run pipeline — the same
trace/lifecycle/metrics/escalation machinery a synthesized run gets — so a
human-supplied candidate shows up in the API the same way an autonomous run
does, instead of being a separate one-off code path.

**How to use it (backend API):**

```jsonc
POST /runs
{
  "cobol_source": "fixtures/cobol/interest.cob",
  "data_file": "fixtures/data/accounts.dat",
  "synthesis_mode": false,
  "candidate_path": "path/to/your/method_body.java"
}
```

- `candidate_path` must point at a **method body** (the statements that go
  inside the paragraph's Java method), not a full class file — the same
  format used everywhere else in the codebase (see any `reference_*/*.body.java`
  file for examples).
- If the body verifies clean (0 divergences), the run commits immediately.
- If it diverges, the **same repair loop** a synthesized body would get
  kicks in (deterministic patches first, then model-assisted repair) — this
  isn't a dead end, just a different starting point.
- Only works for **single-synthesis-unit programs** right now. If the COBOL
  program has more than one paragraph needing translation, the run fails
  loudly with a clear error rather than guessing which paragraph your file
  is for.
- The API validates the pairing up front: `synthesis_mode: false` without a
  `candidate_path`, or a `candidate_path` that doesn't exist, gets rejected
  with a 400 before a run is even created.

**Where the code lives:** `RunSpec.candidate_body_path` (the plumbing),
`Orchestrator._process_unit()` (the skip-synthesis branch),
`backend/runs.py::_build_run_spec()` / `RunManager.create_run()` (API wiring
and validation).

---

## 2. Bug fixes from a full-project audit

We ran a systematic audit of every layer (MVP harness, agent layer, backend,
plus a live regression pass across all fixtures) against the SRS/plan docs.
Real, live bugs found and fixed:

### The backend was silently ignoring most run parameters
`backend/runs.py` was building every run's `RunSpec` from only two fields
(`cobol_source`, `data_file`) and defaults for everything else — meaning
`seed`, `model_name`, `max_repair_attempts`, `replay`, and `copybook_dir`
sent in a `POST /runs` request had **no effect**, even though the API
echoed them back as if they'd been used. Worse: the backend never resolved
a program-specific config, so launching a run against anything other than
`interest.cob` (feecalc, taxcalc, etc.) would have silently verified against
**interest.cob's** scaffold and golden output.

Fixed by extracting the CLI's per-program config registry into a shared
module (`weaver/agent/program_profiles.py`) that both `weaver` (CLI) and the
backend now use, and building a real `_build_run_spec()` that threads every
request field through.

### Decimal scale was hardcoded to `2` in several places
`repair_deterministic.py`, `verify.py`, and `orchestrator.py` all assumed
every numeric field has scale 2 — true for `interest.cob`'s two
working-storage fields by coincidence, false in general. A field genuinely
declared at a different scale would have been mis-repaired or
mis-classified. Now derived from each program's own field declarations
(`weaver/agent/scaffold.py::field_scale()`).

### A few smaller fixes
- **Thread safety:** the orchestrator's per-unit results dict could race
  between the background worker thread and the API's read requests. Added
  a shared lock.
- **`weaver report` crash:** running it against an incomplete/still-running
  run directory threw a raw Python traceback instead of a clean error.
- **Backend 500s:** unhandled exceptions in GET endpoints didn't carry the
  `error_class`/trace-ID contract every other error type does. Added a
  catch-all handler.
- **A test that wasn't checking what it claimed to:** the AC-10 acceptance
  test (UNKNOWN classifications ≤ 15%) was only checking a 50-entry capped
  sample instead of the real 132-divergence population. Rewritten to
  recompute the full set independently.
- **Report-line encoding gap closed:** the Java code generator could only
  emit COBOL's "floating sign" money-style edit mask (`-(n)9.99`). Added
  support for plain zero-padded unsigned fields (`PIC 9(n)`) too
  (`Field.edit_style`, `CobolEdit.zeroPadded`).

Full findings and rationale are in the conversation history / commit
message on `f314f9a` if you want the details.

---

## 3. Four new COBOL fixture programs

To prove the migration pipeline generalizes beyond `interest.cob` and
`feecalc.cob`, we added four more programs, each exercising a genuinely
different control-flow shape (not just different field names):

| Program | Shape | What it tests |
|---|---|---|
| `taxcalc.cob` | Nested `IF/ELSE` bracket ladder | Multi-level branching, unlike interest.cob's single 88-level check or feecalc's flat `EVALUATE` |
| `tieraccum.cob` | In-paragraph `PERFORM VARYING` loop | A loop *inside* the synthesis unit itself — every other program's only loop is the scaffold's outer per-record loop |
| `compound.cob` | Straight-line arithmetic, no branching/looping at all | Chained truncation across sequential `COMPUTE` statements |
| `shipcost.cob` | `EVALUATE TRUE` with compound `AND` conditions across two fields | A single `WHEN` clause referencing more than one field at once |

Each one has: COBOL source + copybook, a real GnuCOBOL-produced golden
output, a Python field-layout module, a `ScaffoldSpec`, and a
hand-verified reference Java implementation (confirmed to produce zero
divergences against the golden output before being trusted as "correct").

All four work with `weaver verify` today. `weaver migrate` (full autonomous
synthesis) works on some of them; where it doesn't, that's a local-model
capability limit, not an infrastructure gap — the pipeline correctly detects
and reports the failure rather than producing wrong output.

Try one:
```bash
weaver verify fixtures/cobol_taxcalc/taxcalc.cob <your_candidate.java> fixtures/data_taxcalc/tax.dat
```

Documented as "Phase U" in `docs/specs/AGENT_LAYER_PLAN.md`.

---

## Test coverage

68 tests passing (up from 60), covering the RunSpec parameter-threading fix
and both new candidate-supplied-mode code paths (correct candidate commits
clean, broken candidate escalates, multi-unit programs reject cleanly).
