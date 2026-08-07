# LegacyWeaver MVP

**The compiled legacy binary is the specification; we verify translations against it automatically.**

> Status: scaffolding only. See "Not yet implemented" below and the checklist
> in [docs/specs/MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md).

## Results

*To be filled in after Step D5/E3 — copy numbers from the committed JSON
report, never from memory (Step H3).*

| Records compared | Divergences found | Breakdown by cause | False positives | Human review required |
|---|---|---|---|---|
| TBD | TBD | TBD | TBD | TBD |

## Reproduction

Prerequisites (SRS §2.4): GnuCOBOL 3.x (`cobc`), JDK 17+ (`java`, `javac`), Python 3.11+.

```bash
python -m venv .venv
source .venv/Scripts/activate   # or .venv/bin/activate on Linux/macOS
pip install -e .

# TODO once fixtures exist:
# cobc -x -o fixtures/cobol/build/interest fixtures/cobol/interest.cob \
#      -I fixtures/cobol/copybooks
# python fixtures/generate_data.py fixtures/data/accounts.dat
# javac -d baseline/build baseline/Baseline.java
# weaver verify fixtures/cobol/interest.cob baseline/Baseline.java fixtures/data/accounts.dat
```

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
                    Perceive / Plan / Repair / Memory   <- full system, not MVP
```

## Repository layout

| Path | Contents |
|---|---|
| `fixtures/` | COBOL oracle source, copybooks, generated input, golden output |
| `baseline/` | Deliberately unconstrained Java translation (control arm) |
| `weaver/` | The verification harness (execution, comparison, classification, CLI) |
| `tests/` | Unit tests for the harness |
| `docs/specs/` | MVP SRS and implementation runbook |
| `docs/screenshots/` | Demonstration screenshots |

## Not yet implemented

Per the full LegacyWeaver SRS ([docs/specs/MVP_SRS.md](docs/specs/MVP_SRS.md) §2.5),
this MVP implements only the **Verify** stage. The following are explicitly
out of scope here:

- COBOL parsing, paragraph segmentation, dependency planning (Perceive/Plan)
- Java code synthesis
- Any language model invocation
- Autonomous repair loop, failure memory, escalation
- Container sandboxing for untrusted candidate execution
- CICS, DB2, IMS, VSAM, JCL, inter-program `CALL`

## Specifications

- [docs/specs/MVP_SRS.md](docs/specs/MVP_SRS.md)
- [docs/specs/MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md)
