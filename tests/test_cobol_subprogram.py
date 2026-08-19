"""Phase X1 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X1) -- LEAF-A/LEAF-B parse correctly (hand-verified against source), and
out-of-scope shapes raise rather than guess."""

from pathlib import Path

import pytest

from weaver.cobol.subprogram import UnsupportedSubprogramError, load_subprogram

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"


def test_load_leaf_a_matches_hand_verified_source():
    model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    assert model.program_id == "LEAF-A"
    assert model.input_param.name == "LA-INPUT"
    assert model.output_param.name == "LA-OUTPUT"
    assert model.input_param.numeric and model.output_param.numeric
    assert model.input_param.decimal_scale == 2
    assert model.output_param.decimal_scale == 2
    assert model.paragraph_id == "MAIN-PARA"
    assert "COMPUTE LA-OUTPUT = LA-INPUT * 2" in model.paragraph_source.upper()


def test_load_leaf_b_matches_hand_verified_source():
    model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    assert model.program_id == "LEAF-B"
    assert model.input_param.name == "LB-INPUT"
    assert model.output_param.name == "LB-OUTPUT"
    assert model.paragraph_id == "MAIN-PARA"
    assert "10.00" in model.paragraph_source


def test_root_cob_has_file_io_and_is_rejected():
    # ROOT.cob has FILE-CONTROL/FD -- outside Phase X1's no-file-I/O scope.
    with pytest.raises(UnsupportedSubprogramError):
        load_subprogram(FIXTURE_DIR / "root.cob")


def test_interest_cob_has_file_io_and_is_rejected():
    with pytest.raises(UnsupportedSubprogramError):
        load_subprogram(
            Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "interest.cob"
        )


def test_more_than_two_linkage_params_rejected(tmp_path):
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THREE-PARAM.

       DATA DIVISION.
       LINKAGE SECTION.
       01  P-A                    PIC 9(5)V99.
       01  P-B                    PIC 9(5)V99.
       01  P-C                    PIC 9(5)V99.

       PROCEDURE DIVISION USING P-A P-B P-C.
       MAIN-PARA.
           COMPUTE P-C = P-A + P-B
           GOBACK.
"""
    path = tmp_path / "three_param.cob"
    path.write_text(source)
    with pytest.raises(UnsupportedSubprogramError):
        load_subprogram(path)


def test_more_than_one_paragraph_rejected(tmp_path):
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWO-PARA.

       DATA DIVISION.
       LINKAGE SECTION.
       01  P-IN                   PIC 9(5)V99.
       01  P-OUT                  PIC 9(5)V99.

       PROCEDURE DIVISION USING P-IN P-OUT.
       MAIN-PARA.
           PERFORM DOUBLE-IT
           GOBACK.
       DOUBLE-IT.
           COMPUTE P-OUT = P-IN * 2.
"""
    path = tmp_path / "two_para.cob"
    path.write_text(source)
    with pytest.raises(UnsupportedSubprogramError):
        load_subprogram(path)


def test_non_numeric_linkage_param_rejected(tmp_path):
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALPHA-PARAM.

       DATA DIVISION.
       LINKAGE SECTION.
       01  P-IN                   PIC X(5).
       01  P-OUT                  PIC 9(5)V99.

       PROCEDURE DIVISION USING P-IN P-OUT.
       MAIN-PARA.
           MOVE ZERO TO P-OUT
           GOBACK.
"""
    path = tmp_path / "alpha_param.cob"
    path.write_text(source)
    with pytest.raises(UnsupportedSubprogramError):
        load_subprogram(path)


def test_missing_procedure_division_using_rejected(tmp_path):
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NO-USING.

       DATA DIVISION.
       LINKAGE SECTION.
       01  P-IN                   PIC 9(5)V99.
       01  P-OUT                  PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE ZERO TO P-OUT
           GOBACK.
"""
    path = tmp_path / "no_using.cob"
    path.write_text(source)
    with pytest.raises(UnsupportedSubprogramError):
        load_subprogram(path)
