"""Single `verify` command (Step F1/F2; FR-15).

    weaver verify <cobol_source> <java_candidate> <input_data> [--report OUT]

Compiles both programs if needed, runs the differential comparison,
classifies divergences, renders a terminal summary, writes the JSON
report, and exits 0 if verified else 1.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from rich.console import Console
from rich.table import Table

from weaver.agent.metrics import compute_metrics
from weaver.agent.orchestrator import RUNS_ROOT, Orchestrator
from weaver.agent.program_profiles import program_profile as _program_profile
from weaver.agent.runspec import (
    DEFAULT_MAX_REPAIRS,
    DEFAULT_MODEL,
    DEFAULT_SEED,
    RunSpec,
)
from weaver.classification import classify, summarize
from weaver.comparison import compare_lines, normalize_line_endings
from weaver.execution import run_candidate, run_oracle
from weaver.layout import REPORT_LAYOUT, TOTALS_LAYOUT
from weaver.report import Report

console = Console()

OUTPUT_FILENAME = "interest.out"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weaver", description="LegacyWeaver differential verification harness")
    sub = parser.add_subparsers(dest="command", required=True)

    # SRS 3.9.1 specifies the flag form; the positional form predates it and
    # is used by README, tests/test_acceptance.py and BACKEND_PLAN.md:388,
    # so both are accepted.
    verify = sub.add_parser("verify", help="Verify a Java candidate against a COBOL oracle")
    verify.add_argument("cobol_source_pos", type=Path, nargs="?", default=None,
                        metavar="cobol_source")
    verify.add_argument("java_candidate_pos", type=Path, nargs="?", default=None,
                        metavar="java_candidate")
    verify.add_argument("input_data_pos", type=Path, nargs="?", default=None,
                        metavar="input_data")
    verify.add_argument("--cobol", dest="cobol_flag", type=Path, default=None)
    verify.add_argument("--java", dest="java_flag", type=Path, default=None)
    verify.add_argument("--data", dest="data_flag", type=Path, default=None)
    verify.add_argument("--report", type=Path, default=Path("report.json"))

    report_cmd = sub.add_parser("report", help="Print metrics computed from a run directory's trace/state")
    report_cmd.add_argument("run_dir", type=Path)

    # SRS 3.9.1: weaver migrate <program.cbl> [--copybook DIR] [--data FILE]
    #            [--out DIR] [--max-repairs 3] [--model granite-code:20b] [--seed 42]
    migrate = sub.add_parser("migrate", help="Autonomously migrate a COBOL program to Java")
    migrate.add_argument("program", type=Path, help="COBOL program to migrate")
    migrate.add_argument("--copybook", type=Path, default=None, help="Copybook directory")
    migrate.add_argument("--data", type=Path, default=None, help="Input data file for verification")
    migrate.add_argument("--out", type=Path, default=None, help="Output directory for generated Java")
    migrate.add_argument("--max-repairs", type=int, default=DEFAULT_MAX_REPAIRS,
                         help="Maximum repair attempts per unit")
    migrate.add_argument("--model", default=DEFAULT_MODEL, help="Local inference model tag")
    migrate.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Inference seed")
    migrate.add_argument("--replay", action="store_true",
                         help="FR-8.4: serve model responses exclusively from cache")
    migrate.add_argument("--run-dir", type=Path, default=None,
                         help="Run directory (default: runs/<run_id>)")
    migrate.add_argument("--json", action="store_true",
                         help="Emit machine-readable JSON instead of streaming status")

    # Phase Z2 (migration-framework-spec.md Section 4.2): generate real
    # PostgreSQL/RabbitMQ/REST connector code + deployment descriptors for
    # every EXEC SQL/EXEC CICS directive in a subprogram. Migration output
    # only -- never invoked by verify/migrate, never touches a network
    # (CLAUDE.md rule 10).
    connectors = sub.add_parser(
        "connectors", help="Generate connector adapters + deployment descriptors for a mocked subprogram"
    )
    connectors.add_argument("cobol_source", type=Path, help="Subprogram COBOL source (LINKAGE SECTION shape)")
    connectors.add_argument("--out-dir", type=Path, default=None,
                            help="Output directory (default: generated/connectors/<PROGRAM-ID>)")

    # Phase AA2 (migration-framework-spec.md Section 3.2): scan a directory
    # of COBOL programs for record layouts that are structurally identical
    # across two or more programs, and emit one shared Java class per
    # distinct shape instead of leaving each program to declare its own
    # copy. Additive to weaver/agent/scaffold.py's per-program generator
    # (never touches it) -- migration output only.
    dedup = sub.add_parser(
        "dedup", help="Find and generate shared Java classes for record layouts duplicated across programs"
    )
    dedup.add_argument("cobol_dir", type=Path, help="Directory to scan recursively for *.cob files")
    dedup.add_argument("--out-dir", type=Path, default=Path("generated") / "shared_classes",
                        help="Output directory (default: generated/shared_classes)")

    original_parse_args = parser.parse_args

    def parse_args(args=None, namespace=None):
        ns = original_parse_args(args, namespace)
        if ns.command == "verify":
            _normalise_verify_args(ns, parser)
        return ns

    parser.parse_args = parse_args

    return parser


def _normalise_verify_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Collapse SS3.9.1's flag form and the older positional form into one
    set of attributes run_verify can rely on."""
    args.cobol_source = args.cobol_flag or args.cobol_source_pos
    args.java_candidate = args.java_flag or args.java_candidate_pos
    args.input_data = args.data_flag or args.input_data_pos
    missing = [
        name for name, value in (
            ("cobol source", args.cobol_source),
            ("java candidate", args.java_candidate),
            ("input data", args.input_data),
        ) if value is None
    ]
    if missing:
        parser.error(
            "verify requires " + ", ".join(missing)
            + " (positionally, or via --cobol/--java/--data)"
        )


