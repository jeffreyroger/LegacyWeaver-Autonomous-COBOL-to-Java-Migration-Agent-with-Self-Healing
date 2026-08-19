"""Phase X3 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X3, blocking gate). Real cobc-compiled LEAF-A/LEAF-B (via the disclosed
WEAVER_COBC_VIA_WSL shim on this dev machine, CLAUDE.md rule 10) vs. a
candidate Java body, over the same 6 hand-verified witness values Task 6's
accounts.dat already uses.

Proves the axis actually discriminates: a correct body gets zero
divergences; a deliberately wrong body gets a divergence at the exact
witness where behavior differs -- not just a green rubber stamp.
"""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from weaver.agent.subprogram_verify import verify_subprogram
from weaver.cobol.subprogram import load_subprogram

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"

# Task 6's own hand-verified witness values (fixtures/data/multiprog/accounts.dat).
WITNESSES = [Decimal("100.00"), Decimal("250.50"), Decimal("0.00"),
             Decimal("9999.99"), Decimal("1.01"), Decimal("12345.67")]

_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"
requires_cobol_toolchain = pytest.mark.skipif(
    not _have_cobc, reason="requires cobc on PATH or WEAVER_COBC_VIA_WSL=1"
)
requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_cobol_toolchain
@requires_javac
def test_correct_leaf_a_body_has_zero_divergences(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    body = "        return input.multiply(java.math.BigDecimal.valueOf(2));"
    result = verify_subprogram(model, body, WITNESSES, tmp_path)
    assert result.compiled, result.compile_error
    assert result.divergence_count == 0, result.divergences


@requires_cobol_toolchain
@requires_javac
def test_correct_leaf_b_body_has_zero_divergences(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    body = "        return input.add(java.math.BigDecimal.valueOf(10.00));"
    result = verify_subprogram(model, body, WITNESSES, tmp_path)
    assert result.compiled, result.compile_error
    assert result.divergence_count == 0, result.divergences


@requires_cobol_toolchain
@requires_javac
def test_wrong_leaf_a_body_diverges_at_the_expected_witnesses(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    # Deliberately wrong: adds 2 instead of doubling. double(x) == add(x, 2)
    # only at x==2, which is not in the witness set, so every witness
    # diverges, including 0.00 (double(0)=0 vs add(0,2)=2).
    wrong_body = "        return input.add(java.math.BigDecimal.valueOf(2));"
    result = verify_subprogram(model, wrong_body, WITNESSES, tmp_path)
    assert result.compiled, result.compile_error
    diverging_inputs = {d.witness_input for d in result.divergences}
    assert diverging_inputs == set(WITNESSES)


@requires_cobol_toolchain
@requires_javac
def test_wrong_leaf_b_body_diverges_at_a_nonzero_witness(tmp_path):
    model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    # Deliberately wrong surcharge amount (5.00 instead of 10.00).
    wrong_body = "        return input.add(java.math.BigDecimal.valueOf(5.00));"
    result = verify_subprogram(model, wrong_body, WITNESSES, tmp_path)
    assert result.compiled, result.compile_error
    assert result.divergence_count == len(WITNESSES)
    div = next(d for d in result.divergences if d.witness_input == Decimal("100.00"))
    assert div.oracle_output == Decimal("110.00")
    assert div.candidate_output == Decimal("105.00")
