"""Phase BB1 acceptance tests (proactive generalization of
weaver/cobol/frontend.py beyond its original one-input/one-output scope) --
fixtures/cobol_multiinput/multiinput.cob reads two input files in lockstep
by position (weaver.agent.scaffold.ScaffoldSpec.extra_input_files' own
comment explains why this is a deliberately narrower subshape than a full
COBOL MATCH-MERGE, not a general join).

Every existing fixture's frontend/scaffold regression coverage
(tests/test_cobol_frontend.py, tests/test_scaffold_redefines.py) already
proves this phase changed nothing for single-input-file programs -- these
tests are additive, covering only the new N>1 shape.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.assemble import assemble
from weaver.agent.scaffold import generate, java_signature
from weaver.cobol.frontend import UnsupportedProgramError, load_program, to_scaffold_spec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol_multiinput" / "multiinput.cob"
DATA_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "data_multiinput"

# Hand-computed from the real fixed-width PIC 9(7)V99/9(5)V99 encoding in
# fixtures/data_multiinput/{master,adjust}.dat -- record i's RL-ADJUSTED is
# MST-BALANCE[i] + ADJ-AMOUNT[i]:
#   112233.45 +   100.00 = 112333.45
#   500000.00 +     5.50 = 500005.50
#        0.00 + 99999.99 =  99999.99
# Totals accumulate all three: 112333.45 + 500005.50 + 99999.99 = 712338.94
CORRECT_BODY = "        ws.adjusted = ar.balance.add(ar2.amount);"


def test_load_program_parses_two_input_files():
    model = load_program(FIXTURE)
    assert model.input_file == "master.dat"
    assert model.extra_input_files == ("adjust.dat",)
    assert [f.name for f in model.input_layout] == ["MST-ID", "MST-BALANCE"]
    assert [f.name for f in model.extra_input_layouts[0]] == ["ADJ-ID", "ADJ-AMOUNT"]


def test_load_program_derives_ctor_maps_from_both_files():
    model = load_program(FIXTURE)
    assert model.report_ctor_map["RL-ID"] == "ar.id"
    assert model.report_ctor_map["RL-BALANCE"] == "ar.balance"
    # RL-ADJUSTED comes from ws.adjusted (the synthesis unit's own COMPUTE,
    # combining both records) -- not a plain MOVE from either input file.
    assert model.report_ctor_map["RL-ADJUSTED"] == "ws.adjusted"
    assert model.accumulator_field == "totalAdjusted"
    assert model.per_record_field == "adjusted"


def test_java_signature_includes_the_extra_record_parameter():
    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    assert java_signature(spec) == "static void processRecord(AccountRecord ar, InputRecord2 ar2, WorkingStorage ws)"


def test_a_file_read_by_key_lookup_instead_of_lockstep_is_rejected(tmp_path):
    # Same two-file shape, but the driver only READs the second file
    # conditionally inside an EVALUATE-by-key branch structure this
    # phase's lockstep-only subshape does not model -- MASTER-FILE gets
    # read twice, ADJUST-FILE zero times in the (only) recognized READ
    # scan, which must raise rather than silently guess a join order.
    bad_source = FIXTURE.read_text(encoding="utf-8").replace(
        "READ ADJUST-FILE", "READ MASTER-FILE"
    )
    bad_path = tmp_path / "bad.cob"
    bad_path.write_text(bad_source, encoding="utf-8")
    with pytest.raises(UnsupportedProgramError):
        load_program(bad_path)


requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_candidate_scaffold_compiles_and_produces_correct_output(tmp_path):
    """Real javac compile + real java run of the generated 2-input-file
    scaffold against the real committed fixture data, with a hand-written
    (known-correct, not LLM-synthesized) body -- proves the frontend ->
    scaffold -> execution path this phase built, end to end. This is
    candidate self-consistency, not a byte-for-byte oracle comparison --
    see test_candidate_matches_real_gnucobol_oracle below for that,
    gated on a real cobc being reachable."""
    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    assembled = assemble(source, {spec.paragraph_id: CORRECT_BODY})
    (tmp_path / "Scaffold.java").write_text(assembled, encoding="utf-8")

    build_dir = tmp_path / "build"
    compiled = subprocess.run(
        ["javac", "-d", str(build_dir), str(tmp_path / "Scaffold.java")],
        capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    import shutil as _shutil
    _shutil.copy2(DATA_DIR / "master.dat", run_dir / "master.dat")
    _shutil.copy2(DATA_DIR / "adjust.dat", run_dir / "adjust.dat")

    ran = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"], cwd=run_dir, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr

    output = (run_dir / "multiinput.out").read_text(encoding="utf-8")
    lines = output.splitlines()
    assert len(lines) == 4  # 3 detail + 1 totals
    assert lines[0].split()[-2:] == ["112233.45", "112333.45"]
    assert lines[1].split()[-2:] == ["500000.00", "500005.50"]
    assert lines[2].split()[-2:] == ["0.00", "99999.99"]
    assert lines[3].strip().endswith("712338.94")


@requires_javac
def test_record_count_mismatch_between_files_raises_at_runtime(tmp_path):
    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    assembled = assemble(source, {spec.paragraph_id: CORRECT_BODY})
    (tmp_path / "Scaffold.java").write_text(assembled, encoding="utf-8")

    build_dir = tmp_path / "build"
    subprocess.run(["javac", "-d", str(build_dir), str(tmp_path / "Scaffold.java")],
                    check=True, capture_output=True, text=True, timeout=30)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "master.dat").write_text((DATA_DIR / "master.dat").read_text(encoding="utf-8"), encoding="utf-8")
    # Only one adjust record -- deliberately fewer than master's three.
    adjust_lines = (DATA_DIR / "adjust.dat").read_text(encoding="utf-8").splitlines()
    (run_dir / "adjust.dat").write_text(adjust_lines[0] + "\n", encoding="utf-8")

    ran = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"], cwd=run_dir, capture_output=True, text=True, timeout=30)
    assert ran.returncode != 0
    assert "record count" in ran.stderr


requires_full_toolchain = pytest.mark.skipif(
    shutil.which("cobc") is None or shutil.which("javac") is None,
    reason="requires cobc and javac on PATH (same convention as test_acceptance.py)",
)


@requires_full_toolchain
def test_candidate_matches_real_gnucobol_oracle(tmp_path):
    """The real byte-for-byte proof: compiles fixtures/cobol_multiinput/
    multiinput.cob with real cobc, runs it against the real committed
    data files, and diffs its real output against the candidate scaffold's
    output line-for-line -- the same comparison contract
    (weaver.comparison.compare_lines) every other fixture in this repo is
    held to, never a second equivalence rule."""
    from weaver.comparison import compare_lines, normalize_line_endings

    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    (oracle_dir / "multiinput.cob").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(DATA_DIR / "master.dat", oracle_dir / "master.dat")
    shutil.copy2(DATA_DIR / "adjust.dat", oracle_dir / "adjust.dat")
    compiled = subprocess.run(
        ["cobc", "-x", "multiinput.cob", "-o", "multiinput"],
        cwd=oracle_dir, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"
    oracle_run = subprocess.run(
        ["./multiinput"] if shutil.which("wsl") is None else ["multiinput.exe"],
        cwd=oracle_dir, capture_output=True, text=True, timeout=30,
    )
    assert oracle_run.returncode == 0, f"{oracle_run.stdout}\n{oracle_run.stderr}"
    oracle_lines = normalize_line_endings((oracle_dir / "multiinput.out").read_text(encoding="utf-8")).splitlines()

    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    assembled = assemble(source, {spec.paragraph_id: CORRECT_BODY})
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "Scaffold.java").write_text(assembled, encoding="utf-8")
    build_dir = candidate_dir / "build"
    subprocess.run(["javac", "-d", str(build_dir), str(candidate_dir / "Scaffold.java")],
                    check=True, capture_output=True, text=True, timeout=30)
    shutil.copy2(DATA_DIR / "master.dat", candidate_dir / "master.dat")
    shutil.copy2(DATA_DIR / "adjust.dat", candidate_dir / "adjust.dat")
    candidate_run = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"],
                                    cwd=candidate_dir, capture_output=True, text=True, timeout=30)
    assert candidate_run.returncode == 0, candidate_run.stderr
    candidate_lines = normalize_line_endings((candidate_dir / "multiinput.out").read_text(encoding="utf-8")).splitlines()

    assert len(oracle_lines) == len(candidate_lines)
    divergences = [
        compare_lines(i, o, c, None, layout=spec.report_layout if i < 3 else spec.totals_layout)
        for i, (o, c) in enumerate(zip(oracle_lines, candidate_lines))
    ]
    divergences = [d for d in divergences if d is not None]
    assert divergences == [], divergences