def run_report(args: argparse.Namespace) -> int:
    """`weaver report <run_dir>` (BACKEND_PLAN.md §4.4 DC-5 target).

    Reads the same trace.jsonl / orchestrator_state.json a run directory
    holds and prints the identical Metrics object the backend's
    GET /runs/{id} serves -- both call weaver.agent.metrics.compute_metrics.
    """
    trace_path = args.run_dir / "trace.jsonl"
    state_path = args.run_dir / "orchestrator_state.json"
    m4_path = args.run_dir / "m4_baseline.json"
    # A run interrupted before its first unit finished (or still RUNNING)
    # has no orchestrator_state.json yet -- report that cleanly instead of
    # letting FileNotFoundError surface as a raw traceback (2026-08-12 audit).
    missing = [p for p in (trace_path, state_path) if not p.exists()]
    if missing:
        console.print(f"[red]Cannot compute metrics for {args.run_dir}: "
                       f"missing {', '.join(str(p.name) for p in missing)} "
                       f"(run may still be in progress or never started).[/red]")
        return 1
    metrics = compute_metrics(trace_path, state_path, m4_path)
    print(json.dumps(dataclasses.asdict(metrics), indent=2))
    return 0


def _compile_oracle(cobol_source: Path) -> Path:
    build_dir = cobol_source.parent / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    binary_path = build_dir / cobol_source.stem
    copybook_dir = cobol_source.parent / "copybooks"

    if not binary_path.exists() or binary_path.stat().st_mtime < cobol_source.stat().st_mtime:
        console.print(f"[cyan]Compiling oracle:[/cyan] {cobol_source}")
        subprocess.run(
            ["cobc", "-x", "-I", str(copybook_dir), "-o", str(binary_path), str(cobol_source)],
            check=True,
        )
    return binary_path


def _compile_candidate(java_candidate: Path) -> tuple[str, Path]:
    build_dir = java_candidate.parent / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    main_class = java_candidate.stem
    class_file = build_dir / f"{main_class}.class"

    if not class_file.exists() or class_file.stat().st_mtime < java_candidate.stat().st_mtime:
        console.print(f"[cyan]Compiling candidate:[/cyan] {java_candidate}")
        subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(build_dir), str(java_candidate)], check=True)
    return main_class, build_dir


