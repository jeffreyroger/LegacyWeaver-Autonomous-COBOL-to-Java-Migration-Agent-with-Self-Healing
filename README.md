# LegacyWeaver MVP

**The compiled legacy binary is the specification; we verify translations against it automatically.**

> Status: MVP Phase 1 (A–I, [docs/specs/MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md))
> is complete and independently verified. Agent layer Phase 2 (J–T,
> [docs/specs/AGENT_LAYER_PLAN.md](docs/specs/AGENT_LAYER_PLAN.md)) — local
> inference, deterministic scaffold, synthesis, repair loop, failure memory,
> orchestrator, escalation — is implemented in `weaver/agent/`. The local run
> service in `backend/` ([docs/specs/BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md))
> is in progress; its precondition is "MVP complete · agent layer complete."

## Results

Every number below is read directly from a committed report — see
[docs/screenshots/report.json](docs/screenshots/report.json) and
[docs/screenshots/verify_run.txt](docs/screenshots/verify_run.txt) for the
full run this table was copied from.

> **Note on numbers vs. the runbook:** this repo's oracle, generator, and
> baseline were built independently from the SRS's encoding rules — the
> original spec authors' fixture/generator source was not available, only
> their description of it. The measured numbers below (checksum, 132
> divergences) are this repo's own reproducible values; they replace the
> runbook's illustrative reference values (checksum `149ff767b1...`, "113
> divergences"), which this repo cannot regenerate without that source.
> See `CLAUDE.md` for the full accounting of this substitution.

| Records compared | Divergences found | Breakdown by cause | False positives | Human review required |
|---|---|---|---|---|
| 201 (200 detail + 1 totals) | 132 | TRUNCATION 72 (54.5%), SIGN 28 (21.2%), CONTROL_FLOW 25 (18.9%), UNKNOWN 7 (5.3%) | 0 (self-comparison of golden output against itself: 0 divergences) | 7 records (UNKNOWN class) |

Golden output checksum: `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`
(`fixtures/data/expected/golden_interest.out.sha256`) — stable across 10
consecutive oracle runs (Step B4).

Oracle independently hand-verified on 5 records spanning every logic path
(ordinary, premium, dormant, negative-balance, boundary) —
[docs/specs/oracle_hand_verification.md](docs/specs/oracle_hand_verification.md).

## Reproduction

Prerequisites (SRS §2.4): GnuCOBOL 3.x (`cobc`), JDK 17+ (`java`, `javac`),
Python 3.11+. On Windows, GnuCOBOL is only practical via WSL2 — the commands
below assume a Linux or WSL2 Ubuntu shell.

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
and exit status **1** (not verified — the baseline is deliberately wrong).

### Running the tests

```bash
python -m pytest tests/ -v
```

Tests that need the real GnuCOBOL/JDK toolchain (e.g.
`test_full_pipeline_against_real_fixture`) are skipped automatically if
`cobc`/`javac` aren't on `PATH` — the rest of the suite runs offline.

## Architecture

```
   COBOL source ─────┐
   Copybooks    ─────┤
   Input data   ─────┼──▶  ┌──────────────────────────┐
   Java candidate ───┘     │   LegacyWeaver Verify    │   <- implemented (MVP)
                           │                          │
                           │  compile oracle          │
                           │  compile candidate       │
                           │  execute both            │──▶ Divergence report (JSON)
                           │  compare byte-for-byte   │──▶ Summary table (terminal)
                           │  resolve to fields       │──▶ Exit status
                           │  classify defects        │
                           └──────────────────────────┘
                                       │
                                       ▼
                           ┌──────────────────────────┐
                           │   weaver/agent/           │   <- Phase 2 (agent layer)
                           │  local inference (Ollama) │
                           │  deterministic scaffold   │
                           │  synthesis + repair loop  │
                           │  failure memory           │
                           │  orchestrator + escalation│
                           └──────────────────────────┘
                                       │
                                       ▼
                           ┌──────────────────────────┐
                           │   backend/                │   <- Phase 3 (in progress)
                           │  loopback-only HTTP API   │
                           │  run lifecycle + SSE trace │
                           │  no domain logic (DC-4/5) │
                           └──────────────────────────┘
```

## Repository layout

| Path | Contents |
|---|---|
| `fixtures/` | COBOL oracle source, copybooks, generated input, golden output |
| `baseline/` | Deliberately unconstrained Java translation (control arm) |
| `weaver/` | The verification harness (execution, comparison, classification, CLI) |
| `weaver/agent/` | Agent layer: local inference, deterministic scaffold, synthesis, repair loop, failure memory, orchestrator, escalation |
| `backend/` | Local, loopback-only HTTP service exposing agent run lifecycle and trace events to a browser (no domain logic — see [docs/specs/BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md)) |
| `tests/` | Unit tests for the harness, agent layer, and backend |
| `docs/specs/` | SRS and implementation plans for all three phases |
| `docs/screenshots/` | Demonstration screenshots |
| `generated/` | Run artifacts: model cache, failure memory, synthesized candidates |
| `requirements.txt` | Pinned-free dependency list (mirrors `pyproject.toml`); use for quick `pip install -r` setup |


## Specifications

- [docs/specs/MVP_SRS.md](docs/specs/MVP_SRS.md) — MVP requirements and acceptance criteria
- [docs/specs/MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md) — MVP build order (phases A–I)
- [docs/specs/AGENT_LAYER_PLAN.md](docs/specs/AGENT_LAYER_PLAN.md) — agent layer build order (phases J–T)
- [docs/specs/BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md) — local run service build order
- [CLAUDE.md](CLAUDE.md) — binding working rules, hard constraints, and this repo's load-bearing numbers
