"""Unit-cache-backed verification — GRAPH_PLAN.md M6 (verifier half).

`verify_unit_from_cache` is a faster substitute for
`weaver.agent.attribution.verify_unit`, never a replacement for it: M7's
equivalence gate (tests/test_replay_verify_live.py) proves the two agree
exactly before this is ever wired into a real repair loop
(Non-Negotiable Design Decision 3, GRAPH_PLAN.md §1).

Design, reached after empirically testing GnuCOBOL's actual DISPLAY
output (this session, WSL GnuCOBOL 3.2.0) rather than assuming a decode
format: nothing here re-implements COBOL decode/encode semantics a
second time.

- `ar` (the input record) is never taken from the harvested cache at all.
  A UnitFixture's `record_index` is the line number in the real
  `input_data` file; the driver re-reads that line and decodes it with
  the assembled Scaffold.java's own `AccountRecord.decode()` -- the exact
  decoder the whole-program path already trusts.
- `ws` (working storage) seeding and checking use the harvested DISPLAY
  text directly. GnuCOBOL's DISPLAY of a signed, non-SEPARATE numeric
  WORKING-STORAGE field (e.g. `WS-INTEREST PIC S9(7)V99`) was confirmed
  to emit clean `+0000123.45` / `-0000123.45` text -- not zoned-decimal
  overpunch bytes -- and Java's `BigDecimal(String)` parses that directly.
  No custom decode helper is needed for WS fields at all.
- Only `ScaffoldSpec.ws_fields` *excluding the accumulator* are seeded or
  checked. `weaver.agent.scaffold.ws_accessors()` already computes this
  exact set: reading `generated/Scaffold.java`'s own main-loop wiring
  during this design showed `ws.totalInterest` is advanced by the
  scaffold's main loop (`ws.totalInterest = ws.totalInterest.add(...)`),
  never inside the candidate paragraph body -- it is scaffold-owned, not
  paragraph-owned, even though the COBOL *source* text of PROCESS-RECORD
  contains the `ADD` statement (dataflow.py's read/write set is correct
  for the knowledge graph; it is not the right scope for this replay).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weaver.agent.assemble import assemble
from weaver.agent.attribution import AttributionResult
from weaver.agent.runspec import RunSpec
from weaver.agent.scaffold import ScaffoldSpec, generate as generate_scaffold, ws_accessors
from weaver.agent.trace_harvest import UnitFixture
from weaver.classification import Classification, classify
from weaver.comparison import Divergence
from weaver.report import Report

DRIVER_CLASS_NAME = "UnitCacheDriver"
_RESULT_PREFIX = "RESULT\t"


def _fixture_data_text(fixtures: list[UnitFixture]) -> str:
    """One row per (record, phase, field): `<record_index>\\tENTRY|EXIT\\t<field>\\t<value>`.
    Read at runtime by the generated driver -- kept as plain data, not
    baked into the driver's Java source, so driver generation stays a
    pure function of ScaffoldSpec alone."""
    rows = []
    for fx in fixtures:
        for field_name, value in fx.input_state.items():
            rows.append(f"{fx.record_index}\tENTRY\t{field_name}\t{value}")
        for field_name, value in fx.output_state.items():
            rows.append(f"{fx.record_index}\tEXIT\t{field_name}\t{value}")
    return "\n".join(rows) + "\n"


def _generate_driver(spec: ScaffoldSpec) -> str:
    """Java source for a small standalone driver, compiled alongside the
    assembled Scaffold.java: for each harvested record, seed `ws` from
    its ENTRY values, call the candidate paragraph method, and compare
    the result against the harvested EXIT values -- entirely in memory,
    no file I/O, no re-running the other 199 records."""
    accessors = ws_accessors(spec)  # cobol name -> "ws.javaName", accumulator excluded

    seed_lines = "\n".join(
        f'            if (entry.containsKey("{cobol}")) {expr} = '
        f'new java.math.BigDecimal(entry.get("{cobol}").trim());'
        for cobol, expr in accessors.items()
    )
    check_lines = "\n".join(
        f"""            if (exit.containsKey("{cobol}")) {{
                reportField(out, recordIndex, "{cobol}", exit.get("{cobol}").trim(), {expr}, thrown);
            }}"""
        for cobol, expr in accessors.items()
    )

    return f"""\
import java.math.BigDecimal;
import java.nio.file.*;
import java.util.*;

