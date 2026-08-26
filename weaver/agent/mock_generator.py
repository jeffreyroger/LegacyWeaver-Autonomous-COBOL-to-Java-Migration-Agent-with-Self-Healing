"""Deterministic COBOL/Java Mock Generator -- Phase Z1
(migration-framework-spec.md Section 2.1's "Dynamic Mocking").

This offline harness has no database or CICS region (CLAUDE.md rule 10) --
`EXEC SQL`/`EXEC CICS` can never be executed for real here. The spec's own
answer is a deterministic mock: every directive gets a canned value derived
once, non-randomly, from its own `MockDirective.signature` (Phase Z1's
`weaver/cobol/mock_directives.py`) via a SHA-256 digest -- not a real
database row, disclosed as synthetic mock data, but *deterministic*
synthetic data: the same directive always yields the same canned value on
both the oracle (rewritten COBOL) and candidate (Java) side, which is what
makes the Terminal State axis meaningful for a mocked run, and what makes
the External Stub Log axis meaningful (both sides emit the identical
signature string when they hit the same directive).

Source rewriting replaces each `EXEC SQL/CICS ... END-EXEC` block in-place
with a `MOVE <canned> TO <target>` and a `DISPLAY "STUB:<signature>"` --
ordinary, `cobc`-compilable COBOL, no SQL precompiler or CICS translator
needed. Paragraph-entry tracing (`DISPLAY "PARA:<name>"`) is inserted the
same way, for the Paragraphs Hit axis.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from weaver.cobol.mock_directives import MockDirective

_SQL_TARGET_RE = re.compile(r"INTO\s+:([A-Z0-9-]+)", re.IGNORECASE)
_CICS_TARGET_RE = re.compile(r"INTO\s*\(\s*([A-Z0-9-]+)\s*\)", re.IGNORECASE)


@dataclass(frozen=True)
class MockValue:
    kind: str    # "numeric" or "alnum"
    literal: str  # a valid COBOL literal for a MOVE statement (no surrounding quotes for numeric)


MockMap = dict[str, MockValue]


def _derive_numeric(signature: str) -> Decimal:
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    magnitude = int(digest[:6], 16) % 100000  # 0..99999 -> up to 3 integer + 2 decimal digits
    return Decimal(magnitude) / 100


def default_mock_map(directives: list[MockDirective], *, numeric: bool = True) -> MockMap:
    """One canned value per distinct `signature` -- same signature always
    maps to the same value, so re-generating this map from the same
    directives (oracle side and candidate side both call this) always
    agrees."""
    mock_map: MockMap = {}
    for directive in directives:
        if directive.signature in mock_map:
            continue
        if numeric:
            value = _derive_numeric(directive.signature)
            mock_map[directive.signature] = MockValue(kind="numeric", literal=f"{value:.2f}")
        else:
            digest = hashlib.sha256(directive.signature.encode("utf-8")).hexdigest()[:8].upper()
            mock_map[directive.signature] = MockValue(kind="alnum", literal=digest)
    return mock_map


def _target_field(directive: MockDirective) -> str | None:
    pattern = _SQL_TARGET_RE if directive.kind == "SQL" else _CICS_TARGET_RE
    match = pattern.search(directive.body)
    return match.group(1).upper() if match else None


def _replacement_statements(directive: MockDirective, mock_map: MockMap) -> list[str]:
    """Returns the replacement as SEPARATE statements, one per physical
    line -- fixed-format COBOL's column 72 line-length limit (GnuCOBOL's
    default) silently truncates a long MOVE+DISPLAY combined onto one
    line, which for a longer signature cuts a string literal mid-quote
    and fails to compile with a baffling 'continuation character
    expected' error one line further down. Never combine them again."""
    value = mock_map[directive.signature]
    target = _target_field(directive)
    literal = value.literal if value.kind == "numeric" else f'"{value.literal}"'
    statements = []
    if target:
        statements.append(f"MOVE {literal} TO {target}.")
    statements.append(f'DISPLAY "STUB:{directive.signature}".')
    return statements


def rewrite_cobol_source(source: str, directives: list[MockDirective], mock_map: MockMap,
                          paragraph_names: list[str] | None = None) -> str:
    """Returns `source` with every EXEC SQL/CICS block replaced by its
    mock MOVE+DISPLAY (Terminal State + External Stub Log), and, if
    `paragraph_names` is given, a `DISPLAY "PARA:<name>"` inserted right
    after each named paragraph's header line (Paragraphs Hit). Splices by
    exact original directive/paragraph text, not by line offset, so it is
    correct regardless of surrounding whitespace/indentation."""
    lines = source.splitlines(keepends=True)

    directives_by_line = {d.line_number: d for d in directives}
    paragraph_names = set(p.upper() for p in (paragraph_names or []))

    out: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip().upper()

        if (i + 1) in directives_by_line and stripped.startswith("EXEC "):
            directive = directives_by_line[i + 1]
            # Consume every physical line through the one containing END-EXEC.
            block_lines = [raw]
            while "END-EXEC" not in block_lines[-1].upper() and i + 1 < len(lines):
                i += 1
                block_lines.append(lines[i])
            indent = raw[: len(raw) - len(raw.lstrip())]
            for stmt in _replacement_statements(directive, mock_map):
                out.append(f"{indent}{stmt}\n")
            i += 1
            continue

        # Paragraph-entry tracing: a paragraph header is a bare identifier
        # (optionally SECTION) terminated by '.', at statement start.
        bare = stripped.rstrip(".")
        if bare in paragraph_names and stripped.endswith("."):
            out.append(raw)
            out.append(f'{raw[: len(raw) - len(raw.lstrip())]}    DISPLAY "PARA:{bare}".\n')
            i += 1
            continue

        out.append(raw)
        i += 1

    return "".join(out)


__all__ = ["MockValue", "MockMap", "default_mock_map", "rewrite_cobol_source"]
