"""Phase X8 acceptance tests -- weaver.cobol.subprogram's widened,
multi-input-field LINKAGE SECTION grammar, and
weaver.agent.subprogram_verify's matching N-input real parity axis
(verify_subprogram_multi), proven against a new, synthetic 2-input
subprogram fixture -- not LEAF-A/LEAF-B, proving the widening is generic."""

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from weaver.agent.subprogram_scaffold import generate as generate_subprogram_scaffold
from weaver.agent.subprogram_verify import verify_subprogram_multi
from weaver.cobol.subprogram import load_subprogram

TWO_FIELD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADDER.

       DATA DIVISION.
       LINKAGE SECTION.
       01  AD-A                   PIC 9(5)V99.
       01  AD-B                   PIC 9(5)V99.
       01  AD-SUM                 PIC 9(6)V99.

       PROCEDURE DIVISION USING AD-A AD-B AD-SUM.
       MAIN-PARA.
           COMPUTE AD-SUM = AD-A + AD-B
           GOBACK.
"""

CORRECT_BODY = "        return a.add(b);"
WRONG_BODY = "        return a;"


@pytest.fixture()
def two_field_model(tmp_path):
    path = tmp_path / "adder.cob"
    path.write_text(TWO_FIELD_SOURCE, encoding="utf-8")
    return load_subprogram(path)


def test_load_subprogram_parses_two_input_fields(two_field_model):
    model = two_field_model
    assert model.program_id == "ADDER"
    assert [f.name for f in model.input_params] == ["AD-A", "AD-B"]
    assert [f.name for f in model.output_params] == ["AD-SUM"]


_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"


@pytest.mark.skipif(not _have_cobc, reason="requires cobc on PATH or WEAVER_COBC_VIA_WSL=1")
@pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")
def test_verify_subprogram_multi_zero_divergence_for_correct_body(two_field_model, tmp_path):
    witnesses = [
        {"AD-A": Decimal("100.00"), "AD-B": Decimal("250.50")},
        {"AD-A": Decimal("0.00"), "AD-B": Decimal("0.00")},
        {"AD-A": Decimal("99999.99"), "AD-B": Decimal("0.01")},
    ]
    # subprogram_scaffold.generate needs a 2-arg java_signature -- proven
    # separately via subprogram_prompt.py's own tests; here we only need
    # verify_subprogram_multi's driver-generation path, which calls
    # generate_subprogram_scaffold itself.
    result = verify_subprogram_multi(two_field_model, CORRECT_BODY, witnesses, tmp_path / "correct")
    assert result.compiled, result.compile_error
    assert result.divergence_count == 0, result.divergences


@pytest.mark.skipif(not _have_cobc, reason="requires cobc on PATH or WEAVER_COBC_VIA_WSL=1")
@pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")
def test_verify_subprogram_multi_flags_wrong_body(two_field_model, tmp_path):
    witnesses = [{"AD-A": Decimal("100.00"), "AD-B": Decimal("250.50")}]
    result = verify_subprogram_multi(two_field_model, WRONG_BODY, witnesses, tmp_path / "wrong")
    assert result.compiled, result.compile_error
    assert result.divergence_count == 1, result.divergences