def run_verify(args: argparse.Namespace) -> int:
    profile = _program_profile(args.cobol_source)
    output_filename = profile.output_filename if profile else OUTPUT_FILENAME
    report_layout = profile.report_layout if profile else REPORT_LAYOUT
    totals_layout = profile.totals_layout if profile else TOTALS_LAYOUT

    oracle_binary = _compile_oracle(args.cobol_source)
    main_class, classpath = _compile_candidate(args.java_candidate)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        oracle_dir = tmp_path / "oracle"
        candidate_dir = tmp_path / "candidate"

        oracle_result = run_oracle(oracle_binary, oracle_dir, args.input_data, output_filename)
        candidate_result = run_candidate(main_class, classpath, candidate_dir, args.input_data, output_filename)

    exit_codes_match = oracle_result.exit_code == candidate_result.exit_code

    oracle_lines = oracle_result.output_lines or []
    candidate_lines = candidate_result.output_lines or []

    with open(args.input_data) as f:
        input_lines = f.read().splitlines()

    total_records = max(len(oracle_lines), len(candidate_lines))
    report = Report(unit_id=args.cobol_source.stem, total_records=total_records, exit_codes_match=exit_codes_match)

    classifications = []
    for i in range(total_records):
        o_line = normalize_line_endings(oracle_lines[i]) if i < len(oracle_lines) else ""
        c_line = normalize_line_endings(candidate_lines[i]) if i < len(candidate_lines) else ""
        causing_input = input_lines[i] if i < len(input_lines) else None
        layout = report_layout if i < len(input_lines) else totals_layout

        div = compare_lines(i, o_line, c_line, causing_input, layout=layout)
        if div is not None:
            report.add_divergence(div)
            classifications.append(classify(div))

    class_summary = summarize(classifications) if classifications else {}

    _render_summary(report, class_summary)
    args.report.write_text(report.to_json(), encoding="utf-8")
    console.print(f"[cyan]Report written to[/cyan] {args.report}")

    return 0 if report.verified else 1


def _render_summary(report: Report, class_summary: dict) -> None:
    table = Table(title="Verification summary")
    table.add_column("Metric")
    table.add_column("Value")
    equivalence_rate = (
        100 * (report.total_records - report.divergence_count) / report.total_records
        if report.total_records else 0.0
    )
    table.add_row("Total records", str(report.total_records))
    table.add_row("Divergence count", str(report.divergence_count))
    table.add_row("Equivalence rate", f"{equivalence_rate:.1f}%")
    table.add_row("Exit codes match", str(report.exit_codes_match))
    table.add_row("Verified", str(report.verified))
    console.print(table)

    if class_summary:
        class_table = Table(title="Classification breakdown")
        class_table.add_column("Class")
        class_table.add_column("Count")
        class_table.add_column("Percentage")
        for cls, entry in class_summary.items():
            class_table.add_row(cls, str(entry["count"]), f"{entry['percentage']}%")
        console.print(class_table)

    if report.divergences:
        console.print("[yellow]First 3 divergences:[/yellow]")
        for div in report.divergences[:3]:
            console.print(
                f"  record={div.record_index} field={div.field_name} offset={div.byte_offset} "
                f"oracle={div.oracle_value!r} candidate={div.candidate_value!r} delta={div.numeric_delta} "
                f"input={div.causing_input_record!r}"
            )


