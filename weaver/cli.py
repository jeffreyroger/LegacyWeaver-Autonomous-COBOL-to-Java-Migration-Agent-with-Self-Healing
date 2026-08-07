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
from pathlib import Path

from rich.console import Console
from rich.table import Table

from weaver.agent.metrics import compute_metrics
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

    verify = sub.add_parser("verify", help="Verify a Java candidate against a COBOL oracle")
    verify.add_argument("cobol_source", type=Path)
    verify.add_argument("java_candidate", type=Path)
    verify.add_argument("input_data", type=Path)
    verify.add_argument("--report", type=Path, default=Path("report.json"))

    report_cmd = sub.add_parser("report", help="Print metrics computed from a run directory's trace/state")
    report_cmd.add_argument("run_dir", type=Path)

    # SRS 3.9.1: weaver migrate <program.cbl> [--copybook DIR] [--data FILE]
    #            [--out DIR] [--max-repairs 3] [--model qwen2.5-coder:7b] [--seed 42]
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

    return parser


def run_report(args: argparse.Namespace) -> int:
    """`weaver report <run_dir>` (BACKEND_PLAN.md §4.4 DC-5 target).

    Reads the same trace.ndjson / orchestrator_state.json a run directory
    holds and prints the identical Metrics object the backend's
    GET /runs/{id} serves -- both call weaver.agent.metrics.compute_metrics.
    """
    trace_path = args.run_dir / "trace.ndjson"
    state_path = args.run_dir / "orchestrator_state.json"
    m4_path = args.run_dir / "m4_baseline.json"
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
        subprocess.run(["javac", "-d", str(build_dir), str(java_candidate)], check=True)
    return main_class, build_dir


def run_verify(args: argparse.Namespace) -> int:
    oracle_binary = _compile_oracle(args.cobol_source)
    main_class, classpath = _compile_candidate(args.java_candidate)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        oracle_dir = tmp_path / "oracle"
        candidate_dir = tmp_path / "candidate"

        oracle_result = run_oracle(oracle_binary, oracle_dir, args.input_data, OUTPUT_FILENAME)
        candidate_result = run_candidate(main_class, classpath, candidate_dir, args.input_data, OUTPUT_FILENAME)

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
        layout = REPORT_LAYOUT if i < len(input_lines) else TOTALS_LAYOUT

        div = compare_lines(i, o_line, c_line, causing_input, layout=layout)
        if div is not None:
            report.add_divergence(div)
            classifications.append(classify(div))

    class_summary = summarize(classifications) if classifications else {}

    _render_summary(report, class_summary)
    args.report.write_text(report.to_json())
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
    return RunSpec(
        cobol_source=args.program,
        copybook_dir=args.copybook,
        input_data=args.data or defaults.input_data,
        out_dir=args.out,
        golden_output=defaults.golden_output,
        scaffold_path=defaults.scaffold_path,
        memory_store_path=defaults.memory_store_path,
        max_repairs=args.max_repairs,
        model=args.model,
        seed=args.seed,
        replay=args.replay,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        return run_verify(args)
    if args.command == "report":
        return run_report(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
