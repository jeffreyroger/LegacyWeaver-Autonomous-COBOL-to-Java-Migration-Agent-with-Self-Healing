"""Phase X2 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X2) -- the generated scaffold compiles under real javac with a
hand-written correct body substituted in, proving the class shape is
valid Java independent of any synthesis/verification machinery."""

import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.subprogram_scaffold import generate
from weaver.cobol.subprogram import load_subprogram

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"

requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


def test_unsynthesized_stub_has_paragraph_markers_and_throws():
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    source = generate(model)
    assert "public final class LeafA {" in source
    assert "public static java.math.BigDecimal mainPara(java.math.BigDecimal input) {" in source
    assert "// PARAGRAPH:MAIN-PARA:BEGIN" in source
    assert "// PARAGRAPH:MAIN-PARA:END" in source
    assert "UnsupportedOperationException" in source


def test_leaf_b_class_and_method_names():
    model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    source = generate(model)
    assert "public final class LeafB {" in source
    assert "java.math.BigDecimal mainPara(java.math.BigDecimal input)" in source


@requires_javac
def test_generated_leaf_a_scaffold_compiles_with_correct_body(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    body = "        return input.multiply(java.math.BigDecimal.valueOf(2));"
    source = generate(model, method_body=body)

    java_file = tmp_path / "LeafA.java"
    java_file.write_text(source, encoding="utf-8")

    result = subprocess.run(
        ["javac", "-d", str(tmp_path), str(java_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"javac failed:\n{result.stdout}\n{result.stderr}"
    assert (tmp_path / "LeafA.class").exists()


@requires_javac
def test_generated_leaf_b_scaffold_compiles_with_correct_body(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    body = "        return input.add(java.math.BigDecimal.valueOf(10.00));"
    source = generate(model, method_body=body)

    java_file = tmp_path / "LeafB.java"
    java_file.write_text(source, encoding="utf-8")

    result = subprocess.run(
        ["javac", "-d", str(tmp_path), str(java_file)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"javac failed:\n{result.stdout}\n{result.stderr}"
    assert (tmp_path / "LeafB.class").exists()
