"""PERFORM/CALL edge extraction — GRAPH_PLAN.md M1.

Extends `weaver/cobol/procedure.py`'s regex-scrape style (Move/Add) to the
two statement kinds that carry paragraph-to-paragraph and same-file
program-call relationships, neither of which weaver/cobol/ has extracted
before this: `PERFORM <paragraph> [THRU|THROUGH <paragraph>]` and
`CALL "<literal program name>"`.

`performs()` only ever reports an edge to a *known* paragraph identifier,
supplied by the caller (typically segment()'s output for the whole
program). This is what tells a real `PERFORM PROCESS-RECORD` apart from an
inline `PERFORM UNTIL ...` / `PERFORM VARYING ...` loop, which is not a
call to another paragraph at all -- its first token is a reserved word,
never a paragraph name, so it can never satisfy the known-identifier
filter.

`calls()` only reports a *literal* program name (`CALL "SUBPROG"`).
`CALL <identifier>` names a variable holding a dynamically resolved
program name -- GRAPH_PLAN.md's stated scope for this phase is same-file,
statically known relationships only, so a dynamic call target is skipped
rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENT = r"[A-Z0-9][A-Z0-9-]*"
_LITERAL = r"\"[^\"]*\"|'[^']*'"

_PERFORM_RE = re.compile(
    rf"\bPERFORM\s+(?P<target>{_IDENT})(?:\s+(?:THRU|THROUGH)\s+(?P<thru>{_IDENT}))?",
    re.IGNORECASE,
)
_CALL_RE = re.compile(rf"\bCALL\s+(?P<program>{_LITERAL})", re.IGNORECASE)

_PERFORM_KEYWORDS = {"UNTIL", "VARYING", "TIMES", "WITH", "TEST"}


@dataclass(frozen=True)
class Perform:
    target: str
    kind: str  # "SIMPLE" | "THRU"
    thru_target: str | None = None


@dataclass(frozen=True)
class Call:
    program: str


def performs(paragraph_text: str, known_paragraphs: set[str]) -> list[Perform]:
    """PERFORM edges out of `paragraph_text`, restricted to targets present
    in `known_paragraphs` -- see module docstring for why that filter is
    what tells a paragraph call apart from an inline PERFORM loop."""
    out: list[Perform] = []
    for m in _PERFORM_RE.finditer(paragraph_text):
        target = m.group("target").upper()
        if target in _PERFORM_KEYWORDS or target not in known_paragraphs:
            continue
        thru = m.group("thru")
        if thru is not None:
            thru = thru.upper()
            if thru not in known_paragraphs:
                continue
            out.append(Perform(target=target, kind="THRU", thru_target=thru))
        else:
            out.append(Perform(target=target, kind="SIMPLE"))
    return out


def calls(paragraph_text: str) -> list[Call]:
    """CALL edges with a literal program name. A dynamic (identifier)
    target is silently skipped -- see module docstring."""
    out: list[Call] = []
    for m in _CALL_RE.finditer(paragraph_text):
        program = m.group("program")
        if program[:1] in ('"', "'"):
            out.append(Call(program=program[1:-1]))
    return out
