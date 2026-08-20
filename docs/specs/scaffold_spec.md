# Generated class shape — Step K1

**Status:** written, per AGENT_LAYER_PLAN.md Step K1. Reviewed by re-reading
against `weaver/layout.py` (INPUT_LAYOUT, REPORT_LAYOUT, TOTALS_LAYOUT) and
`fixtures/cobol/interest.cob` before implementation (Step K2).

**Scope note.** This spec describes the shape generated for the INTEREST
fixture (and, in Phase S, FEECALC — a second program sharing the same
generation rules but its own field table). It is driven by the field table,
not by parsing arbitrary COBOL.

**Amended 2026-08-12 (Phase V).** This note previously read that building a
general-purpose COBOL-to-scaffold compiler was out of scope, because
`AGENT_LAYER_PLAN.md` asks only for a scaffold generated *from the field
table*. That remains true of the generator and is unchanged: `scaffold.py`
reads a `ScaffoldSpec` and never COBOL text. What changed is where the field
table comes from — `weaver/cobol/` parses the DATA DIVISION and produces it,
so the spec is derived per program rather than hand-declared. The scope
limit that survives is narrower and enforced by raising, not by convention:
one output file, DISPLAY usage only, no `OCCURS` / `RENAMES` /
`COPY REPLACING`, and exactly one synthesis unit per program.

**Amended 2026-08-21 (Phase BB1).** "One input file" widened to "one or
more input files, read in lockstep by position" — a program may `OPEN
INPUT` more than one file as long as its driving paragraph `READ`s each
exactly once per loop iteration (no keyed match/merge; see
`weaver/agent/scaffold.py`'s `ScaffoldSpec.extra_input_files` comment for
the exact subshape and why it stops short of a general COBOL MERGE). Every
program with exactly one input file — every fixture before this phase —
takes the identical code path it always has; this is additive, not a
relaxation of the single-input-file contract for programs that still have
one. Output-file count, `OCCURS`/`RENAMES`/`COPY REPLACING`, and the
one-synthesis-unit-per-program limit are unchanged (see `tasks.md`'s
Phase BB row for BB2/BB3/BB4, the not-yet-built further widenings).

## 1. Record type per 01-level group

- `AccountRecord` — one component per `INPUT_LAYOUT` field that is not a
  `REDEFINES` target. Every numeric field is `java.math.BigDecimal` at the
  scale implied by `decimal_scale`. Non-numeric fields are `String`. No
  `double`/`float` anywhere.
- `ReportLine` — one component per `REPORT_LAYOUT` field (the 200 detail
  lines).
- `TotalsLine` — one component per `TOTALS_LAYOUT` field (the 201st line).

## 2. Decoder

`AccountRecord.decode(String line)` slices the fixed-width input line using
the byte offsets in `INPUT_LAYOUT`:

- A field with `trailing_separate_sign=True` reads its digit run plus the
  separate `+`/`-` byte immediately following, and produces a signed
  `BigDecimal` at `decimal_scale`.
- A field with `redefines` set (`AR-DORMANT`, `AR-HOLD`) is **not** a
  separate decoded component. It is a second accessor
  (`AccountRecord.dormant()`, `AccountRecord.hold()`) that re-slices the
  *same* underlying raw flag bytes stored for its `redefines` target
  (`AR-FLAGS`) — never appended bytes, per the K2 common-failure warning.
- 88-level condition names become boolean accessor methods on the record:
  `isPremium()`, `isDormant()`, `isHold()` — evaluated against the parent
  field's value, never as ad hoc string comparisons in paragraph bodies.

## 3. Encoder

`ReportLine.encode()` / `TotalsLine.encode()` reproduce the declared numeric
edit mask (`-(n)9.99` style: `n` floating sign positions, one mandatory
integer digit, decimal point, `decimal_scale` fraction digits) generically
from `(width, decimal_scale)`: integer capacity = `width - 1 - decimal_scale`.
Floating-sign rule: leading zero digits are blanked to spaces; the position
immediately before the first significant (or mandatory) digit holds `-` if
the value is negative, else a space. This is derived once in
`weaver/agent/cobol_edit.py` and reused by both encoder methods — not
duplicated per field.

## 4. Working-storage holder

`WorkingStorage` — one mutable field per `WORKING-STORAGE SECTION` item that
survives across records: `appliedRate` (scale 5), `interest` (scale 2),
`totalInterest` (scale 2, accumulator). `BigDecimal`, exact decimal only.

## 5. Paragraph stub

One method per COBOL paragraph that is not pure control flow. For this
fixture that is `PROCESS-RECORD` only — `MAIN-PARA` is the read/write driving
loop, which is control flow and is emitted directly into `main()` (§6), not
as a model-synthesized unit.

Uniform signature:

```java
static void processRecord(AccountRecord ar, WorkingStorage ws)
```

The scaffold stub throws `UnsupportedOperationException("PROCESS-RECORD not yet synthesized")`.
Marked with substitution markers so synthesis/repair can swap the body
without touching anything else:

```java
// PARAGRAPH:PROCESS-RECORD:BEGIN
...
// PARAGRAPH:PROCESS-RECORD:END
```

## 6. Main loop

`main()` opens `accounts.dat`, iterates fixed-width lines (skipping blanks),
decodes each into `AccountRecord`, calls `processRecord`, builds a
`ReportLine` from the record plus `ws.interest`, accumulates
`ws.totalInterest`, and after the loop writes one `TotalsLine`. This mirrors
`MAIN-PARA`'s `PERFORM UNTIL WS-EOF` / `WRITE REPORT-LINE` / final
`WRITE TOTALS-LINE`, generated deterministically — no model involvement.

## Review

Every `INPUT_LAYOUT` field maps to exactly one `AccountRecord` component or
`REDEFINES` accessor. Every non-control-flow paragraph (`PROCESS-RECORD`)
maps to exactly one stub. Reviewed against `weaver/layout.py` current
content on 2026-08-07.
