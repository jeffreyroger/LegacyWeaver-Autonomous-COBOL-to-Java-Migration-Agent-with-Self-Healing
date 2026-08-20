"""Phase Z2 acceptance tests (migration-framework-spec.md Section 4.2) --
weaver.agent.connector_map routes every EXEC SQL/EXEC CICS verb this
harness declares support for, and raises rather than guessing for
anything else."""

from pathlib import Path

import pytest

from weaver.agent.connector_map import (
    ConnectorKind,
    UnsupportedConnectorError,
    map_directive,
    map_directives,
)
from weaver.cobol.mock_directives import find_mock_directives
from weaver.cobol.subprogram import load_subprogram

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "mocked" / "orders.cob"


def _directive(text: str):
    source = f"       MAIN-PARA.\n{text}\n"
    return find_mock_directives(source)[0]


def test_orders_fixture_routes_to_all_three_connectors():
    model = load_subprogram(FIXTURE)
    full_source = model.source_path.read_text(encoding="utf-8")
    directives = find_mock_directives(full_source)
    bindings = {b.kind: b for b in map_directives(directives)}

    assert bindings[ConnectorKind.POSTGRES].target == "ORDERS"
    assert bindings[ConnectorKind.POSTGRES].operation == "SELECT"
    assert bindings[ConnectorKind.RABBITMQ].target == "ORDERQ"
    assert bindings[ConnectorKind.RABBITMQ].operation == "PUBLISH"
    assert bindings[ConnectorKind.REST].target == "PRICING"
    assert bindings[ConnectorKind.REST].operation == "POST"
    # Every binding's signature matches its directive's -- Phase Z1's mock
    # map and Phase Z2's offline adapter can never disagree on a key.
    for binding in bindings.values():
        assert binding.signature == binding.directive.signature


def test_sql_insert_and_update_route_to_postgres():
    insert = _directive("           EXEC SQL INSERT INTO ORDERS VALUES (:OR-ID) END-EXEC.")
    update = _directive("           EXEC SQL UPDATE ORDERS SET TOTAL = :OR-TOTAL END-EXEC.")
    assert map_directive(insert).kind == ConnectorKind.POSTGRES
    assert map_directive(insert).target == "ORDERS"
    assert map_directive(update).kind == ConnectorKind.POSTGRES
    assert map_directive(update).target == "ORDERS"


def test_cics_readq_routes_to_rabbitmq_as_consume():
    directive = _directive("           EXEC CICS READQ TS QUEUE('ORDERQ') INTO(OR-TOTAL) END-EXEC.")
    binding = map_directive(directive)
    assert binding.kind == ConnectorKind.RABBITMQ
    assert binding.operation == "CONSUME"
    assert binding.target == "ORDERQ"


def test_cics_file_read_routes_to_postgres():
    directive = _directive("           EXEC CICS READ FILE('CUSTOMER') INTO(OR-TOTAL) END-EXEC.")
    binding = map_directive(directive)
    assert binding.kind == ConnectorKind.POSTGRES
    assert binding.target == "CUSTOMER"


def test_cics_xctl_routes_to_rest():
    directive = _directive("           EXEC CICS XCTL PROGRAM('NEXTPROG') END-EXEC.")
    binding = map_directive(directive)
    assert binding.kind == ConnectorKind.REST
    assert binding.target == "NEXTPROG"


def test_unmapped_sql_verb_raises():
    directive = _directive("           EXEC SQL COMMIT END-EXEC.")
    with pytest.raises(UnsupportedConnectorError):
        map_directive(directive)


def test_sql_select_with_no_from_clause_raises():
    directive = _directive("           EXEC SQL SELECT 1 END-EXEC.")
    with pytest.raises(UnsupportedConnectorError):
        map_directive(directive)


def test_cics_writeq_with_no_queue_operand_raises():
    directive = _directive("           EXEC CICS WRITEQ TS FROM(OR-TOTAL) END-EXEC.")
    with pytest.raises(UnsupportedConnectorError):
        map_directive(directive)


def test_unmapped_cics_verb_raises():
    directive = _directive("           EXEC CICS ASKTIME END-EXEC.")
    with pytest.raises(UnsupportedConnectorError):
        map_directive(directive)


def test_java_identifier_is_a_valid_constant_name():
    directive = _directive("           EXEC CICS WRITEQ TS QUEUE('ORDER-Q') FROM(OR-TOTAL) END-EXEC.")
    binding = map_directive(directive)
    assert binding.java_identifier == "ORDER_Q"
