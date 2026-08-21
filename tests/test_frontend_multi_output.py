"""Phase BB2 acceptance tests (proactive generalization of
weaver/cobol/frontend.py beyond its original one-input/one-output scope) --
fixtures/cobol_multioutput/multioutput.cob writes every input record
unconditionally to TWO output files (a fee report and a separate balance
audit log), each with its own totals line. See
weaver/agent/scaffold.py's ExtraOutputFile comment for why this is
unconditional-per-record, not conditional routing (which would be real
business-logic derivation, outside weaver/cobol/procedure.py's declared
scope).

Every existing fixture's frontend/scaffold regression coverage
(tests/test_cobol_frontend.py, tests/test_scaffold_redefines.py) already
proves this phase changed nothing for single-output-file programs -- these
tests are additive, covering only the new N>1 shape.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.assemble import assemble
from weaver.agent.scaffold import generate
from weaver.cobol.frontend import load_program, to_scaffold_spec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol_multioutput" / "multioutput.cob"
DATA_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "data_multioutput"

# Hand-computed from the real PIC 9(7)V99 encoding in
# fixtures/data_multioutput/accounts2.dat -- fee = balance * 0.01 (truncated):
#   112233.45 * 0.01 = 1122.3345 -> 1122.33
#   500000.00 * 0.01 = 5000.00
#        0.00 * 0.01 =    0.00
# Total fee: 1122.33 + 5000.00 + 0.00 = 6122.33
# Total balance: 112233.45 + 500000.00 + 0.00 = 612233.45
CORRECT_BODY = (
    '        ws.fee = ar.balance.multiply(new java.math.BigDecimal("0.01000"))'
    ".setScale(2, java.math.RoundingMode.DOWN);\n"
    "        ws.balanceCopy = ar.balance;"
)


def test_load_program_parses_two_output_files():
    model = load_program(FIXTURE)
    assert model.output_file == "fee.out"
    assert len(model.extra_output_files) == 1
    extra = model.extra_output_files[0]
    assert extra.file_name == "audit.out"
    assert [f.name for f in extra.report_layout] == ["AL-ID", "AL-BALANCE"]
    assert [f.name for f in extra.totals_layout] == ["ATL-LABEL", "ATL-TOTAL", "ATL-FILLER"]


def test_each_output_file_derives_its_own_ctor_map_and_accumulator():
    model = load_program(FIXTURE)
    assert model.accumulator_field == "totalFee"
    assert model.per_record_field == "fee"
    extra = model.extra_output_files[0]
    assert extra.accumulator_field == "totalBalance"
    assert extra.per_record_field == "balanceCopy"
    assert extra.report_ctor_map == {"AL-ID": "ar.id", "AL-BALANCE": "ar.balance"}


requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_candidate_scaffold_writes_both_output_files_correctly(tmp_path):
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
    shutil.copy2(DATA_DIR / "accounts2.dat", run_dir / "accounts2.dat")
    ran = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"], cwd=run_dir, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr

    fee_lines = (run_dir / "fee.out").read_text(encoding="utf-8").splitlines()
    audit_lines = (run_dir / "audit.out").read_text(encoding="utf-8").splitlines()
    assert len(fee_lines) == 4  # 3 detail + 1 totals
    assert len(audit_lines) == 4

    assert fee_lines[0].split()[-2:] == ["112233.45", "1122.33"]
    assert fee_lines[1].split()[-2:] == ["500000.00", "5000.00"]
    assert fee_lines[2].split()[-2:] == ["0.00", "0.00"]
    assert fee_lines[3].strip().endswith("6122.33")

    assert audit_lines[0].split() == ["ACCT000001", "112233.45"]
    assert audit_lines[1].split() == ["ACCT000002", "500000.00"]
    assert audit_lines[2].split() == ["ACCT000003", "0.00"]
    assert audit_lines[3].strip().endswith("612233.45")


requires_full_toolchain = pytest.mark.skipif(
    shutil.which("cobc") is None or shutil.which("javac") is None,
    reason="requires cobc and javac on PATH (same convention as test_acceptance.py)",
)


@requires_full_toolchain
def test_candidate_matches_real_gnucobol_oracle(tmp_path):
    """Real byte-for-byte proof: compiles fixtures/cobol_multioutput/
    multioutput.cob with real cobc, runs it against the real committed
    data file, and diffs both of its real output files against the
    candidate scaffold's two output files line-for-line, the same
    comparison contract every other fixture in this repo is held to."""
    from weaver.comparison import compare_lines, normalize_line_endings

    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    (oracle_dir / "multioutput.cob").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(DATA_DIR / "accounts2.dat", oracle_dir / "accounts2.dat")
    compiled = subprocess.run(
        ["cobc", "-x", "multioutput.cob", "-o", "multioutput"],
        cwd=oracle_dir, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"
    oracle_run = subprocess.run(["./multioutput"], cwd=oracle_dir, capture_output=True, text=True, timeout=30)
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
    shutil.copy2(DATA_DIR / "accounts2.dat", candidate_dir / "accounts2.dat")
    candidate_run = subprocess.run(["java", "-cp", str(build_dir), "Scaffold"],
                                    cwd=candidate_dir, capture_output=True, text=True, timeout=30)
    assert candidate_run.returncode == 0, candidate_run.stderr

    for filename, layout_primary, layout_totals in (
        ("fee.out", spec.report_layout, spec.totals_layout),
        ("audit.out", spec.extra_output_files[0].report_layout, spec.extra_output_files[0].totals_layout),
    ):
        oracle_lines = normalize_line_endings((oracle_dir / filename).read_text(encoding="utf-8")).splitlines()
        candidate_lines = normalize_line_endings((candidate_dir / filename).read_text(encoding="utf-8")).splitlines()
        assert len(oracle_lines) == len(candidate_lines)
        divergences = [
            compare_lines(i, o, c, None, layout=layout_primary if i < len(oracle_lines) - 1 else layout_totals)
            for i, (o, c) in enumerate(zip(oracle_lines, candidate_lines))
        ]
        divergences = [d for d in divergences if d is not None]
        assert divergences == [], (filename, divergences)
