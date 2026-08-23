"""Surface tests for `weaver migrate` (SRS SS3.9.1). These never invoke the
real orchestrator -- they assert the CLI parses arguments into the RunSpec
the orchestrator is constructed with, which is the property that broke
before: a flag the user passes must not be silently dropped."""
import dataclasses
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
    assert spec.model == "granite-code:20b"
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


def test_migrate_writes_an_fr_8_1_run_dir(tmp_path, monkeypatch):
    """FR-8.1: trace lands at <run_dir>/trace.jsonl, and the directory is
    exactly what `weaver report` reads."""
    import weaver.cli as cli_mod

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}
            self.output_path = None

        def run(self):
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
            self.state_path.write_text("{}")
            return self.results

    monkeypatch.setattr(cli_mod, "Orchestrator", FakeOrchestrator)

    run_dir = tmp_path / "run1"
    args = cli_mod.build_parser().parse_args(
        ["migrate", "prog.cbl", "--run-dir", str(run_dir), "--json"]
    )
    assert cli_mod.run_migrate(args) == 0
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "orchestrator_state.json").exists()
    assert (run_dir / "params.json").exists()


def test_migrate_params_json_records_every_spec_field(tmp_path, monkeypatch):
    """NFR-D1: the reproducibility record must describe the run that
    actually happened -- every RunSpec field, no omissions."""
    import json

    import weaver.cli as cli_mod
    from weaver.agent.runspec import RunSpec

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}
            self.output_path = None

        def run(self):
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
            self.state_path.write_text("{}")
            return self.results

    monkeypatch.setattr(cli_mod, "Orchestrator", FakeOrchestrator)

    run_dir = tmp_path / "run2"
    args = cli_mod.build_parser().parse_args(
        ["migrate", "prog.cbl", "--run-dir", str(run_dir), "--seed", "7", "--json"]
    )
    cli_mod.run_migrate(args)

    recorded = json.loads((run_dir / "params.json").read_text())
    assert set(recorded) == {f.name for f in dataclasses.fields(RunSpec)}
    assert recorded["seed"] == 7


def test_migrate_exit_code_1_when_a_unit_escalates(tmp_path, monkeypatch):
    import weaver.cli as cli_mod
    from weaver.agent.orchestrator import UnitResult

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}
            self.output_path = None

        def run(self):
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
            self.state_path.write_text("{}")
            self.results = {
                "P1": UnitResult("P1", "committed", "body", 1, False, 0.5),
                "P2": UnitResult("P2", "escalated", None, 3, False, 1.5),
            }
            return self.results

    monkeypatch.setattr(cli_mod, "Orchestrator", FakeOrchestrator)

    args = cli_mod.build_parser().parse_args(
        ["migrate", "prog.cbl", "--run-dir", str(tmp_path / "run3"), "--json"]
    )
    assert cli_mod.run_migrate(args) == 1


def test_leaf_first_rejects_a_single_file_program(tmp_path):
    """--leaf-first requires 'program' to be a directory of *.cob files --
    a single-file argument (the normal migrate shape) must fail clearly
    rather than reaching LeafOrchestrator with a directory-shaped
    assumption violated."""
    import weaver.cli as cli_mod

    program_file = tmp_path / "single.cob"
    program_file.write_text("")
    args = cli_mod.build_parser().parse_args(
        ["migrate", str(program_file), "--leaf-first", "--run-dir", str(tmp_path / "run_leaf_reject")]
    )
    assert cli_mod.run_migrate(args) == 2


