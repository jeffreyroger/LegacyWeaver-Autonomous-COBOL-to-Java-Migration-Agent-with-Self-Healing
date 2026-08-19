"""Source instrumentation — GRAPH_PLAN.md M4.

Derives an instrumented COBOL source variant that DISPLAYs read-set field
values at paragraph entry and write-set field values at paragraph exit.
Purely additive text splicing: nothing here compiles anything or touches
the oracle source that produces golden output (Non-Negotiable Design
Decision 1, GRAPH_PLAN.md §1) -- that separation is the caller's job
(compile this function's output to a distinctly named binary, M5).

Practical simplification versus GRAPH_PLAN.md's literal wording ("given a
ProgramModel + ProgramGraph"): only paragraph boundaries (segment()'s
Paragraph list) and read/write sets (ProgramGraph.read_write_sets) are
needed to splice DISPLAY statements at entry/exit -- ProgramModel's other
fields (layouts, output filename, ...) are irrelevant to this transform.
"""

from __future__ import annotations

import re
from pathlib import Path

from weaver.agent.graph import ProgramGraph
from weaver.agent.segment import Paragraph
from weaver.cobol.source import expand_copy

_CONDITION_NAME_RE = re.compile(r"^\s*88\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE | re.MULTILINE)

TRACE_PREFIX = "WEAVER-TRACE:"
_DISPLAY_INDENT = " " * 11  # Area B (0-based col 11), matches this repo's fixture style
_CONTINUATION = "      -    \""  # cols 1-6 blank, col 7 '-', col 12 resumes the literal
_MAX_LINE = 72  # fixed-format COBOL: columns 8-72 are code; anything past 72 is silently dropped


def _display_line(paragraph_id: str, phase: str, field_name: str) -> list[str]:
    """One or more physical lines for a single DISPLAY statement, wrapped
    to respect fixed-format COBOL's 72-column limit.

    Found by actually compiling under GnuCOBOL (this environment's
    absence of `cobc` had let it through untested): a long paragraph/field
    name pushes `WEAVER-TRACE:<paragraph>:<phase>:<field>=` past column 72
    on a single unbroken line. GnuCOBOL doesn't error on this -- fixed
    format simply truncates the line at column 72, which silently drops
    the closing quote and the field-name operand, producing garbage
    identifiers on the *next* line ('WS-I' instead of 'WS-INTEREST') and a
    cascade of syntax errors. Long literals use COBOL's own continuation
    convention instead: `-` in column 7, with the resumed text starting at
    the next quote.
    """
    tag = f"{TRACE_PREFIX}{paragraph_id}:{phase}:{field_name}="
    prefix = f'{_DISPLAY_INDENT}DISPLAY "'
    suffix = f'" {field_name}.'

    single_line = f"{prefix}{tag}{suffix}"
    if len(single_line) <= _MAX_LINE:
        return [single_line]

    lines: list[str] = []
    budget = _MAX_LINE - len(prefix)
    chunk, remainder = tag[:budget], tag[budget:]
    lines.append(f"{prefix}{chunk}")
    # Whatever's left of the tag, plus the closing quote + operand + period
    # (`suffix`), still has to land somewhere -- even when `remainder` is
    # empty because the whole tag fit on line 1, the suffix on its own may
    # still not fit, and dropping it produces an unterminated string
    # literal GnuCOBOL rejects with "continuation character expected".
    tail = remainder + suffix
    while tail:
        budget = _MAX_LINE - len(_CONTINUATION)
        chunk, tail = tail[:budget], tail[budget:]
        lines.append(f"{_CONTINUATION}{chunk}")
    return lines


def _condition_names(source: str, copybook_dir: Path | None) -> set[str]:
    """88-level condition names declared anywhere in `source` -- including
    inside a COPYbook, since a 01-level record (and its 88-levels) is
    routinely declared there rather than inline (interest.cob's own
    AR-PREMIUM/AR-IS-DORMANT live in ACCOUNT-REC.cpy, not interest.cob
    itself). Uses weaver.cobol.source.expand_copy purely to widen what
    this scan can see; the source returned by instrument() below is never
    expanded -- the COPY statement is left exactly as written, since real
    GnuCOBOL resolves it at compile time the same way this repo's own
    oracle build already relies on.

    Found by actually compiling under GnuCOBOL: dataflow.py's read set
    correctly includes a condition name referenced by `IF AR-PREMIUM` (it
    genuinely is something PROCESS-RECORD's logic depends on -- SRS
    FR-1.5/FR-2.1 both want that captured in the graph). But a
    condition-name is a predicate over its parent field, not a data item
    with a value of its own; GnuCOBOL rejects `DISPLAY AR-PREMIUM` outright
    ('condition-name not allowed here'). Excluded from instrumentation
    only -- the graph itself still records the read.
    """
    try:
        expanded = expand_copy(source, copybook_dir)
    except FileNotFoundError:
        expanded = source  # best effort: scan what's inline if a copybook is missing
    return {m.group(1).upper() for m in _CONDITION_NAME_RE.finditer(expanded)}


def instrument(
    source: str, paragraphs: list[Paragraph], graph: ProgramGraph, *, copybook_dir: Path | None = None
) -> str:
    """Return a new COBOL source string with a DISPLAY trace spliced at
    each paragraph's entry (its read set) and exit (its write set). The
    input `source` is never modified in place; nothing is compiled here.
    `copybook_dir`, if given, only widens condition-name detection (see
    `_condition_names`) -- it never changes what's returned."""
    lines = source.splitlines()
    condition_names = _condition_names(source, copybook_dir)
    # 0-based line index -> lines to insert immediately after it.
    insertions: dict[int, list[str]] = {}

    for p in paragraphs:
        rw = graph.read_write_sets.get(p.identifier)
        if rw is None:
            continue
        header_idx = p.start_line - 1
        reads = sorted(f for f in rw.reads if f not in condition_names)
        entry_lines = [l for f in reads for l in _display_line(p.identifier, "ENTRY", f)]
        if entry_lines:
            insertions.setdefault(header_idx, []).extend(entry_lines)

        exit_idx = p.end_line - 1
        writes = sorted(f for f in rw.writes if f not in condition_names)
        exit_lines = [l for f in writes for l in _display_line(p.identifier, "EXIT", f)]
        if exit_lines:
            insertions.setdefault(exit_idx, []).extend(exit_lines)

    out = list(lines)
    for idx in sorted(insertions, reverse=True):
        for ins_line in reversed(insertions[idx]):
            out.insert(idx + 1, ins_line)
    return "\n".join(out) + "\n"
