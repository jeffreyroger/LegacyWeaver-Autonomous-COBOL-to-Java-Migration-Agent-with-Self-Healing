"""Connector code + deployment descriptor generator -- Phase Z2
(migration-framework-spec.md Section 4.2).

Ports & adapters: three tiny interfaces (`WeaverDataSource`,
`WeaverMessageQueue`, `WeaverTransactionGateway`), a real adapter per
Section 4.2 target (Postgres/RabbitMQ/REST), and one offline adapter that
implements all three ports from Phase Z1's own deterministic `MockMap`
(`weaver/agent/mock_generator.py`) -- reused, not re-derived, so a
connector-bound run and a Phase Z1 mocked-verify run can never disagree on
a canned value for the same directive.

CLAUDE.md rule 10 boundary: everything this module WRITES is migration
output. Nothing it writes is ever compiled into, or executed by, the
parity-gate verification path -- that path binds `OfflineAdapters` only.
Real network I/O happens only in the separate, opt-in live-connector lane
(`WEAVER_LIVE_CONNECTORS=1`, see CLAUDE.md rule 10's new Phase Z2
exception), never inside `weaver verify`/`weaver migrate`.
"""

from __future__ import annotations

from pathlib import Path

from weaver.agent.connector_map import ConnectorBinding, ConnectorKind
from weaver.agent.mock_generator import MockMap, default_mock_map
from weaver.cobol.mock_directives import MockDirective
from weaver.layout import Field


def _class_name(program_id: str) -> str:
    return "".join(part.capitalize() for part in program_id.split("-"))


def _sql_column_type(field: Field) -> str:
    if not field.numeric:
        return f"CHAR({field.width})"
    scale = field.decimal_scale
    precision = field.width - (1 if field.trailing_separate_sign else 0)
    return f"NUMERIC({precision}, {scale})"


def _schema_sql(program_id: str, bindings: list[ConnectorBinding], fields: tuple[Field, ...]) -> str:
    tables = {b.target for b in bindings if b.kind == ConnectorKind.POSTGRES}
    # Every field gets a column (numeric -> NUMERIC, alphanumeric -> CHAR
    # via _sql_column_type) -- there is no field kind excluded here.
    columns = ",\n    ".join(f"{f.name.replace('-', '_')} {_sql_column_type(f)}" for f in fields)
    statements = [
        f"-- Phase Z2: derived from {program_id}'s LINKAGE SECTION field table "
        f"(weaver.layout.Field) -- never hand-declared (CLAUDE.md rule 9).",
    ]
    for table in sorted(tables):
        statements.append(f"CREATE TABLE IF NOT EXISTS {table.lower()} (\n    {columns}\n);")
    return "\n\n".join(statements) + "\n"


_PORT_INTERFACES = {
    "WeaverDataSource.java": """\
public interface WeaverDataSource {
    /** Returns the raw digit-string value the legacy EXEC SQL call would
     * have fetched, keyed by its Phase Z1 directive signature. */
    String query(String signature, String table) throws Exception;
}
""",
    "WeaverMessageQueue.java": """\
public interface WeaverMessageQueue {
    void publish(String signature, String queue, String payload) throws Exception;
    String consume(String signature, String queue) throws Exception;
}
""",
    "WeaverTransactionGateway.java": """\
public interface WeaverTransactionGateway {
    String call(String signature, String remoteProgram, String payload) throws Exception;
}
""",
}


def _postgres_adapter() -> str:
    return """\
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

/** Section 4.2: mainframe RDBMS -> PostgreSQL. JDK-only (java.sql) --
 * compiles offline; needs org.postgresql.Driver on the classpath and a
 * reachable server only when actually RUN (never during weaver verify). */
public final class PostgresDataSource implements WeaverDataSource {
    private final String jdbcUrl;

    public PostgresDataSource(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @Override
    public String query(String signature, String table) throws Exception {
        try (Connection conn = DriverManager.getConnection(jdbcUrl);
             PreparedStatement ps = conn.prepareStatement("SELECT * FROM " + table + " LIMIT 1");
             ResultSet rs = ps.executeQuery()) {
            if (rs.next()) {
                return rs.getString(1);
            }
            throw new IllegalStateException("no row for " + signature + " in " + table);
        }
    }
}
"""


def _rabbitmq_adapter() -> str:
    return """\
import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;
import com.rabbitmq.client.ConnectionFactory;
import java.nio.charset.StandardCharsets;

/** Section 4.2: MQ Series -> RabbitMQ. Needs com.rabbitmq.client on the
 * classpath to compile (not JDK-builtin) -- emitted as migration output
 * regardless; compiled/run only in the opt-in live-connector lane when the
 * jar is supplied via WEAVER_CONNECTOR_CLASSPATH. */
public final class RabbitMqQueue implements WeaverMessageQueue {
    private final String amqpUri;

    public RabbitMqQueue(String amqpUri) {
        this.amqpUri = amqpUri;
    }

    @Override
    public void publish(String signature, String queue, String payload) throws Exception {
        ConnectionFactory factory = new ConnectionFactory();
        factory.setUri(amqpUri);
        try (Connection conn = factory.newConnection(); Channel channel = conn.createChannel()) {
            channel.queueDeclare(queue, true, false, false, null);
            channel.basicPublish("", queue, null, payload.getBytes(StandardCharsets.UTF_8));
        }
    }

    @Override
    public String consume(String signature, String queue) throws Exception {
        ConnectionFactory factory = new ConnectionFactory();
        factory.setUri(amqpUri);
        try (Connection conn = factory.newConnection(); Channel channel = conn.createChannel()) {
            channel.queueDeclare(queue, true, false, false, null);
            var response = channel.basicGet(queue, true);
            if (response == null) {
                throw new IllegalStateException("no message on " + queue + " for " + signature);
            }
            return new String(response.getBody(), StandardCharsets.UTF_8);
        }
    }
}
"""


