# zuse

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![GnuCOBOL 3.x](https://img.shields.io/badge/GnuCOBOL-3.x-informational)](zuse-all.sh)
[![Tests](https://img.shields.io/badge/tests-see%20zuse%2Ftests-brightgreen)](zuse/tests/)
[![Offline](https://img.shields.io/badge/inference-local%20only%2C%20no%20cloud-lightgrey)](CLAUDE.md)

**Autonomous COBOL → Java migration, verified against the compiled legacy binary — not against a human's reading of it.**

zuse treats the running COBOL program as ground truth. It compiles and executes the original alongside a Java candidate on identical input, compares every output byte, classifies any divergence by root cause, and — where a local model is available — drives a repair loop that fixes the candidate and re-verifies, with failed attempts remembered so the same mistake isn't retried.

No cloud dependency, no partial-credit scoring, no human reading two files side by side and guessing whether they match. A translation is either byte-identical to the oracle or it isn't, and the tool tells you exactly why not.

## Contents

- [What it does](#what-it-does)
- [Results](#results)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Status &amp; roadmap](#status--roadmap)
- [Repository layout](#repository-layout)
- [Design principles](#design-principles)
- [Contributing](#contributing)
- [License](#license)

## What it does

- **Compiles and runs the real COBOL** (GnuCOBOL 3.x) as the oracle of record — the spec is whatever the binary actually does, not a document about what it's supposed to do.
- **Byte-for-byte comparison**, field-resolved against a data-driven layout table — no heuristics, tolerances, or thresholds anywhere in the pass/fail decision.
- **Deterministic root-cause classification** of every divergence (padding, sign, scale, truncation, control-flow, unknown) — no model in the classification path, so the same input always produces the same verdict.
- **Autonomous repair agent**: local LLM inference (Ollama, loopback-only), a deterministic scaffold, candidate synthesis, and a repair loop that iterates against the verifier's own output until a fix verifies or the agent escalates.
- **Failure memory**: repair attempts that didn't work are recorded so the orchestrator doesn't retry a dead end on the next run.
- **Local run service**: a loopback-only HTTP API that starts runs and streams trace events to a browser, with zero domain logic of its own — every value it returns is independently reproducible from the CLI.

## Results

| Records compared | Divergences found | Breakdown by cause | False positives | Human review required |
|---|---|---|---|---|
| 201 (200 detail + 1 totals) | 132 | TRUNCATION 72 (54.5%), SIGN 28 (21.2%), CONTROL_FLOW 25 (18.9%), UNKNOWN 7 (5.3%) | 0 (self-comparison of golden output against itself: 0 divergences) | 7 records (UNKNOWN class) |

Golden output reference: `zuse/examples/reference/interest.out`, checked
against `zuse/examples/reference/accounts.dat` and the deliberately-flawed
`zuse/examples/baseline/Baseline.java` (see its header for the planted defects).

## Quickstart

Prerequisites: GnuCOBOL 3.x (`cobc`), JDK 17+ (`java`, `javac`), Python 3.11+.
On Windows, GnuCOBOL is only practical via WSL2 — the commands below assume
a Linux or WSL2 Ubuntu shell.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements.txt   # or: pip install -e ".[backend]" for API-only

zuse verify zuse/examples/input/interest.cob zuse/examples/baseline/Baseline.java \
  zuse/examples/reference/accounts.dat --report report.json
```

`zuse verify` compiles both the oracle (`cobc`) and the candidate
(`javac`) automatically if their binaries are missing or stale, then runs
the full compare/classify/report pipeline. Expect divergence count **132**
and exit status **1** against the committed baseline (it's deliberately
wrong — see `zuse/examples/baseline/Baseline.java`'s header for the planted defects).

### Running the agent

With [Ollama](https://ollama.com) running locally:

```bash
zuse migrate zuse/examples/input/interest.cob --data zuse/examples/reference/accounts.dat
```

The orchestrator synthesizes a candidate, verifies it against the oracle,
and — if it doesn't verify — enters a repair loop, consulting failure
memory before each attempt so it doesn't retry a fix that's already known
not to work. Unit status streams with colour coding as the run proceeds,
and Ctrl-C stops cleanly at the next unit boundary.

```
--copybook DIR      copybook directory
--data FILE         input data file used for verification
--out DIR           output directory for generated Java
--max-repairs 3     repair attempts per unit
--model TAG         local inference model (default qwen2.5-coder:7b)
--seed 42           inference seed
--replay            serve model responses exclusively from cache
```

Each run writes `zuse/examples/generated/runs/<run_id>/` containing
`params.json`, `trace.jsonl`, and `orchestrator_state.json`. Read its
metrics back with:

```bash
zuse report zuse/examples/generated/runs/<run_id>
```

That is the same object the local run service serves from `GET /runs/{id}` —
byte-identical by test, so no number depends on which surface you read it from.

Exit codes: `0` all units committed, `1` at least one unit escalated,
`130` cancelled.

**Not yet implemented:** `zuse baseline` (FR-8.3), `zuse replay <run_id>`
(FR-8.4 — the `--replay` flag on `migrate` works; the standalone command does
not), and `zuse memory list|export|import` (§3.9.1). Generated code is
compiled and executed on the host, not in the containers §3.9.3/NFR-S1
require.

### Running the tests

```bash
python -m pytest zuse/tests/ -v
```

Tests that need the real GnuCOBOL/JDK toolchain (e.g.
`test_full_pipeline_against_real_fixture`) are skipped automatically if
`cobc`/`javac` aren't on `PATH` — the rest of the suite runs offline.

For a fuller step-by-step run, including what each command prints and
what's deliberately not implemented yet, see [walkthrough.md](walkthrough.md).

## Architecture

```
   COBOL source ─────┐
   Copybooks    ─────┤
   Input data   ─────┼──▶  ┌──────────────────────────┐
   Java candidate ───┘     │      Verification core    │
                           │                            │
                           │  compile oracle            │
                           │  compile candidate         │──▶ Divergence report (JSON)
                           │  execute both               │──▶ Summary table (terminal)
                           │  compare byte-for-byte      │──▶ Exit status
                           │  resolve to fields          │
                           │  classify defects           │
                           └──────────────────────────┘
                                       │
                                       ▼
                           ┌──────────────────────────┐
                           │   Agent layer              │
                           │  local inference (Ollama)  │
                           │  deterministic scaffold    │
                           │  synthesis + repair loop    │
                           │  failure memory             │
                           │  orchestrator + escalation │
                           └──────────────────────────┘
                                       │
                                       ▼
                           ┌──────────────────────────┐
                           │   Local run service        │
                           │  loopback-only HTTP API    │
                           │  run lifecycle + SSE trace  │
                           │  no domain logic (DC-4/5)  │
                           └──────────────────────────┘
```

The verification core and agent layer are complete and independently
verified. The local run service is under active development — its
contract is that every value it serves must be reproducible from the CLI,
never computed independently.

## Status &amp; roadmap

| Phase | Component | Status |
|---|---|---|
| 1 | Verification core (`zuse verify`) — compile, execute, compare, classify | **Complete** |
| 2 | Agent layer (`zuse migrate`) — scaffold, synthesis, repair loop, failure memory, orchestrator | **Complete** |
| 3 | Local run service (`backend/`) — loopback HTTP API, SSE trace streaming | **In progress** — `zuse report` / `GET /runs/{id}` parity is tested and passing; web trace UI is a **[SHOULD]**, not required |

Known gaps, tracked rather than hidden:

- `zuse baseline <program.cbl>` (FR-8.3) — not implemented
- `zuse replay <run_id>` as a standalone command (FR-8.4) — not implemented; the `--replay` *flag* on `migrate` works today
- `zuse memory list | export | import` (§3.9.1) — not implemented; `FailureMemory` exists internally with no CLI surface
- Sandboxed execution of generated code (§3.9.3 / NFR-S1) — generated Java currently compiles and runs on the host, not inside a `--network=none --read-only` container
- COBOL frontend scope — `zuse/cobol/` derives layouts, condition names, working-storage tables, file names and main-loop wiring from source. It **raises rather than guesses** outside its declared scope: one input and one output file, DISPLAY usage only, no `OCCURS` / `RENAMES` / `COPY REPLACING`, exactly one synthesis unit per program

See [walkthrough.md](walkthrough.md) for a full run-through of what's implemented today, end to end.

## Repository layout

| Path | Contents |
|---|---|
| `zuse/` | The verification harness (execution, comparison, classification, CLI) |
| `zuse/cobol/` | COBOL frontend: PICTURE parser, DATA DIVISION reader, program model (layouts, condition names, main-loop wiring) |
| `zuse/agent/` | Agent layer: local inference, deterministic scaffold, synthesis, repair loop, failure memory, orchestrator, escalation |
| `zuse/tests/` | Unit tests for the harness, agent layer, and backend |
| `zuse/examples/input/` | COBOL oracle source, copybooks, and input data |
| `zuse/examples/reference/`, `zuse/examples/reference_<program>/` | Hand-verified golden output and reference Java classes per program |
| `zuse/examples/baseline/` | Deliberately unconstrained Java translation (control arm) |
| `zuse/examples/generated/` | Run artifacts: model cache, failure memory, synthesized candidates, run history |
| `zuse/examples/output/` | Committed output of the CI migration workflow |
| `backend/` | Local, loopback-only HTTP service exposing agent run lifecycle and trace events to a browser (no domain logic) |
| `frontend/` | React console for driving/observing runs against the backend |
| `docs/` | Reserved for project documentation |
| `requirements.txt` | Dependency list (mirrors `pyproject.toml`); use for quick `pip install -r` setup |

## Continuous migration (GitHub Actions)

`.github/workflows/migrate.yml` runs `zuse migrate` on any `.cob`/`.cbl`
file pushed under `zuse/examples/input/`, and (per the orchestrator's own
per-unit verification) commits the result to `zuse/examples/output/` only
if it verifies. GitHub runners have no local Ollama daemon, so this
workflow is the one scoped exception to "offline by default" below: it
sets `ZUSE_INFERENCE_PROVIDER=groq` and calls Groq's hosted API. **Before
it will run, add a `GROQ_API_KEY` repo secret** (Settings → Secrets and
variables → Actions → New repository secret). Local/CLI/backend/frontend
usage is unaffected and stays offline.

## Design principles

1. **The compiled binary is the spec.** Not a document, not a person's memory of what the code does — the actual execution behavior of the actual COBOL, on the actual input.
2. **No partial credit.** Comparison is byte-for-byte with no tolerance, threshold, or heuristic, ever — that's the whole thesis, and it doesn't bend under pressure to make a demo number look better.
3. **Classification is deterministic.** Root-causing *why* two outputs diverge never touches a model — the same divergence always gets the same verdict.
4. **Everything the agent produces is independently checkable.** No result — from the CLI or from the local API — is trusted until `zuse verify` reproduces it byte-for-byte.
5. **Offline by default.** No network call, API key, or account at any point in a verification run; local inference only.

## Contributing

A few rules that apply to every change:

- The comparison contract (byte-for-byte, no tolerance) and the
  deterministic classification order are never relaxed, for any reason.
- Run `python -m pytest zuse/tests/ -v` before submitting; tests that need
  GnuCOBOL/JDK skip automatically if those toolchains aren't on `PATH`.
- Keep scope disclosed: don't let the README, `--help` text, or a docstring
  imply a command or feature works before it has its own passing test.

## License

[MIT](LICENSE) © 2026 jeffreyroger
