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


def test_migrate_writes_an_fr_8_1_run_dir(tmp_path, monkeypatch):
    """FR-8.1: trace lands at <run_dir>/trace.jsonl, and the directory is
    exactly what `weaver report` reads."""
    import weaver.cli as cli_mod

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.trace_path = kwargs["trace_path"]
            self.state_path = kwargs["state_path"]
            self.results = {}

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


def test_stream_event_emits_colour_coded_status(capsys):
    """SS3.9.4 [MUST]: stream unit status with colour coding."""
    from weaver.cli import _stream_event

    _stream_event({
        "timestamp": 1.0, "unit": "PROCESS-RECORD", "node": "repair",
        "action": "patch", "duration_seconds": 0.4, "model_calls": 1,
        "tokens": 120, "memory_hit": False, "outcome": "committed",
    })
    out = capsys.readouterr().out
    assert "PROCESS-RECORD" in out
    assert "repair" in out


def test_stream_event_never_raises_on_a_partial_event(capsys):
    """The callback is a tee for an observer and must never break a run --
    a malformed or partial event must not propagate an exception into the
    orchestrator's state machine."""
    from weaver.cli import _stream_event

    _stream_event({"unit": "P1"})  # every other key missing
    assert capsys.readouterr().out  # produced something, raised nothing