def _rest_adapter() -> str:
    return """\
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/** Section 4.2: EXEC CICS LINK/XCTL/START -> RESTful endpoint, application
 * state preserved via a containerized microservice. JDK-only
 * (java.net.http) -- compiles and can genuinely run offline against any
 * localhost stub server, real network only in the opt-in live lane. */
public final class RestTransactionGateway implements WeaverTransactionGateway {
    private final String baseUrl;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

    public RestTransactionGateway(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    @Override
    public String call(String signature, String remoteProgram, String payload) throws Exception {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + "/" + remoteProgram))
                .header("Content-Type", "text/plain")
                .header("X-Weaver-Signature", signature)
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() / 100 != 2) {
            throw new IllegalStateException(remoteProgram + " returned HTTP " + response.statusCode());
        }
        return response.body();
    }
}
"""


def _offline_adapter(mock_map: MockMap) -> str:
    entries = ",\n".join(
        f'            Map.entry("{signature}", "{value.literal}")' for signature, value in mock_map.items()
    )
    return f"""\
import java.util.Map;

/** The adapter every weaver verify/weaver migrate run binds -- Phase Z1's
 * deterministic mock values, reused verbatim (never re-derived), so this
 * and a Phase Z1 mocked-verify run agree by construction. No network,
 * ever (CLAUDE.md rule 10). */
public final class OfflineAdapters implements WeaverDataSource, WeaverMessageQueue, WeaverTransactionGateway {{
    private static final Map<String, String> VALUES = Map.ofEntries(
{entries}
    );

    private String lookup(String signature) {{
        String value = VALUES.get(signature);
        if (value == null) {{
            throw new IllegalArgumentException("no offline mock value for signature: " + signature);
        }}
        return value;
    }}

    @Override
    public String query(String signature, String table) {{
        return lookup(signature);
    }}

    @Override
    public void publish(String signature, String queue, String payload) {{
        lookup(signature);  // validates the signature is known; nothing to store offline
    }}

    @Override
    public String consume(String signature, String queue) {{
        return lookup(signature);
    }}

    @Override
    public String call(String signature, String remoteProgram, String payload) {{
        return lookup(signature);
    }}
}}
"""


def _docker_compose_yml() -> str:
    return """\
# Phase Z2 live-connector lane (WEAVER_LIVE_CONNECTORS=1 only -- never
# started by weaver verify/weaver migrate).
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: weaver
      POSTGRES_PASSWORD: weaver
      POSTGRES_DB: weaver
    ports:
      - "5432:5432"
  rabbitmq:
    image: rabbitmq:3-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
"""


def _connectors_properties(program_id: str) -> str:
    return f"""\
# Phase Z2 -- {program_id}. Every value overridable by env var; no secrets committed.
jdbc.url=jdbc:postgresql://localhost:5432/weaver?user=weaver&password=weaver
amqp.uri=amqp://guest:guest@localhost:5672
rest.baseUrl=http://localhost:8080
"""


def generate_connectors(model, bindings: list[ConnectorBinding], out_dir: Path,
                         mock_map: MockMap | None = None) -> list[Path]:
    """Writes the full Phase Z2 artefact set for `model` into `out_dir`.
    Returns every path written. `mock_map` defaults to
    `default_mock_map([b.directive for b in bindings])` -- the exact
    values Phase Z1's mocked-verify path would also compute for the same
    directives."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mock_map = mock_map if mock_map is not None else default_mock_map([b.directive for b in bindings])

    written: list[Path] = []

    def _write(name: str, content: str) -> None:
        path = out_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)

    for name, content in _PORT_INTERFACES.items():
        _write(name, content)

    kinds_present = {b.kind for b in bindings}
    if ConnectorKind.POSTGRES in kinds_present:
        _write("PostgresDataSource.java", _postgres_adapter())
    if ConnectorKind.RABBITMQ in kinds_present:
        _write("RabbitMqQueue.java", _rabbitmq_adapter())
    if ConnectorKind.REST in kinds_present:
        _write("RestTransactionGateway.java", _rest_adapter())

    _write("OfflineAdapters.java", _offline_adapter(mock_map))
    _write("schema.sql", _schema_sql(model.program_id, bindings, tuple(model.input_params) + tuple(model.output_params)))
    _write("docker-compose.yml", _docker_compose_yml())
    _write("connectors.properties", _connectors_properties(model.program_id))

    return written


__all__ = ["generate_connectors"]