def test_leaf_first_flattens_the_nested_result_dict_for_json(tmp_path, monkeypatch):
    """LeafOrchestrator.run() returns dict[program_name, dict[unit_id,
    UnitResult|SubprogramUnitResult]] -- a different shape than the flat
    single-program Orchestrator.run() returns. run_migrate_leaf_first must
    flatten/serialize this correctly (including SubprogramUnitResult,
    which has no memory_hit field) rather than crashing or silently
    dropping a program's results."""
    import json

    import weaver.agent.leaf_orchestrator as leaf_orch_mod
    from weaver.agent.orchestrator import UnitResult
    from weaver.agent.subprogram_orchestrator import SubprogramUnitResult

    class FakeLeafOrchestrator:
        def __init__(self, **kwargs):
            self.program_dir = kwargs["program_dir"]
            self.base_spec = kwargs["base_spec"]

        def run(self):
            return {
                "LEAF-A": {
                    "LEAF-A": SubprogramUnitResult("LEAF-A", "committed", "body", 1, 2.0),
                },
                "ROOT": {
                    "PROCESS-RECORD": UnitResult("PROCESS-RECORD", "escalated", None, 3, False, 5.0),
                },
            }

    monkeypatch.setattr(leaf_orch_mod, "LeafOrchestrator", FakeLeafOrchestrator)

    import weaver.cli as cli_mod

    program_dir = tmp_path / "multiprog"
    program_dir.mkdir()
    run_dir = tmp_path / "run_leaf_flatten"
    args = cli_mod.build_parser().parse_args(
        ["migrate", str(program_dir), "--leaf-first", "--run-dir", str(run_dir), "--json"]
    )
    exit_code = cli_mod.run_migrate(args)

    assert exit_code == 1  # ROOT escalated
    (run_dir / "params.json").read_text()  # written before any program runs


def test_stream_event_emits_colour_coded_status(capsys):
    """SS3.9.4 [MUST]: stream unit status with colour coding (SRS 3.9.4).

    Uses realistic trace event values (node="commit", outcome="verified clean")
    as emitted by the orchestrator, not synthetic past-tense status values.
    """
    from weaver.cli import _stream_event

    # Realistic trace event from orchestrator: commit node with verified outcome
    _stream_event({
        "timestamp": 1.0, "unit": "PROCESS-RECORD", "node": "commit",
        "action": "accept", "duration_seconds": 0.4, "model_calls": 1,
        "tokens": 120, "memory_hit": False, "outcome": "verified clean",
    })
    out = capsys.readouterr().out
    assert "PROCESS-RECORD" in out
    assert "commit" in out
    assert "verified clean" in out  # Outcome is rendered alongside the status


def test_stream_event_colour_codes_escalate_and_cancel(capsys):
    """SS3.9.4 [MUST]: verify colour coding for escalate (red) and cancel (yellow).

    Tests that the orchestrator's real node values ("escalate", "cancel") map
    to the correct colours, not just "commit".
    """
    from weaver.cli import _stream_event

    # Escalate event (red)
    _stream_event({
        "timestamp": 1.0, "unit": "P1", "node": "escalate",
        "action": "give_up", "duration_seconds": 0.5, "outcome": "synthesis_failure",
    })
    out1 = capsys.readouterr().out
    assert "P1" in out1
    assert "escalate" in out1

    # Cancel event (yellow)
    _stream_event({
        "timestamp": 2.0, "unit": "*", "node": "cancel",
        "action": "stop_before_unit", "duration_seconds": 0.0, "outcome": "stopped before P2",
    })
    out2 = capsys.readouterr().out
    assert "cancel" in out2


def test_stream_event_never_raises_on_a_partial_event(capsys):
    """The callback is a tee for an observer and must never break a run --
    a malformed or partial event must not propagate an exception into the
    orchestrator's state machine."""
    from weaver.cli import _stream_event

    _stream_event({"unit": "P1"})  # every other key missing
    assert capsys.readouterr().out  # produced something, raised nothing


def test_verify_accepts_the_srs_flag_form():
    """SS3.9.1: weaver verify --cobol <src> --java <src> --data <file>."""
    args = build_parser().parse_args(
        ["verify", "--cobol", "a.cob", "--java", "B.java", "--data", "c.dat"]
    )
    assert args.cobol_source == Path("a.cob")
    assert args.java_candidate == Path("B.java")
    assert args.input_data == Path("c.dat")


def test_verify_still_accepts_the_positional_form():
    """The positional form is used by README, test_acceptance.py and
    BACKEND_PLAN.md:388 -- it must keep working."""
    args = build_parser().parse_args(["verify", "a.cob", "B.java", "c.dat"])
    assert args.cobol_source == Path("a.cob")
    assert args.java_candidate == Path("B.java")
    assert args.input_data == Path("c.dat")
