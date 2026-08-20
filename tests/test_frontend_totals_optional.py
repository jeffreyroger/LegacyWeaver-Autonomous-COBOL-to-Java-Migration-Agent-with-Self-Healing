"""Phase X7 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X7) -- load_program()'s totals-optional relaxation. New, additive branch:
every existing fixture still has a totals line and takes the exact code
path it always took (proven by tests/test_cobol_frontend.py's unchanged
50 tests); ROOT.cob (no totals line at all) now parses too.
"""

import subprocess
from pathlib import Path

import pytest

from weaver.agent.scaffold import generate
from weaver.cobol.frontend import load_program, to_scaffold_spec

ROOT_COB = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog" / "root.cob"


def test_root_cob_parses_via_totals_optional_branch():
    model = load_program(ROOT_COB)
    assert model.program_id == "ROOT"
    assert model.totals_layout == ()
    assert model.accumulator_field == ""
    assert model.report_ctor_map == {"RL-ID": "ar.id", "RL-A": "ws.outputA", "RL-B": "ws.outputB"}


def test_root_cob_scaffold_spec_generates_valid_java_with_no_totals_line():
    model = load_program(ROOT_COB)
    spec = to_scaffold_spec(model)
    source = generate(spec)
    assert "TotalsLine tl" not in source
    assert "ws. = ws.." not in source  # no blank-field accumulator line leaked through
    assert "class Scaffold" in source


@pytest.mark.skipif(
    __import__("shutil").which("javac") is None, reason="requires javac on PATH"
)
def test_root_cob_scaffold_compiles_with_a_hand_written_body(tmp_path):
    model = load_program(ROOT_COB)
    spec = to_scaffold_spec(model)
    source = generate(spec)

    # Replace the unsynthesized stub with a no-op body -- this test only
    # proves the totals-optional generated class shape itself is valid
    # Java; real CALL resolution against LEAF-A/LEAF-B is this phase's
    # later step.
    source = source.replace(
        f'throw new UnsupportedOperationException("{spec.paragraph_id} not yet synthesized");',
        "// no-op for this compile-only proof",
    )

    java_file = tmp_path / "Scaffold.java"
    java_file.write_text(source, encoding="utf-8")
    result = subprocess.run(
        ["javac", "-d", str(tmp_path), str(java_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"javac failed:\n{result.stdout}\n{result.stderr}"
