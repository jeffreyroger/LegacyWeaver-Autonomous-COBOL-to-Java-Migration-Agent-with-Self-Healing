"""EXEC SQL / EXEC CICS directive parser -- Phase Z1
(migration-framework-spec.md Section 2.1's "Dynamic Mocking": database
queries (`EXEC SQL`), transactional platform APIs (`EXEC CICS`), and
external subprogram calls are intercepted and mocked deterministically
rather than executed for real -- this offline harness has no database or
CICS region to call (CLAUDE.md rule 10), so "real execution" of these
statements was never possible; the framework's own answer is to replace
them with a deterministic mock, which is exactly what this module and
`weaver/agent/mock_generator.py` do).

Parses `EXEC SQL ... END-EXEC` / `EXEC CICS ... END-EXEC` blocks out of a
paragraph's raw statement list (produced by `weaver.cobol.source.statements`,
reused unchanged -- an EXEC block with no internal period is already one
`Statement` by that tokenizer's own multi-line-join rule). Never guesses
at a directive it cannot parse; raises `UnsupportedMockDirectiveError`
instead of silently skipping one (CLAUDE.md's "flag rather than invent"
discipline, the same posture `weaver/cobol/subprogram.py` and
`weaver/cobol/frontend.py` already take).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from weaver.cobol.source import Statement, statements

_EXEC_RE = re.compile(r"^EXEC\s+(SQL|CICS)\s+(.*?)\s+END-EXEC$", re.IGNORECASE | re.DOTALL)
_HOST_VAR_RE = re.compile(r":([A-Z0-9-]+)", re.IGNORECASE)


class UnsupportedMockDirectiveError(ValueError):
    """An EXEC block outside this module's declared parseable shape."""


@dataclass(frozen=True)
class MockDirective:
    kind: str          # "SQL" or "CICS"
    verb: str           # first token of the body, e.g. "SELECT", "READ", "LINK"
    body: str           # the full text between EXEC SQL/CICS and END-EXEC
    host_vars: tuple[str, ...]   # COBOL identifiers referenced (":VAR" for SQL, bare tokens for CICS)
    line_number: int

    @property
    def signature(self) -> str:
        """Deterministic call-signature used as the mock-lookup key and the
        stub-log entry -- same directive text always yields the same
        signature, which is what makes the mock deterministic across the
        oracle and candidate sides without either side needing to agree on
        anything except this module's own derivation rule."""
        return f"{self.kind}:{self.verb}:{'-'.join(self.host_vars)}"


def _parse_one(stmt: Statement) -> MockDirective | None:
    match = _EXEC_RE.match(stmt.text.strip())
    if match is None:
        return None
    kind, body = match.group(1).upper(), match.group(2).strip()
    tokens = body.split()
    if not tokens:
        raise UnsupportedMockDirectiveError(
            f"line {stmt.line_number}: EXEC {kind} block has no verb: {stmt.text!r}"
        )
    verb = tokens[0].upper()
    if kind == "SQL":
        host_vars = tuple(sorted(set(m.upper() for m in _HOST_VAR_RE.findall(body))))
    else:
        # CICS commands take bare-token operands (no ':' prefix); the
        # operand immediately following the verb is what this module
        # models -- e.g. "READ FILE(CUSTOMER) INTO(WS-REC)" -> ("FILE(CUSTOMER)",).
        host_vars = tuple(tokens[1:])
    return MockDirective(kind=kind, verb=verb, body=body, host_vars=host_vars, line_number=stmt.line_number)


def find_mock_directives(source: str) -> list[MockDirective]:
    """Scans `source` (any COBOL source text, typically one paragraph's
    `paragraph_source`) for EXEC SQL/EXEC CICS blocks. Returns them in
    source order. Raises `UnsupportedMockDirectiveError` for an `EXEC`
    block whose kind isn't SQL/CICS or whose body is empty -- never
    silently drops one."""
    directives: list[MockDirective] = []
    for stmt in statements(source):
        upper = stmt.text.strip().upper()
        if upper.startswith("EXEC ") and "END-EXEC" not in upper:
            raise UnsupportedMockDirectiveError(
                f"line {stmt.line_number}: EXEC block has no END-EXEC in the same statement "
                f"(a period inside the block would split it): {stmt.text!r}"
            )
        if upper.startswith("EXEC ") and not upper.startswith(("EXEC SQL", "EXEC CICS")):
            raise UnsupportedMockDirectiveError(
                f"line {stmt.line_number}: only EXEC SQL/EXEC CICS are modeled: {stmt.text!r}"
            )
        parsed = _parse_one(stmt)
        if parsed is not None:
            directives.append(parsed)
    return directives


__all__ = ["MockDirective", "UnsupportedMockDirectiveError", "find_mock_directives"]
