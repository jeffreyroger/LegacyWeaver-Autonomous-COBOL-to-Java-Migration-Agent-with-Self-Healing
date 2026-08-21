"""Phase BB3 acceptance tests (proactive generalization of
weaver/cobol/frontend.py beyond its original one-input/one-output/one-unit
scope) -- fixtures/cobol_multiunit/multiunit.cob PERFORMs two distinct
business-logic paragraphs once each per record: VALIDATE-RECORD sets a
validity code, COMPUTE-FEE computes the fee and writes the report line.
Both units are independently synthesizable (their own
// PARAGRAPH:<id>:BEGIN/:END markers).

Every existing fixture's frontend/scaffold regression coverage
(tests/test_cobol_frontend.py, tests/test_scaffold_redefines.py) already
proves this phase changed nothing for single-unit programs -- these tests
are additive, covering only the new N>1 shape.

Disclosed scope, same posture as BB1/BB2: proven at the frontend+scaffold+
javac layer with a hand-written body; wiring N units into the live
synthesis/repair-loop Orchestrator (which still assumes one unit per
program) is further work.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.assemble import assemble
from weaver.agent.scaffold import generate, java_signature
from weaver.cobol.frontend import UnsupportedProgramError, load_program, to_scaffold_spec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol_multiunit" / "multiunit.cob"
DATA_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "data_multiunit"

# Hand-computed from the real PIC 9(7)V99 encoding in
# fixtures/data_multiunit/accounts3.dat:
#   record 1: balance 112233.45 > 0 -> code 1.00; fee = 112233.45*0.01 = 1122.33
#   record 2: balance 500000.00 > 0 -> code 1.00; fee = 5000.00
#   record 3: balance      0.00     -> code 0.00; fee =    0.00
# Total fee: 1122.33 + 5000.00 + 0.00 = 6122.33
CORRECT_BODIES = {
    "VALIDATE-RECORD": (
        "        ws.validCode = ar.balance.compareTo(java.math.BigDecimal.ZERO) > 0 "
        '? new java.math.BigDecimal("1.00") : new java.math.BigDecimal("0.00");'
    ),
    "COMPUTE-FEE": (
        '        ws.fee = ar.balance.multiply(new java.math.BigDecimal("0.01000"))'
        ".setScale(2, java.math.RoundingMode.DOWN);"
    ),
}


def test_load_program_parses_two_unit_paragraphs():
    model = load_program(FIXTURE)
    assert model.paragraph_id == "VALIDATE-RECORD"
    assert model.extra_paragraph_ids == ("COMPUTE-FEE",)
    assert model.extra_paragraph_methods == ("computeFee",)


def test_report_ctor_map_is_derived_from_both_units_combined():
    model = load_program(FIXTURE)
    # RL-ID/RL-CODE come from VALIDATE-RECORD, RL-FEE from COMPUTE-FEE --
    # both resolved into one merged ctor map.
    assert model.report_ctor_map == {"RL-ID": "ar.id", "RL-CODE": "ws.validCode", "RL-FEE": "ws.fee"}
    assert model.accumulator_field == "totalFee"
    assert model.per_record_field == "fee"


def test_java_signature_is_the_same_shape_for_every_unit():
    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    assert java_signature(spec) == "static void validateRecord(AccountRecord ar, WorkingStorage ws)"
    assert java_signature(spec, spec.extra_paragraph_methods[0]) == "static void computeFee(AccountRecord ar, WorkingStorage ws)"


def test_a_unit_not_performed_by_the_driver_is_rejected(tmp_path):
    # COMPUTE-FEE is never PERFORMed anywhere -- the driver only performs
    # VALIDATE-RECORD -- which must be rejected, not silently ignored.
    bad_source = FIXTURE.read_text(encoding="utf-8").replace(
        "PERFORM COMPUTE-FEE\n", ""
    )
    bad_path = tmp_path / "bad.cob"
    bad_path.write_text(bad_source, encoding="utf-8")
    with pytest.raises(UnsupportedProgramError):
        load_program(bad_path)


requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_candidate_scaffold_compiles_and_produces_correct_output(tmp_path):
    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    bodies = {spec.paragraph_id: CORRECT_BODIES["VALIDATE-RECORD"],
              spec.extra_paragraph_ids[0]: CORRECT_BODIES["COMPUTE-FEE"]}
    assembled = assemble(source, bodies)
    (tmp_path / "Scaffold.java").write_text(assembled, encoding="utf-8")

    build_dir = tmp_path / "build"
    compiled = subprocess.run(
        ["javac", "-d", str(build_dir), str(tmp_path / "Scaffold.java")],
        capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy2(DATA_DIR / "accounts3.dat", run_dir / "accounts3.dat")
    ran = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"], cwd=run_dir, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr

    lines = (run_dir / "multiunit.out").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4  # 3 detail + 1 totals
    assert lines[0].split()[-2:] == ["1.00", "1122.33"]
    assert lines[1].split()[-2:] == ["1.00", "5000.00"]
    assert lines[2].split()[-2:] == ["0.00", "0.00"]
    assert lines[3].strip().endswith("6122.33")


requires_full_toolchain = pytest.mark.skipif(
    shutil.which("cobc") is None or shutil.which("javac") is None,
    reason="requires cobc and javac on PATH (same convention as test_acceptance.py)",
)


@requires_full_toolchain
def test_candidate_matches_real_gnucobol_oracle(tmp_path):
    """Real byte-for-byte proof: compiles fixtures/cobol_multiunit/
    multiunit.cob with real cobc, runs it against the real committed data
    file, and diffs its real output against the candidate scaffold's
    output line-for-line, the same comparison contract every other
    fixture in this repo is held to."""
    from weaver.comparison import compare_lines, normalize_line_endings

    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    (oracle_dir / "multiunit.cob").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(DATA_DIR / "accounts3.dat", oracle_dir / "accounts3.dat")
    compiled = subprocess.run(
        ["cobc", "-x", "multiunit.cob", "-o", "multiunit"],
        cwd=oracle_dir, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"
    oracle_run = subprocess.run(["./multiunit"], cwd=oracle_dir, capture_output=True, text=True, timeout=30)
    assert oracle_run.returncode == 0, f"{oracle_run.stdout}\n{oracle_run.stderr}"
    oracle_lines = normalize_line_endings((oracle_dir / "multiunit.out").read_text(encoding="utf-8")).splitlines()

    model = load_program(FIXTURE)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    bodies = {spec.paragraph_id: CORRECT_BODIES["VALIDATE-RECORD"],
              spec.extra_paragraph_ids[0]: CORRECT_BODIES["COMPUTE-FEE"]}
    assembled = assemble(source, bodies)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "Scaffold.java").write_text(assembled, encoding="utf-8")
    build_dir = candidate_dir / "build"
    subprocess.run(["javac", "-d", str(build_dir), str(candidate_dir / "Scaffold.java")],
                    check=True, capture_output=True, text=True, timeout=30)
    shutil.copy2(DATA_DIR / "accounts3.dat", candidate_dir / "accounts3.dat")
    candidate_run = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"],
                                    cwd=candidate_dir, capture_output=True, text=True, timeout=30)
    assert candidate_run.returncode == 0, candidate_run.stderr
    candidate_lines = normalize_line_endings((candidate_dir / "multiunit.out").read_text(encoding="utf-8")).splitlines()

    assert len(oracle_lines) == len(candidate_lines)
    divergences = [
        compare_lines(i, o, c, None, layout=spec.report_layout if i < len(oracle_lines) - 1 else spec.totals_layout)
        for i, (o, c) in enumerate(zip(oracle_lines, candidate_lines))
    ]
    divergences = [d for d in divergences if d is not None]
    assert divergences == [], divergences
