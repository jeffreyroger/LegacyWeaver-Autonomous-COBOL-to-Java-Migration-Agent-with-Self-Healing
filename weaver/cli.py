"""Single `verify` command (Step F1/F2; FR-15).

    weaver verify <cobol_source> <java_candidate> <input_data> [--report OUT]

Compiles both programs if needed, runs the differential comparison,
classifies divergences, renders a terminal summary, writes the JSON
report, and exits 0 if verified else 1.

TODO(Step F2): wire up compilation (cobc / javac) once fixtures exist.
TODO(Step F2): wire up execution -> comparison -> classification pipeline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weaver", description="LegacyWeaver differential verification harness")
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="Verify a Java candidate against a COBOL oracle")
    verify.add_argument("cobol_source", type=Path)
    verify.add_argument("java_candidate", type=Path)
    verify.add_argument("input_data", type=Path)
    verify.add_argument("--report", type=Path, default=Path("report.json"))

    return parser


def run_verify(args: argparse.Namespace) -> int:
    # TODO: compile oracle (cobc) if absent/stale
    # TODO: compile candidate (javac) if absent/stale
    # TODO: execute both (weaver.execution), compare (weaver.comparison),
    #       classify (weaver.classification), build Report (weaver.report)
    console.print("[yellow]weaver verify is scaffolded but not yet implemented (Phase D/F).[/yellow]")
    console.print(f"  cobol_source = {args.cobol_source}")
    console.print(f"  java_candidate = {args.java_candidate}")
    console.print(f"  input_data = {args.input_data}")
    console.print(f"  report -> {args.report}")

    table = Table(title="Verification summary (placeholder)")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Total records", "-")
    table.add_row("Divergence count", "-")
    table.add_row("Equivalence rate", "-")
    console.print(table)

    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        return run_verify(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
