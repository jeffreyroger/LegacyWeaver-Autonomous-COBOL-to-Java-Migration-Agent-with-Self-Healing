"""PROCEDURE DIVISION surface scan — Steps U3 and U5.

Extracts only the *wiring* the scaffold's main loop needs and that was
previously hand-declared in a `ScaffoldSpec`:

  U3  which file is opened for input and which for output;
  U5  which field feeds each output-line field (`MOVE x TO RL-y`), and which
      working-storage item accumulates which per-record item (`ADD x TO y`).

This is emphatically not a reading of the business logic. Arithmetic — the
`COMPUTE`s, the tier `EVALUATE`, the truncation semantics — is never looked
at here; it remains the synthesis units' job. What is read is the data
plumbing between the record, working storage, and the report line, which is
mechanical and is exactly what the generated main loop has to reproduce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENT = r"[A-Z0-9][A-Z0-9-]*"
_LITERAL = r"\"[^\"]*\"|'[^']*'"
_NUMBER = r"[0-9]+(?:\.[0-9]+)?"

_MOVE_RE = re.compile(
    rf"\bMOVE\s+(?P<source>{_LITERAL}|{_NUMBER}|{_IDENT})\s+TO\s+(?P<target>{_IDENT})",
    re.IGNORECASE,
)
_ADD_RE = re.compile(
    rf"\bADD\s+(?P<source>{_IDENT})\s+TO\s+(?P<target>{_IDENT})",
    re.IGNORECASE,
)
_OPEN_RE = re.compile(
    rf"\bOPEN\s+(?P<mode>INPUT|OUTPUT|I-O|EXTEND)\s+(?P<file>{_IDENT})",
    re.IGNORECASE,
)
# (?<!-) blocks the false match inside "END-READ": \b alone treats the
# hyphen as a non-word character, so \bREAD would otherwise match "READ"
# starting right after "END-", pairing it with whatever token follows
# END-READ (e.g. a subsequent IF) as if it were a real READ statement.
_READ_RE = re.compile(rf"(?<!-)\bREAD\s+(?P<file>{_IDENT})", re.IGNORECASE)
# Phase BB4: single-argument DISPLAY <identifier> only -- a DISPLAY
# statement with a string literal, multiple arguments, or WITH NO
# ADVANCING is outside this scraper's declared scope (it exists only to
# identify which working-storage item a no-output-file program's summary
# line reports, not to model DISPLAY's full argument grammar).
# (?![A-Z0-9-]) blocks a false shorter match: a hyphen inside an
# identifier (e.g. WS-TOTAL) is a non-word character, so a plain \b would
# let the engine backtrack mid-identifier once the second lookahead below
# rejects the full match -- this one requires the captured arg to already
# be the WHOLE identifier, not a prefix of it, before the "no second
# argument follows" check ever runs.
_DISPLAY_RE = re.compile(
    rf"\bDISPLAY\s+(?P<arg>{_IDENT})(?![A-Z0-9-])(?!\s+{_IDENT})", re.IGNORECASE
)

FIGURATIVE_SPACE = ("SPACE", "SPACES")
FIGURATIVE_ZERO = ("ZERO", "ZEROS", "ZEROES")


@dataclass(frozen=True)
class Move:
    source: str
    target: str


@dataclass(frozen=True)
class Add:
    source: str
    target: str


def open_modes(procedure_text: str) -> dict[str, str]:
    """file name -> "INPUT" | "OUTPUT" | ...

    Read from OPEN rather than from FILE-CONTROL order, which carries no
    direction information.
    """
    return {
        m.group("file").upper(): m.group("mode").upper()
        for m in _OPEN_RE.finditer(procedure_text)
    }


def reads(procedure_text: str) -> list[str]:
    """Phase BB1: file names named by a `READ <file>` statement, in source
    order (duplicates kept -- a file read once per loop iteration appears
    once per `READ` statement in the driving paragraph's source, not once
    per file). Used to confirm every opened input file is actually read in
    the driving paragraph, the same lockstep-loop shape `_main_class`
    generates -- never to model per-iteration control flow itself."""
    return [m.group("file").upper() for m in _READ_RE.finditer(procedure_text)]


def displays(paragraph_text: str) -> list[str]:
    """Phase BB4: the single identifier argument of every single-argument
    `DISPLAY <identifier>` statement in `paragraph_text`, in source order.
    Used to identify which working-storage item a no-output-file
    program's driving paragraph reports as its final summary -- see
    `_DISPLAY_RE`'s own comment for the exact (deliberately narrow)
    subshape."""
    return [m.group("arg").upper() for m in _DISPLAY_RE.finditer(paragraph_text)]


def moves(paragraph_text: str) -> list[Move]:
    return [
        Move(m.group("source"), m.group("target").upper())
        for m in _MOVE_RE.finditer(paragraph_text)
    ]


def adds(paragraph_text: str) -> list[Add]:
    return [
        Add(m.group("source").upper(), m.group("target").upper())
        for m in _ADD_RE.finditer(paragraph_text)
    ]


def is_literal(token: str) -> bool:
    return token[:1] in ('"', "'")


def literal_text(token: str) -> str:
    return token[1:-1]