def build_migrate_spec(args: argparse.Namespace) -> RunSpec:
    """Translate parsed `migrate` arguments into the RunSpec the orchestrator
    runs. Every flag must land in the spec -- a flag that parses but never
    reaches the orchestrator is the exact defect Task 1 fixed.
    """
    defaults = RunSpec.default()
    profile = _program_profile(args.program)
    return RunSpec(
        cobol_source=args.program,
        copybook_dir=args.copybook,
        input_data=args.data or (profile.input_data if profile else None) or defaults.input_data,
        out_dir=args.out,
        golden_output=(profile.golden_output if profile else None) or defaults.golden_output,
        scaffold_path=(profile.scaffold_path if profile else None) or defaults.scaffold_path,
        memory_store_path=defaults.memory_store_path,
        reference_body_path=(profile.reference_body_path if profile else None) or defaults.reference_body_path,
        reference_paragraph_id=(profile.reference_paragraph_id if profile else None)
                                or defaults.reference_paragraph_id,
        scaffold_spec=(profile.scaffold_spec if profile else None) or defaults.scaffold_spec,
        max_repairs=args.max_repairs,
        model=args.model,
        seed=args.seed,
        replay=args.replay,
    )


# SS3.9.4 [MUST]: colour coding for streamed unit status.
# Keys support both trace event nodes (present tense) and UnitResult status values (past tense).
_OUTCOME_COLOURS = {
    # Trace event nodes (orchestrator.py self._emit calls)
    "commit": "green",
    "escalate": "red",
    "cancel": "yellow",
    # UnitResult status values (_render_migrate_summary)
    "committed": "green",
    "escalated": "red",
}


def _stream_event(event: dict) -> None:
    """Render one TraceEvent as a coloured status line (SS3.9.4).

    This is a tee for an observer: it must never raise, because an exception
    here would propagate into the orchestrator's state machine and abort a
    run over a display concern.

    Colour is derived from the trace event's node value (e.g. "commit", "escalate",
    "cancel"), not from the freeform outcome string.
    """
    unit = event.get("unit", "?")
    node = event.get("node", "?")
    action = event.get("action", "")
    outcome = event.get("outcome", "")
    duration = event.get("duration_seconds", 0.0)

    colour = _OUTCOME_COLOURS.get(node, "cyan")

    try:
        console.print(
            f"[dim]{duration:>6.2f}s[/dim] "
            f"[bold]{unit}[/bold] "
            f"[{colour}]{node}[/{colour}]"
            f"{' · ' + action if action else ''}"
            f"{' · ' + str(outcome) if outcome else ''}"
        )
    except Exception:  # noqa: BLE001 - display must never break a run
        pass


def _render_migrate_summary(run_dir: Path, results: dict) -> None:
    table = Table(title="Migration summary")
    table.add_column("Unit")
    table.add_column("Status")
    table.add_column("Model calls")
    table.add_column("Memory hit")
    table.add_column("Duration")
    for unit_id, r in results.items():
        colour = _OUTCOME_COLOURS.get(r.status, "cyan")
        table.add_row(
            unit_id,
            f"[{colour}]{r.status}[/{colour}]",
            str(r.model_calls),
            str(r.memory_hit),
            f"{r.duration_seconds:.1f}s",
        )
    console.print(table)
    console.print(f"[cyan]Run directory:[/cyan] {run_dir}")
    console.print(f"[cyan]Metrics:[/cyan] weaver report {run_dir}")


