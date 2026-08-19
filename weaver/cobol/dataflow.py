"""Per-paragraph read/write field-set extraction — GRAPH_PLAN.md M2.

Fulfils SRS FR-1.5 (data-flow analysis), previously unimplemented and
degrading to "pass the whole field table as context." Scope, per
GRAPH_PLAN.md §4: MOVE, ADD, COMPUTE, and IF/EVALUATE conditions only.
File I/O (READ/WRITE/OPEN) is procedure.py's job; paragraph-to-paragraph
control flow (PERFORM/CALL) is callgraph.py's (M1) -- this module answers
only "which fields does this paragraph's own business logic read and
write."

Deliberately does not split on periods the way `weaver.cobol.source
.statements()` does (that module's job is DATA DIVISION descriptions,
which are reliably period-terminated). Structured PROCEDURE DIVISION code
using scope terminators (END-IF, END-EVALUATE) instead of a period after
every clause -- exactly the style `fixtures/cobol/interest.cob` uses for
its IF/ELSE/END-IF blocks -- would otherwise collapse an entire paragraph
into one period-delimited blob, letting statements the module has no
business reading (WRITE, in interest.cob's case) leak into the read set.
Instead this scans for the *next* occurrence of any recognized keyword
(verb or terminator) to bound each clause, which works whether or not a
period is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENT_RE = re.compile(r"[A-Z][A-Z0-9-]*")
_NUMBER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_QUOTED_RE = re.compile(r"\"[^\"]*\"|'[^']*'")

_FIGURATIVE_CONSTANTS = {
    "ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES",
    "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES",
}
_RESERVED_WORDS = {
    "MOVE", "TO", "ADD", "SUBTRACT", "FROM", "GIVING", "COMPUTE", "ROUNDED",
    "IF", "ELSE", "END-IF", "THEN", "EVALUATE", "WHEN", "OTHER", "END-EVALUATE",
    "TRUE", "FALSE", "AND", "OR", "NOT", "IS", "ARE",
}

# Every keyword that can start a clause this module reads (MOVE/ADD/COMPUTE/
# IF/WHEN) or that ends one without a period (ELSE/END-IF/END-EVALUATE/next
# verb/PERFORM/WRITE/...). A clause runs from one boundary keyword up to
# the next, regardless of periods.
_BOUNDARY_RE = re.compile(
    r"\b(MOVE|ADD|SUBTRACT|MULTIPLY|DIVIDE|COMPUTE|IF|ELSE|WHEN|EVALUATE|"
    r"END-IF|END-EVALUATE|PERFORM|END-PERFORM|WRITE|READ|END-READ|OPEN|CLOSE|STOP)\b",
    re.IGNORECASE,
)
_CLAUSE_VERBS = {"MOVE", "ADD", "COMPUTE", "IF", "WHEN"}


@dataclass(frozen=True)
class ReadWriteSet:
    paragraph_id: str
    reads: frozenset[str]
    writes: frozenset[str]


def _identifiers(text: str) -> list[str]:
    text = _QUOTED_RE.sub(" ", text)  # literals are never field references
    out = []
    for tok in _IDENT_RE.findall(text.upper()):
        if tok in _RESERVED_WORDS or tok in _FIGURATIVE_CONSTANTS:
            continue
        if _NUMBER_RE.match(tok):
            continue
        out.append(tok)
    return out


def _is_field_token(tok: str) -> bool:
    return tok.upper() not in _FIGURATIVE_CONSTANTS and not _NUMBER_RE.match(tok)


def _handle_move(clause: str, reads: set[str], writes: set[str]) -> None:
    # MOVE <source> TO <target1> [<target2> ...]
    m = re.match(r"MOVE\s+(\S+)\s+TO\s+(.+)$", clause, re.IGNORECASE)
    if not m:
        return
    source, targets_text = m.group(1), m.group(2)
    if _is_field_token(source):
        reads.update(_identifiers(source))
    writes.update(_identifiers(targets_text))


def _handle_add(clause: str, reads: set[str], writes: set[str]) -> None:
    # ADD <a> [<a2> ...] TO <b> [GIVING <c>]
    m = re.match(r"ADD\s+(.+?)\s+TO\s+(\S+)(?:\s+GIVING\s+(\S+))?$", clause, re.IGNORECASE)
    if not m:
        return
    addends, target, giving = m.group(1), m.group(2), m.group(3)
    reads.update(_identifiers(addends))
    reads.update(_identifiers(target))
    writes.update(_identifiers(giving) if giving else _identifiers(target))


def _handle_compute(clause: str, reads: set[str], writes: set[str]) -> None:
    # COMPUTE <target> [ROUNDED] = <expression>
    m = re.match(r"COMPUTE\s+(\S+)(?:\s+ROUNDED)?\s*=\s*(.+)$", clause, re.IGNORECASE)
    if not m:
        return
    target, expr = m.group(1), m.group(2)
    writes.update(_identifiers(target))
    reads.update(_identifiers(expr))


def _handle_condition(clause: str, reads: set[str]) -> None:
    # IF <condition> / WHEN <condition>
    m = re.match(r"(?:IF|WHEN)\s+(.+)$", clause, re.IGNORECASE)
    if not m:
        return
    reads.update(_identifiers(m.group(1)))


_HANDLERS = {
    "MOVE": _handle_move,
    "ADD": _handle_add,
    "COMPUTE": _handle_compute,
}


def read_write_set(paragraph_id: str, paragraph_text: str) -> ReadWriteSet:
    """The set of fields `paragraph_id`'s own logic reads and writes,
    scoped to MOVE/ADD/COMPUTE/IF/EVALUATE per GRAPH_PLAN.md §4."""
    reads: set[str] = set()
    writes: set[str] = set()

    boundaries = list(_BOUNDARY_RE.finditer(paragraph_text))
    for i, m in enumerate(boundaries):
        verb = m.group(1).upper()
        if verb not in _CLAUSE_VERBS:
            continue
        end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(paragraph_text)
        clause = paragraph_text[m.start():end].strip().rstrip(".")

        if verb in _HANDLERS:
            _HANDLERS[verb](clause, reads, writes)
        else:  # IF / WHEN
            _handle_condition(clause, reads)

    return ReadWriteSet(paragraph_id, frozenset(reads), frozenset(writes))
