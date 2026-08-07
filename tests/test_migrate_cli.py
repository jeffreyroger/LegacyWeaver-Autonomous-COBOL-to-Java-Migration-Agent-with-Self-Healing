"""Surface tests for `weaver migrate` (SRS SS3.9.1). These never invoke the
real orchestrator -- they assert the CLI parses arguments into the RunSpec
the orchestrator is constructed with, which is the property that broke
before: a flag the user passes must not be silently dropped."""
from pathlib import Path

from weaver.cli import build_migrate_spec, build_parser


def test_migrate_takes_a_positional_program():
    args = build_parser().parse_args(["migrate", "prog.cbl"])
    assert args.command == "migrate"
    assert args.program == Path("prog.cbl")


def test_migrate_defaults_match_srs_3_9_1():
    args = build_parser().parse_args(["migrate", "prog.cbl"])
    spec = build_migrate_spec(args)
    assert spec.max_repairs == 3
    assert spec.model == "qwen2.5-coder:7b"
    assert spec.seed == 42
    assert spec.replay is False


def test_migrate_flags_reach_the_spec():
    args = build_parser().parse_args([
        "migrate", "prog.cbl",
        "--copybook", "cb/",
        "--data", "custom/input.dat",
        "--out", "outdir/",
        "--max-repairs", "5",
        "--model", "qwen2.5-coder:14b",
        "--seed", "7",
    ])
    spec = build_migrate_spec(args)
    assert spec.cobol_source == Path("prog.cbl")
    assert spec.copybook_dir == Path("cb/")
    assert spec.input_data == Path("custom/input.dat")
    assert spec.out_dir == Path("outdir/")
    assert spec.max_repairs == 5
    assert spec.model == "qwen2.5-coder:14b"
    assert spec.seed == 7


def test_existing_commands_still_parse():
    """migrate must not disturb the existing surface (SS3.9.4: the terminal
    path stands alone)."""
    p = build_parser()
    assert p.parse_args(["verify", "a.cob", "B.java", "c.dat"]).command == "verify"
    assert p.parse_args(["report", "runs/abc"]).command == "report"