public class {DRIVER_CLASS_NAME} {{
    public static void main(String[] args) throws Exception {{
        String fixtureDataPath = args[0];
        String inputDataPath = args[1];
        int recordWidth = Integer.parseInt(args[2]);

        List<String> inputLines = Files.readAllLines(Paths.get(inputDataPath));

        // record_index -> phase -> field -> value
        Map<Integer, Map<String, String>> entries = new TreeMap<>();
        Map<Integer, Map<String, String>> exits = new TreeMap<>();
        for (String line : Files.readAllLines(Paths.get(fixtureDataPath))) {{
            if (line.isEmpty()) continue;
            String[] parts = line.split("\\t", 4);
            int idx = Integer.parseInt(parts[0]);
            Map<Integer, Map<String, String>> target = parts[1].equals("ENTRY") ? entries : exits;
            target.computeIfAbsent(idx, k -> new LinkedHashMap<>()).put(parts[2], parts[3]);
        }}

        StringBuilder out = new StringBuilder();
        for (Integer recordIndex : entries.keySet()) {{
            Map<String, String> entry = entries.getOrDefault(recordIndex, Collections.emptyMap());
            Map<String, String> exit = exits.getOrDefault(recordIndex, Collections.emptyMap());

            String rawLine = inputLines.get(recordIndex);
            String paddedLine = String.format("%-" + recordWidth + "s", rawLine);
            AccountRecord ar = AccountRecord.decode(paddedLine);
            WorkingStorage ws = new WorkingStorage();

{seed_lines}

            String thrown = null;
            try {{
                Scaffold.{spec.paragraph_method}(ar, ws);
            }} catch (Throwable t) {{
                thrown = t.toString();
            }}

{check_lines}
        }}

        System.out.print(out);
    }}

    static void reportField(StringBuilder out, int recordIndex, String field, String expectedText,
                             BigDecimal actual, String thrown) {{
        String expected = expectedText;
        String actualText = thrown != null ? ("EXCEPTION:" + thrown) : actual.toPlainString();
        boolean match = false;
        if (thrown == null) {{
            try {{
                match = new BigDecimal(expectedText).compareTo(actual) == 0;
            }} catch (NumberFormatException e) {{
                match = false;
            }}
        }}
        out.append("{_RESULT_PREFIX.rstrip()}\\t").append(recordIndex).append("\\t").append(field)
           .append("\\t").append(match ? "MATCH" : "DIFF")
           .append("\\t").append(expected).append("\\t").append(actualText).append("\\n");
    }}
}}
"""


@dataclass(frozen=True)
class _ParsedResult:
    record_index: int
    field: str
    matched: bool
    expected: str
    actual: str


def _parse_driver_output(stdout: str) -> list[_ParsedResult]:
    out = []
    for line in stdout.splitlines():
        if not line.startswith(_RESULT_PREFIX):
            continue
        _, idx, field, status, expected, actual = line.split("\t", 5)
        out.append(_ParsedResult(int(idx), field, status == "MATCH", expected, actual))
    return out


def verify_unit_from_cache(
    unit_id: str, candidate_body: str, fixtures: list[UnitFixture], work_dir: Path, *, spec: RunSpec,
) -> AttributionResult:
    """Verify `candidate_body` against harvested fixtures instead of
    re-running the whole assembled program. Shape-compatible with
    `attribution.verify_unit`'s `AttributionResult` so callers (and M7's
    equivalence test) can compare them directly."""
    ss = spec.scaffold_spec
    unit_fixtures = [f for f in fixtures if f.paragraph_id == unit_id]

    work_dir.mkdir(parents=True, exist_ok=True)
    scaffold_src = assemble(generate_scaffold(ss), {unit_id: candidate_body})
    (work_dir / "Scaffold.java").write_text(scaffold_src, encoding="utf-8")
    (work_dir / f"{DRIVER_CLASS_NAME}.java").write_text(_generate_driver(ss), encoding="utf-8")
    fixture_data_path = work_dir / "fixtures.tsv"
    fixture_data_path.write_text(_fixture_data_text(unit_fixtures), encoding="utf-8")

    build_dir = work_dir / "build"
    build_dir.mkdir(exist_ok=True)
    compile_proc = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(build_dir),
         str(work_dir / "Scaffold.java"), str(work_dir / f"{DRIVER_CLASS_NAME}.java")],
        capture_output=True, text=True,
    )
    if compile_proc.returncode != 0:
        return AttributionResult(unit_id, Report(unit_id, 0), [], False, compile_proc.stderr)

    record_width = sum(f.width for f in ss.input_layout if f.redefines is None)
    run_proc = subprocess.run(
        ["java", "-cp", str(build_dir), DRIVER_CLASS_NAME,
         str(fixture_data_path.resolve()), str(spec.input_data.resolve()), str(record_width)],
        capture_output=True, text=True,
    )
    results = _parse_driver_output(run_proc.stdout)

    report = Report(unit_id=unit_id, total_records=len(unit_fixtures))
    classifications: list[Classification] = []
    for r in results:
        if r.matched:
            continue
        numeric_delta: Decimal | None = None
        try:
            numeric_delta = Decimal(r.expected.strip()) - Decimal(r.actual.strip())
        except InvalidOperation:
            pass
        div = Divergence(
            record_index=r.record_index, byte_offset=0, field_name=r.field,
            oracle_value=r.expected, candidate_value=r.actual,
            numeric_delta=numeric_delta, causing_input_record=None,
        )
        report.add_divergence(div)
        scale = next((f.scale for f in ss.ws_fields if ws_accessors(ss).get(r.field) == f"ws.{f.java_name}"), 2)
        classifications.append(classify(div, field_decimal_scale=scale))

    return AttributionResult(unit_id, report, classifications, True, None)