def run_migrate(args: argparse.Namespace) -> int:
    """`weaver migrate` (SRS 3.9.1) -- drive the orchestrator from the terminal.

    Constructs the same Orchestrator backend/runs.py constructs and writes the
    same files into the run directory, so `weaver report <run_dir>` and the
    service's GET /runs/{id} read identical inputs (DC-5).
    """
    spec = build_migrate_spec(args)
    run_id = uuid.uuid4().hex
    run_dir = args.run_dir or (RUNS_ROOT / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    # NFR-D1 reproducibility record, written before the first unit executes.
    # Every value here actually influences the run -- see weaver/agent/runspec.py.
    (run_dir / "params.json").write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")

    cancel_requested = threading.Event()
    orchestrator = Orchestrator(
        spec=spec,
        trace_path=run_dir / "trace.jsonl",
        state_path=run_dir / "orchestrator_state.json",
        on_event=None if args.json else _stream_event,
        cancel_requested=cancel_requested,
    )

    try:
        results = orchestrator.run()
    except KeyboardInterrupt:
        # Cooperative: ask the orchestrator to stop at the next unit boundary
        # rather than dying mid-unit (orchestrator.py: "never kill mid-unit,
        # which would leave containers running and state inconsistent").
        cancel_requested.set()
        console.print("[yellow]Cancellation requested; stopping at unit boundary.[/yellow]")
        return 130

    statuses = {r.status for r in results.values()}
    exit_code = 0 if statuses <= {"committed"} else 1

    if args.json:
        print(json.dumps({
            "run_dir": str(run_dir),
            "units": {uid: dataclasses.asdict(r) for uid, r in results.items()},
            "output_path": str(orchestrator.output_path) if orchestrator.output_path else None,
            "exit_code": exit_code,
        }, indent=2, default=str))
    else:
        _render_migrate_summary(run_dir, results)
        if orchestrator.output_path:
            console.print(f"[green]Migrated Java written to {orchestrator.output_path}[/green]")

    return exit_code


def run_connectors(args: argparse.Namespace) -> int:
    from weaver.agent.connector_codegen import generate_connectors
    from weaver.agent.connector_map import UnsupportedConnectorError, map_directives
    from weaver.cobol.mock_directives import UnsupportedMockDirectiveError, find_mock_directives
    from weaver.cobol.subprogram import load_subprogram

    try:
        model = load_subprogram(args.cobol_source)
        full_source = model.source_path.read_text(encoding="utf-8")
        directives = find_mock_directives(full_source)
        if not directives:
            console.print(f"[yellow]{args.cobol_source} has no EXEC SQL/EXEC CICS directives -- nothing to generate.[/yellow]")
            return 0
        bindings = map_directives(directives)
    except (UnsupportedMockDirectiveError, UnsupportedConnectorError) as e:
        console.print(f"[red]{e}[/red]")
        return 1

    out_dir = args.out_dir or Path("generated") / "connectors" / model.program_id
    written = generate_connectors(model, bindings, out_dir)

    console.print(f"[green]Generated {len(written)} artefact(s) for {model.program_id} in {out_dir}:[/green]")
    for path in written:
        console.print(f"  {path}")
    return 0


def run_dedup(args: argparse.Namespace) -> int:
    from weaver.agent.class_designer import discover_shared_layouts
    from weaver.agent.shared_class_codegen import generate_shared_helpers, generate_shared_record_class

    if not args.cobol_dir.is_dir():
        console.print(f"[red]{args.cobol_dir} is not a directory.[/red]")
        return 1

    plan = discover_shared_layouts(args.cobol_dir)
    if not plan.shared:
        console.print(f"[yellow]No structurally identical layouts shared across 2+ programs found under {args.cobol_dir}.[/yellow]")
        if plan.skipped:
            console.print(f"[yellow]{len(plan.skipped)} source file(s) could not be parsed as a file-based program and were skipped.[/yellow]")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = [args.out_dir / "CobolShared.java"]
    written[0].write_text(generate_shared_helpers(), encoding="utf-8")

    console.print(f"[green]Found {len(plan.shared)} shared layout(s) in {args.cobol_dir}:[/green]")
    for shared in plan.shared:
        source = generate_shared_record_class(shared.class_name, shared.layout, shared.layout_kind)
        path = args.out_dir / f"{shared.class_name}.java"
        path.write_text(source, encoding="utf-8")
        written.append(path)
        programs = ", ".join(sorted({u.program_id for u in shared.used_by}))
        console.print(f"  {shared.class_name} ({shared.layout_kind}) -- used by {programs} -> {path}")

    if plan.skipped:
        console.print(f"[yellow]{len(plan.skipped)} source file(s) skipped (not a file-based program).[/yellow]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        _normalise_verify_args(args, parser)
        return run_verify(args)
    if args.command == "report":
        return run_report(args)
    if args.command == "migrate":
        return run_migrate(args)
    if args.command == "connectors":
        return run_connectors(args)
    if args.command == "dedup":
        return run_dedup(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
