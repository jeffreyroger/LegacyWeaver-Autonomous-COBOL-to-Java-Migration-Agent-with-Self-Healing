"""Phase Z2 acceptance tests -- weaver.agent.connector_codegen emits every
declared artefact, schema.sql matches the PIC-derived field types, and
real javac compiles the JDK-only pieces (ports, PostgresDataSource,
RestTransactionGateway, OfflineAdapters) with an EMPTY classpath, proving
the "compiles offline, zero external jars" claim rather than asserting it."""

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.connector_codegen import generate_connectors
from weaver.agent.connector_map import map_directives
from weaver.cobol.mock_directives import find_mock_directives
from weaver.cobol.subprogram import load_subprogram

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "mocked" / "orders.cob"

requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


def _bindings():
    model = load_subprogram(FIXTURE)
    full_source = model.source_path.read_text(encoding="utf-8")
    directives = find_mock_directives(full_source)
    return model, map_directives(directives)


def test_generate_connectors_writes_every_declared_artefact(tmp_path):
    model, bindings = _bindings()
    written = generate_connectors(model, bindings, tmp_path)
    names = {p.name for p in written}
    assert names == {
        "WeaverDataSource.java", "WeaverMessageQueue.java", "WeaverTransactionGateway.java",
        "PostgresDataSource.java", "RabbitMqQueue.java", "RestTransactionGateway.java",
        "OfflineAdapters.java", "schema.sql", "docker-compose.yml", "connectors.properties",
    }
    for path in written:
        assert path.exists()


def test_schema_sql_matches_pic_derived_types(tmp_path):
    model, bindings = _bindings()
    generate_connectors(model, bindings, tmp_path)
    schema = (tmp_path / "schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS orders" in schema
    # OR-ID / OR-TOTAL are PIC 9(5)V99 -- width 7, scale 2 -- NUMERIC(7, 2).
    assert "OR_ID NUMERIC(7, 2)" in schema
    assert "OR_TOTAL NUMERIC(7, 2)" in schema


def test_offline_adapter_reuses_the_same_mock_map_phase_z1_would(tmp_path):
    from weaver.agent.mock_generator import default_mock_map

    model, bindings = _bindings()
    directives = [b.directive for b in bindings]
    expected_map = default_mock_map(directives)
    generate_connectors(model, bindings, tmp_path)
    offline_source = (tmp_path / "OfflineAdapters.java").read_text(encoding="utf-8")
    for signature, value in expected_map.items():
        assert f'"{signature}", "{value.literal}"' in offline_source


def test_no_connectors_for_a_directive_less_source(tmp_path):
    from weaver.agent.connector_codegen import generate_connectors as gen
    model, _ = _bindings()
    written = gen(model, [], tmp_path)
    names = {p.name for p in written}
    # No SQL/CICS directives -> no real adapter classes, but the offline
    # adapter + descriptors are still emitted (always-valid migration output).
    assert "PostgresDataSource.java" not in names
    assert "RabbitMqQueue.java" not in names
    assert "RestTransactionGateway.java" not in names
    assert "OfflineAdapters.java" in names


@requires_javac
def test_jdk_only_pieces_compile_with_an_empty_classpath(tmp_path):
    model, bindings = _bindings()
    generate_connectors(model, bindings, tmp_path)
    build_dir = tmp_path / "build"
    build_dir.mkdir()

    jdk_only_sources = [
        "WeaverDataSource.java", "WeaverMessageQueue.java", "WeaverTransactionGateway.java",
        "PostgresDataSource.java", "RestTransactionGateway.java", "OfflineAdapters.java",
    ]
    result = subprocess.run(
        ["javac", "-cp", "", "-d", str(build_dir)] + [str(tmp_path / name) for name in jdk_only_sources],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"javac failed:\n{result.stdout}\n{result.stderr}"
    assert (build_dir / "PostgresDataSource.class").exists()
    assert (build_dir / "RestTransactionGateway.class").exists()
    assert (build_dir / "OfflineAdapters.class").exists()


@requires_javac
def test_rabbitmq_adapter_fails_to_compile_without_the_jar(tmp_path):
    """Disclosed asymmetry, proven rather than asserted: RabbitMqQueue.java
    genuinely cannot compile with an empty classpath, unlike the other two
    real adapters -- this is what the live lane exists to bridge."""
    model, bindings = _bindings()
    generate_connectors(model, bindings, tmp_path)
    build_dir = tmp_path / "build"
    build_dir.mkdir()

    result = subprocess.run(
        ["javac", "-cp", "", "-d", str(build_dir),
         str(tmp_path / "WeaverMessageQueue.java"), str(tmp_path / "RabbitMqQueue.java")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "rabbitmq" in result.stderr.lower() or "package com.rabbitmq" in result.stderr
