"""Legacy subsystem -> modern connector mapping -- Phase Z2
(migration-framework-spec.md Section 4.2, "Legacy Subsystem Substitutions":
mainframe RDBMS -> PostgreSQL, MQ Series -> RabbitMQ, EXEC CICS/IMS
middleware -> RESTful endpoints).

Pure mapping layer over Phase Z1's `weaver/cobol/mock_directives.py`
`MockDirective` -- no I/O, no code generation, no network. Answers exactly
one question: "which modern connector does this legacy call become?"
`weaver/agent/connector_codegen.py` consumes the answer and emits code.

An unmapped verb raises `UnsupportedConnectorError` rather than defaulting
to a plausible-looking connector -- the same never-guess posture
`weaver/cobol/subprogram.py` and `weaver/cobol/frontend.py` already take
(CLAUDE.md rule 9). A confidently wrong connector choice is far worse than
a refusal, because the generated Java would compile and look correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from weaver.cobol.mock_directives import MockDirective

# EXEC SQL: the table follows FROM / INTO <table> / UPDATE <table>.
_SQL_FROM_RE = re.compile(r"\bFROM\s+([A-Z0-9_-]+)", re.IGNORECASE)
_SQL_INSERT_RE = re.compile(r"\bINSERT\s+INTO\s+([A-Z0-9_-]+)", re.IGNORECASE)
_SQL_UPDATE_RE = re.compile(r"\bUPDATE\s+([A-Z0-9_-]+)", re.IGNORECASE)
# EXEC CICS: operands are NAME(VALUE); the value may be a quoted literal.
_CICS_OPERAND_TEMPLATE = r"\b{name}\s*\(\s*'?([A-Z0-9_.-]+)'?\s*\)"

# Section 4.2's three target subsystems.
_SQL_VERBS = {"SELECT", "INSERT", "UPDATE", "DELETE"}
# CICS temporary-storage / transient-data queues carry queue semantics, and
# are what an MQ Series MQPUT/MQGET becomes in a CICS-hosted program.
_CICS_QUEUE_VERBS = {"READQ", "WRITEQ", "DELETEQ", "MQPUT", "MQGET"}
# CICS file control over VSAM -- the standard modernization target is a
# relational table, i.e. the same PostgreSQL data layer as EXEC SQL.
_CICS_FILE_VERBS = {"READ", "WRITE", "REWRITE", "DELETE", "STARTBR", "READNEXT", "ENDBR"}
# Program-control / transaction verbs -- Section 4.2's "mapped to RESTful
# endpoints, with application state preserved via containerized services".
_CICS_REST_VERBS = {"LINK", "XCTL", "START", "RETURN"}


class UnsupportedConnectorError(ValueError):
    """A directive whose verb this module has no declared mapping for."""


class ConnectorKind(Enum):
    POSTGRES = "postgres"
    RABBITMQ = "rabbitmq"
    REST = "rest"


@dataclass(frozen=True)
class ConnectorBinding:
    kind: ConnectorKind
    directive: MockDirective
    target: str        # table name / queue name / remote program (endpoint) name
    operation: str      # SELECT / INSERT / PUBLISH / CONSUME / POST ...

    @property
    def signature(self) -> str:
        """Reused verbatim from the directive, so a binding and its Phase Z1
        deterministic mock value are always keyed identically -- the offline
        adapter and the mocked-verify path cannot drift apart."""
        return self.directive.signature

    @property
    def java_identifier(self) -> str:
        """`ORDER-QUEUE` -> `ORDER_QUEUE`, usable as a Java constant name."""
        return re.sub(r"[^A-Za-z0-9]", "_", self.target).upper()


def _cics_operand(body: str, name: str) -> str | None:
    pattern = _CICS_OPERAND_TEMPLATE.format(name=re.escape(name))
    found = re.search(pattern, body, re.IGNORECASE)
    return found.group(1).upper() if found else None


def _sql_target(directive: MockDirective) -> str:
    for pattern in (_SQL_INSERT_RE, _SQL_UPDATE_RE, _SQL_FROM_RE):
        found = pattern.search(directive.body)
        if found:
            return found.group(1).upper()
    raise UnsupportedConnectorError(
        f"line {directive.line_number}: EXEC SQL {directive.verb} names no table "
        f"(no FROM / INSERT INTO / UPDATE clause found): {directive.body!r}"
    )


def map_directive(directive: MockDirective) -> ConnectorBinding:
    """Maps one parsed EXEC block to its Section 4.2 modern connector.
    Raises `UnsupportedConnectorError` for any verb without a declared
    rule -- never falls back to a default connector."""
    verb = directive.verb.upper()

    if directive.kind == "SQL":
        if verb not in _SQL_VERBS:
            raise UnsupportedConnectorError(
                f"line {directive.line_number}: EXEC SQL verb {verb!r} has no declared "
                f"connector mapping (known: {sorted(_SQL_VERBS)})"
            )
        return ConnectorBinding(ConnectorKind.POSTGRES, directive, _sql_target(directive), verb)

    if directive.kind == "CICS":
        if verb in _CICS_QUEUE_VERBS:
            target = _cics_operand(directive.body, "QUEUE") or _cics_operand(directive.body, "TDQUEUE")
            if target is None:
                raise UnsupportedConnectorError(
                    f"line {directive.line_number}: EXEC CICS {verb} names no QUEUE(...): "
                    f"{directive.body!r}"
                )
            operation = "CONSUME" if verb in ("READQ", "MQGET") else "PUBLISH"
            return ConnectorBinding(ConnectorKind.RABBITMQ, directive, target, operation)

        if verb in _CICS_FILE_VERBS:
            target = _cics_operand(directive.body, "FILE") or _cics_operand(directive.body, "DATASET")
            if target is None:
                raise UnsupportedConnectorError(
                    f"line {directive.line_number}: EXEC CICS {verb} names no FILE(...): "
                    f"{directive.body!r}"
                )
            return ConnectorBinding(ConnectorKind.POSTGRES, directive, target, verb)

        if verb in _CICS_REST_VERBS:
            target = _cics_operand(directive.body, "PROGRAM") or _cics_operand(directive.body, "TRANSID")
            if target is None:
                raise UnsupportedConnectorError(
                    f"line {directive.line_number}: EXEC CICS {verb} names no PROGRAM(...): "
                    f"{directive.body!r}"
                )
            return ConnectorBinding(ConnectorKind.REST, directive, target, "POST")

        raise UnsupportedConnectorError(
            f"line {directive.line_number}: EXEC CICS verb {verb!r} has no declared connector mapping"
        )

    raise UnsupportedConnectorError(
        f"line {directive.line_number}: directive kind {directive.kind!r} has no connector mapping"
    )


def map_directives(directives: list[MockDirective]) -> list[ConnectorBinding]:
    return [map_directive(d) for d in directives]


__all__ = [
    "ConnectorBinding", "ConnectorKind", "UnsupportedConnectorError",
    "map_directive", "map_directives",
]
