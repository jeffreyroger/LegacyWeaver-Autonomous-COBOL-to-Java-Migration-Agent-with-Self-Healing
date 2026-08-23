# LegacyWeaver

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![GnuCOBOL 3.x](https://img.shields.io/badge/GnuCOBOL-3.x-informational)](docs/specs/MVP_SRS.md)
[![Tests](https://img.shields.io/badge/tests-60%20passed%2C%201%20skipped-brightgreen)](tests/)
[![Offline](https://img.shields.io/badge/inference-local%20only%2C%20no%20cloud-lightgrey)](CLAUDE.md)

**Autonomous COBOL → Java migration, verified against the compiled legacy binary — not against a human's reading of it.**

LegacyWeaver treats the running COBOL program as ground truth. It compiles and executes the original alongside a Java candidate on identical input, compares every output byte, classifies any divergence by root cause, and — where a local model is available — drives a repair loop that fixes the candidate and re-verifies, with failed attempts remembered so the same mistake isn't retried.

No cloud dependency, no partial-credit scoring, no human reading two files side by side and guessing whether they match. A translation is either byte-identical to the oracle or it isn't, and the tool tells you exactly why not.

## Contents

- [What it does](#what-it-does)
- [Results](#results)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Status &amp; roadmap](#status--roadmap)
- [Repository layout](#repository-layout)
- [Design principles](#design-principles)
- [Specifications](#specifications)
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

Every number below is read directly from a committed report — see
[docs/screenshots/report.json](docs/screenshots/report.json) and
[docs/screenshots/verify_run.txt](docs/screenshots/verify_run.txt) for the
full run this table was copied from.

| Records compared | Divergences found | Breakdown by cause | False positives | Human review required |
|---|---|---|---|---|
| 201 (200 detail + 1 totals) | 132 | TRUNCATION 72 (54.5%), SIGN 28 (21.2%), CONTROL_FLOW 25 (18.9%), UNKNOWN 7 (5.3%) | 0 (self-comparison of golden output against itself: 0 divergences) | 7 records (UNKNOWN class) |

Golden output checksum: `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`
(`fixtures/data/expected/golden_interest.out.sha256`) — stable across 10
consecutive oracle runs.

Oracle independently hand-verified on 5 records spanning every logic path
(ordinary, premium, dormant, negative-balance, boundary) —
[docs/specs/oracle_hand_verification.md](docs/specs/oracle_hand_verification.md).

<details>
<summary>Note on numbers vs. the original runbook</summary>

This repo's oracle, generator, and baseline were built independently from
the governing spec's encoding rules — the original authors' fixture and
generator source was not available, only their description of it. The
measured numbers above (checksum, 132 divergences) are this repo's own
reproducible values; they replace the runbook's illustrative reference
values (checksum `149ff767b1...`, "113 divergences"), which this repo
cannot regenerate without that source. See [CLAUDE.md](CLAUDE.md) for the
full accounting of this substitution.

</details>

## Quickstart

Prerequisites: GnuCOBOL 3.x (`cobc`), JDK 17+ (`java`, `javac`), Python 3.11+.
On Windows, GnuCOBOL is only practical via WSL2 — the commands below assume
a Linux or WSL2 Ubuntu shell.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements.txt   # or: pip install -e ".[backend]" for API-only

python fixtures/generate_data.py fixtures/data/accounts.dat
weaver verify fixtures/cobol/interest.cob baseline/Baseline.java fixtures/data/accounts.dat --report report.json
```

`weaver verify` compiles both the oracle (`cobc`) and the candidate
(`javac`) automatically if their binaries are missing or stale, then runs
the full compare/classify/report pipeline. Expect divergence count **132**
and exit status **1** against the committed baseline (it's deliberately
wrong — see `baseline/Baseline.java`'s header for the planted defects).

### Running the agent

With [Ollama](https://ollama.com) running locally:

```bash
weaver migrate fixtures/cobol/interest.cob --data fixtures/data/accounts.dat
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
--model TAG         local inference model (default granite-code:20b)
--seed 42           inference seed
--replay            serve model responses exclusively from cache
--use-text-refinement   opt-in hosted gpt-4o-mini refinement pass after synthesis (requires OPENAI_API_KEY)
--use-delta-debugging   opt-in ddmin-based minimal counterexample selection during repair
```

Each run writes `runs/<run_id>/` containing `params.json`, `trace.jsonl`,
and `orchestrator_state.json`. Read its metrics back with:

```bash
weaver report runs/<run_id>
```

That is the same object the local run service serves from `GET /runs/{id}` —
byte-identical by test, so no number depends on which surface you read it from.

Exit codes: `0` all units committed, `1` at least one unit escalated,
`130` cancelled.

**Not yet implemented:** `weaver baseline` (FR-8.3), `weaver replay <run_id>`
(FR-8.4 — the `--replay` flag on `migrate` works; the standalone command does
not), and `weaver memory list|export|import` (§3.9.1). Generated code is
compiled and executed on the host, not in the containers §3.9.3/NFR-S1
require.

### Running the tests

```bash
python -m pytest tests/ -v
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
| 1 | Verification core (`weaver verify`) — compile, execute, compare, classify | **Complete** — blocking gates AC-2/AC-3/AC-9/AC-12 passed |
| 2 | Agent layer (`weaver migrate`) — scaffold, synthesis, repair loop, failure memory, orchestrator | **Complete** — see build order in [AGENT_LAYER_PLAN.md](docs/specs/AGENT_LAYER_PLAN.md) |
| 3 | Local run service (`backend/`) — loopback HTTP API, SSE trace streaming | **In progress** — `weaver report` / `GET /runs/{id}` parity is tested and passing; web trace UI is a **[SHOULD]**, not required |

Known gaps, tracked rather than hidden (CLAUDE.md rule 12 — scope stays disclosed):

- `weaver baseline <program.cbl>` (FR-8.3) — not implemented
- `weaver replay <run_id>` as a standalone command (FR-8.4) — not implemented; the `--replay` *flag* on `migrate` works today
- `weaver memory list | export | import` (§3.9.1) — not implemented; `FailureMemory` exists internally with no CLI surface
- Sandboxed execution of generated code (§3.9.3 / NFR-S1) — generated Java currently compiles and runs on the host, not inside a `--network=none --read-only` container
- COBOL frontend scope (Phase V) — `weaver/cobol/` derives layouts, condition names, working-storage tables, file names and main-loop wiring from source, replacing the hand-written per-program tables. It **raises rather than guesses** outside its declared scope: one input and one output file, DISPLAY usage only, no `OCCURS` / `RENAMES` / `COPY REPLACING`, exactly one synthesis unit per program
- `tieraccum` / `compound` scaffolds gain unused WorkingStorage fields under the frontend — it emits every numeric WORKING-STORAGE item, where the hand-written specs omitted scratch variables their reference bodies express as Java locals. Additive, not a behaviour change; regenerating those two scaffolds changes their prompt hashes

See [walkthrough.md](walkthrough.md) for a full run-through of what's implemented today, end to end.

## Repository layout

| Path | Contents |
|---|---|
| `fixtures/` | COBOL oracle source, copybooks, generated input, golden output |
| `baseline/` | Deliberately unconstrained Java translation (control arm) |
| `weaver/` | The verification harness (execution, comparison, classification, CLI) |
| `weaver/cobol/` | COBOL frontend: PICTURE parser, DATA DIVISION reader, program model (layouts, condition names, main-loop wiring) |
| `weaver/agent/` | Agent layer: local inference, deterministic scaffold, synthesis, repair loop, failure memory, orchestrator, escalation |
| `backend/` | Local, loopback-only HTTP service exposing agent run lifecycle and trace events to a browser (no domain logic — see [docs/specs/BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md)) |
| `tests/` | Unit tests for the harness, agent layer, and backend |
| `docs/specs/` | SRS and implementation plans for all three phases |
| `docs/screenshots/` | Demonstration screenshots |
| `generated/` | Run artifacts: model cache, failure memory, synthesized candidates |
| `requirements.txt` | Dependency list (mirrors `pyproject.toml`); use for quick `pip install -r` setup |

## Continuous migration (GitHub Actions)

`.github/workflows/migrate.yml` runs `weaver migrate` on any `.cob`/`.cbl`
file pushed under `input/`, and (per the orchestrator's own per-unit
verification) commits the result to `output/` only if it verifies. GitHub
runners have no local Ollama daemon, so this workflow is the one scoped
exception to "offline by default" below: it sets `WEAVER_INFERENCE_PROVIDER=groq`
and calls Groq's hosted API. **Before it will run, add a `GROQ_API_KEY` repo
secret** (Settings → Secrets and variables → Actions → New repository
secret). Local/CLI/backend/frontend usage is unaffected and stays offline.

## Design principles

1. **The compiled binary is the spec.** Not a document, not a person's memory of what the code does — the actual execution behavior of the actual COBOL, on the actual input.
2. **No partial credit.** Comparison is byte-for-byte with no tolerance, threshold, or heuristic, ever — that's the whole thesis, and it doesn't bend under pressure to make a demo number look better.
3. **Classification is deterministic.** Root-causing *why* two outputs diverge never touches a model — the same divergence always gets the same verdict.
4. **Everything the agent produces is independently checkable.** No result — from the CLI or from the local API — is trusted until `weaver verify` reproduces it byte-for-byte.
5. **Offline by default.** No network call, API key, or account at any point in a verification run; local inference only.

## Specifications

- [docs/specs/MVP_SRS.md](docs/specs/MVP_SRS.md) — core requirements and acceptance criteria
- [docs/specs/MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md) — verification core build order
- [docs/specs/AGENT_LAYER_PLAN.md](docs/specs/AGENT_LAYER_PLAN.md) — agent layer build order
- [docs/specs/BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md) — local run service build order
- [CLAUDE.md](CLAUDE.md) — binding working rules, hard constraints, and this repo's load-bearing numbers

## Contributing

This project follows the specs, not ad hoc judgment calls — before opening
a PR, read [CLAUDE.md](CLAUDE.md) and the plan document for whatever
phase your change touches
([MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md),
[AGENT_LAYER_PLAN.md](docs/specs/AGENT_LAYER_PLAN.md), or
[BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md)). A few rules that apply to
every change, not just some:

- The comparison contract (byte-for-byte, no tolerance) and the
  deterministic classification order are never relaxed, for any reason.
- Every acceptance test named in the relevant plan must pass before a step
  is considered done — they're the definition of done, not a checkpoint to
  skip under time pressure.
- Run `python -m pytest tests/ -v` before submitting; tests that need
  GnuCOBOL/JDK skip automatically if those toolchains aren't on `PATH`.
- Keep scope disclosed: don't let the README, `--help` text, or a docstring
  imply a command or feature works before it has its own passing
  acceptance test.

Open an issue for anything that looks like a spec gap rather than silently
working around it — most "judgment calls" turn out to already be answered
in the SRS.

## License

[MIT](LICENSE) © 2026 jeffreyroger
