# Walkthrough

A step-by-step run through LegacyWeaver's CLI, from a clean checkout to a
verified (or repaired) migration. Every number and file path below is
reproducible on your own machine — nothing here is illustrative.

## 0. Prerequisites

- GnuCOBOL 3.x (`cobc`) — 2.x silently produces different arithmetic and
  invalidates the golden output.
- JDK 17+ (`java`, `javac`)
- Python 3.11+
- [Ollama](https://ollama.com) running locally, only if you want to run the
  autonomous agent (`weaver migrate`). `weaver verify` needs none of this.

On Windows, GnuCOBOL is only practical via WSL2 — run the commands below
from a Linux or WSL2 Ubuntu shell.

## 1. Install and generate fixture data

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements.txt        # add ".[backend]" if you also want the API

python fixtures/generate_data.py fixtures/data/accounts.dat
```

`generate_data.py` writes 200 fixed-width account records
(39 bytes each) covering every code path the oracle exercises: ordinary,
premium, dormant, and negative-balance accounts, plus boundary values at
each field's magnitude limit.

## 2. Verify a candidate against the COBOL oracle

```bash
weaver verify fixtures/cobol/interest.cob baseline/Baseline.java fixtures/data/accounts.dat --report report.json
```

or, in the `--cobol/--java/--data` flag form (§3.9.1):

```bash
weaver verify --cobol fixtures/cobol/interest.cob --java baseline/Baseline.java --data fixtures/data/accounts.dat --report report.json
```

What happens:

1. `cobc` compiles the COBOL source to a native binary (skipped if already
   built and newer than the source).
2. `javac` compiles the Java candidate the same way.
3. Both run against the same 200-record input file.
4. Every output byte is compared — no tolerance, no heuristic, no model.
5. Any divergence is classified deterministically: `PADDING`, `SIGN`,
   `SCALE`, `TRUNCATION`, `CONTROL_FLOW`, or `UNKNOWN`, most-specific rule
   first.
6. A summary table prints to the terminal; the full detail goes to
   `report.json`.

Against the repo's own deliberately-flawed `baseline/Baseline.java`, expect:

```
Records compared: 201 (200 detail + 1 totals)
Divergences:      132
  TRUNCATION   72 (54.5%)
  SIGN         28 (21.2%)
  CONTROL_FLOW 25 (18.9%)
  UNKNOWN       7 (5.3%)
Exit status: 1
```

Exit status `1` means at least one byte differed — that's expected here,
since the baseline exists specifically to have planted defects for the
harness to catch (see the header comment in `baseline/Baseline.java` for
the full, honest list of what's wrong with it on purpose).

Run it again with the golden output against itself and you get **0**
divergences — the self-comparison check that proves the harness has no
false positives.

## 3. Let the agent migrate a program from scratch

This is the part that doesn't need a hand-written Java candidate at all.
With Ollama running (`ollama serve`, with `qwen2.5-coder:7b` and
`nomic-embed-text` pulled):

```bash
weaver migrate fixtures/cobol/interest.cob --data fixtures/data/accounts.dat
```

What happens, unit by unit:

1. A deterministic scaffold is generated directly from the COBOL structure
   (record layout, working-storage, control flow skeleton) — no model
   involved yet.
2. The local model synthesizes the body of each unresolved unit.
3. Each synthesized unit is verified against the oracle using the exact
   same byte-for-byte comparison as `weaver verify`.
4. If a unit fails, the orchestrator checks failure memory first — has this
   *kind* of defect been seen and fixed before? If so, it applies the known
   patch. If not, it enters a repair loop: re-prompt with the verifier's own
   divergence output, re-verify, repeat up to `--max-repairs` (default 3).
5. A unit that still doesn't verify after all repair attempts escalates
   (recorded, not silently dropped) and the run continues to the next unit.

Status streams to the terminal with colour coding as each unit resolves —
green for verified, yellow for repairing, red for escalated. Ctrl-C stops
cleanly at the next unit boundary rather than mid-unit.

Useful flags:

```
--copybook DIR      copybook directory
--out DIR           output directory for generated Java
--max-repairs 3      repair attempts per unit before escalating
--model TAG          local inference model (default qwen2.5-coder:7b)
--seed 42            inference seed, for reproducible synthesis
--replay              serve model responses exclusively from cache (no live inference)
```

Exit codes: `0` every unit committed and verified, `1` at least one unit
escalated, `130` the run was cancelled.

## 4. Read back a run's results

Every `weaver migrate` run writes `runs/<run_id>/`, containing
`params.json` (the exact spec the run used), `trace.jsonl` (one event per
unit transition), and `orchestrator_state.json` (final per-unit status).

```bash
weaver report runs/<run_id>
```

This computes metrics from that same trace/state pair using the identical
code path the local run service's `GET /runs/{id}` endpoint calls — the
two are byte-identical by test (`tests/test_backend_service.py`), so the
number you see in a browser and the number `weaver report` prints can never
disagree.

## 5. What's not implemented yet

Stated plainly, per CLAUDE.md rule 12 (scope stays disclosed):

- `weaver baseline <program.cbl>` (FR-8.3) — single-shot whole-program
  translation with no verification, meant to quantify the harness's
  contribution by comparison. Not built.
- `weaver replay <run_id>` (FR-8.4) — the `--replay` *flag* on `migrate`
  works today; the standalone command that replays a previously recorded
  run by id does not exist yet.
- `weaver memory list | export | import <file>` (§3.9.1) — `FailureMemory`
  exists and is used internally by the repair loop; it has no CLI surface.
- Sandboxed execution (§3.9.3 / NFR-S1) — generated code currently compiles
  and runs on the host, not inside a `--network=none --read-only` container
  as the spec requires. This is the largest outstanding gap.

Don't infer these work from the presence of related code (e.g.
`generated/m4_baseline.json`) — until a command has its own passing
acceptance test, it isn't there.
