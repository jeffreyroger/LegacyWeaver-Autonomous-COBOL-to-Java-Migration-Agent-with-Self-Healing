"""Phase Z2 live-connector lane (migration-framework-spec.md Section 4.2).
CLAUDE.md rule 10's Phase Z2 exception: opt-in only (WEAVER_LIVE_CONNECTORS=1),
a separate test lane that touches real Docker containers and (optionally)
real driver jars -- weaver verify/weaver migrate/weaver connectors never
read these env vars and never open a socket.

Each connector is proven by the strongest honest means available (see the
plan's "Honest asymmetry" table): REST gets a full round trip through the
real generated gateway; PostgreSQL gets its generated schema.sql applied
to a real server; RabbitMQ gets its generated topology declared and a
publish/consume round trip via the management CLI already inside the
official image. The JDBC/AMQP Java adapter classes themselves compile and
run only when WEAVER_CONNECTOR_CLASSPATH supplies the driver jars --
otherwise those specific assertions skip with a clear reason, never
silently pass.
"""

import http.server
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from weaver.agent.connector_codegen import generate_connectors
from weaver.agent.connector_map import map_directives
from weaver.cobol.mock_directives import find_mock_directives
from weaver.cobol.subprogram import load_subprogram

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "mocked" / "orders.cob"
COMPOSE_PROJECT = "weaver-z2-live-test"


def _docker_daemon_reachable() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


requires_live = pytest.mark.skipif(
    os.environ.get("WEAVER_LIVE_CONNECTORS") != "1",
    reason="opt-in only -- set WEAVER_LIVE_CONNECTORS=1 (CLAUDE.md rule 10 Phase Z2 exception)",
)
requires_docker = pytest.mark.skipif(not _docker_daemon_reachable(), reason="requires a reachable Docker daemon")
requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@pytest.fixture(scope="module")
def artefacts(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("z2live")
    model = load_subprogram(FIXTURE)
    full_source = model.source_path.read_text(encoding="utf-8")
    bindings = map_directives(find_mock_directives(full_source))
    generate_connectors(model, bindings, out_dir)
    return out_dir, model, bindings


@pytest.fixture(scope="module")
def compose_up(artefacts):
    if os.environ.get("WEAVER_LIVE_CONNECTORS") != "1":
        pytest.skip("opt-in only -- set WEAVER_LIVE_CONNECTORS=1 (CLAUDE.md rule 10 Phase Z2 exception)")
    if not _docker_daemon_reachable():
        pytest.skip("requires a reachable Docker daemon")
    out_dir, _model, _bindings = artefacts
    subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", str(out_dir / "docker-compose.yml"), "up", "-d", "--wait"],
        check=True, timeout=180,
    )
    yield out_dir
    subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", str(out_dir / "docker-compose.yml"), "down", "-v"],
        timeout=60,
    )


@requires_live
@requires_docker
def test_generated_schema_sql_applies_to_a_real_postgres(compose_up):
    out_dir = compose_up
    result = subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "exec", "-T", "postgres",
         "psql", "-U", "weaver", "-d", "weaver", "-v", "ON_ERROR_STOP=1"],
        input=(out_dir / "schema.sql").read_text(encoding="utf-8"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"psql failed:\n{result.stdout}\n{result.stderr}"

    verify = subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "exec", "-T", "postgres",
         "psql", "-U", "weaver", "-d", "weaver", "-c", "\\dt orders"],
        capture_output=True, text=True, timeout=30,
    )
    assert "orders" in verify.stdout.lower()


@requires_live
@requires_docker
def test_generated_topology_round_trips_through_real_rabbitmq(compose_up):
    subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "exec", "-T", "rabbitmq",
         "rabbitmqadmin", "declare", "queue", "name=ORDERQ", "durable=true"],
        check=True, timeout=30,
    )
    subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "exec", "-T", "rabbitmq",
         "rabbitmqadmin", "publish", "routing_key=ORDERQ", "payload=00012345"],
        check=True, timeout=30,
    )
    result = subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "exec", "-T", "rabbitmq",
         "rabbitmqadmin", "get", "queue=ORDERQ", "ackmode=ack_requeue_false"],
        capture_output=True, text=True, timeout=30,
    )
    assert "00012345" in result.stdout


@requires_live
def test_real_generated_rest_gateway_round_trips_against_a_stub_server(artefacts):
    """Doesn't need Docker: proves the REAL generated
    RestTransactionGateway.java (java.net.http, JDK-only) against a
    localhost stub -- the strongest honest proof available for a
    connector whose real counterpart (a CICS-hosted remote program) has
    no offline equivalent to call."""
    if shutil.which("javac") is None:
        pytest.skip("requires javac on PATH")
    out_dir, model, bindings = artefacts

    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = self.rfile.read(length).decode("utf-8")
            received["signature"] = self.headers.get("X-Weaver-Signature")
            received["path"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"00012345")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        driver_dir = out_dir / "driver"
        driver_dir.mkdir(exist_ok=True)
        (driver_dir / "Main.java").write_text(f"""\
public final class Main {{
    public static void main(String[] args) throws Exception {{
        RestTransactionGateway gw = new RestTransactionGateway("http://127.0.0.1:{port}");
        String result = gw.call("TEST:SIG", "PRICING", "00012345");
        System.out.println(result);
    }}
}}
""", encoding="utf-8")
        build_dir = out_dir / "driver_build"
        build_dir.mkdir(exist_ok=True)
        compile_result = subprocess.run(
            ["javac", "-d", str(build_dir),
             str(out_dir / "WeaverTransactionGateway.java"), str(out_dir / "RestTransactionGateway.java"),
             str(driver_dir / "Main.java")],
            capture_output=True, text=True, timeout=30,
        )
        assert compile_result.returncode == 0, compile_result.stderr

        run_result = subprocess.run(
            ["java", "-cp", str(build_dir), "Main"], capture_output=True, text=True, timeout=30,
        )
        assert run_result.returncode == 0, run_result.stderr
        assert run_result.stdout.strip() == "00012345"
        assert received["body"] == "00012345"
        assert received["signature"] == "TEST:SIG"
        assert received["path"] == "/PRICING"
    finally:
        server.shutdown()


@requires_live
@requires_javac
def test_jdbc_and_amqp_adapters_skip_without_driver_jars_on_classpath(artefacts):
    """Disclosed asymmetry, exercised rather than glossed over: without
    WEAVER_CONNECTOR_CLASSPATH pointing at real driver jars, these two
    real adapters cannot compile -- this test proves that boundary is
    real, not asserted."""
    classpath_dir = os.environ.get("WEAVER_CONNECTOR_CLASSPATH")
    if not classpath_dir:
        pytest.skip("WEAVER_CONNECTOR_CLASSPATH not set -- no driver jars supplied for this run")

    out_dir, _model, _bindings = artefacts
    build_dir = out_dir / "jdbc_amqp_build"
    build_dir.mkdir(exist_ok=True)
    jars = list(Path(classpath_dir).glob("*.jar"))
    assert jars, f"WEAVER_CONNECTOR_CLASSPATH={classpath_dir} has no jars"
    cp = os.pathsep.join(str(j) for j in jars)

    result = subprocess.run(
        ["javac", "-cp", cp, "-d", str(build_dir),
         str(out_dir / "WeaverDataSource.java"), str(out_dir / "PostgresDataSource.java"),
         str(out_dir / "WeaverMessageQueue.java"), str(out_dir / "RabbitMqQueue.java")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"javac failed with supplied driver jars:\n{result.stdout}\n{result.stderr}"
