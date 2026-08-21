"""Phase BB4 acceptance tests (proactive generalization of
weaver/cobol/frontend.py beyond its original one-input/one-output scope)
-- fixtures/cobol_validation/validation.cob is a no-output-file
(validation-only) program: it reads every record, accumulates a running
balance total, and ends with exactly one single-argument DISPLAY of that
total. See weaver/agent/scaffold.py's `summary_accumulator_width` comment
for the exact (deliberately narrow) subshape.

Every existing fixture's frontend/scaffold regression coverage
(tests/test_cobol_frontend.py, tests/test_scaffold_redefines.py) already
proves this phase changed nothing for programs with a real output file --
these tests are additive, covering only the new no-output-file shape.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.assemble import assemble
from weaver.agent.scaffold import generate
from weaver.cobol.frontend import UnsupportedProgramError, load_program, to_scaffold_spec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol_validation" / "validation.cob"
DATA_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "data_validation"

# Hand-computed from the real PIC 9(7)V99 encoding in
# fixtures/data_validation/accounts4.dat: 112233.45 + 500000.00 + 0.00 =
# 612233.45 -> raw 11-digit zero-padded (PIC 9(9)V99): "00061223345"
CORRECT_BODY = "        ws.balanceCopy = ar.balance;"


def test_load_program_parses_a_no_output_file_program():
    model = load_program(FIXTURE)
    assert model.output_file == ""
    assert model.report_layout == ()
    assert model.accumulator_field == "totalBalance"
    assert model.per_record_field == "balanceCopy"
    assert model.summary_accumulator_width == 11
    assert model.summary_accumulator_scale == 2


def test_a_program_with_no_display_summary_is_rejected(tmp_path):
    bad_source = FIXTURE.read_text(encoding="utf-8").replace("DISPLAY WS-TOTAL-BALANCE.\n", "")
    bad_path = tmp_path / "bad.cob"
    bad_path.write_text(bad_source, encoding="utf-8")
    with pytest.raises(UnsupportedProgramError):
        load_program(bad_path)


def test_a_signed_summary_accumulator_is_rejected(tmp_path):
    bad_source = FIXTURE.read_text(encoding="utf-8").replace("PIC 9(9)V99 VALUE ZERO.", "PIC S9(9)V99 VALUE ZERO.")
    bad_path = tmp_path / "bad.cob"
    bad_path.write_text(bad_source, encoding="utf-8")
    with pytest.raises(UnsupportedProgramError):
        load_program(bad_path)


requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_generated_scaffold_has_no_report_line_class():
    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    assert "OUTPUT_FILE" not in source
    assert "class ReportLine" not in source
    assert "System.out.println" in source


@requires_javac
def test_candidate_scaffold_compiles_and_prints_correct_total(tmp_path):
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
    shutil.copy2(DATA_DIR / "accounts4.dat", run_dir / "accounts4.dat")
    ran = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"], cwd=run_dir, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "00061223345"


requires_full_toolchain = pytest.mark.skipif(
    shutil.which("cobc") is None or shutil.which("javac") is None,
    reason="requires cobc and javac on PATH (same convention as test_acceptance.py)",
)


@requires_full_toolchain
def test_candidate_matches_real_gnucobol_oracle(tmp_path):
    """Real byte-for-byte proof: compiles fixtures/cobol_validation/
    validation.cob with real cobc, runs it against the real committed
    data file, and diffs its real stdout against the candidate scaffold's
    stdout -- exact string equality, the strongest form of the same
    comparison contract every other fixture in this repo is held to."""
    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    (oracle_dir / "validation.cob").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(DATA_DIR / "accounts4.dat", oracle_dir / "accounts4.dat")
    compiled = subprocess.run(
        ["cobc", "-x", "validation.cob", "-o", "validation"],
        cwd=oracle_dir, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"
    oracle_run = subprocess.run(["./validation"], cwd=oracle_dir, capture_output=True, text=True, timeout=30)
    assert oracle_run.returncode == 0, f"{oracle_run.stdout}\n{oracle_run.stderr}"

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
    shutil.copy2(DATA_DIR / "accounts4.dat", candidate_dir / "accounts4.dat")
    candidate_run = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"],
                                    cwd=candidate_dir, capture_output=True, text=True, timeout=30)
    assert candidate_run.returncode == 0, candidate_run.stderr

    assert oracle_run.stdout.strip() == candidate_run.stdout.strip()
