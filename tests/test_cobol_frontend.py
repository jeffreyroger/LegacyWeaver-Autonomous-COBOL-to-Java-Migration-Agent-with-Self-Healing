"""Phase V acceptance tests — the COBOL frontend.

The load-bearing tests here are `test_derived_layouts_match_hand_tables` and
`test_corpus_layouts_match_hand_tables`: the parser's output must equal the
hand-derived tables in `weaver/layout.py` and the five `*_layout.py` modules,
field for field. Those tables were built by hand from the copybooks and
cross-checked against real GnuCOBOL runs (CLAUDE.md rule 6), so they are the
regression oracle for the parser — and because the derived tables are *equal*
to them, every number downstream (201 report lines, 132 divergences, the
golden checksum) is unchanged by construction, not by re-measurement.

Four of the six fixtures were written independently of this parser, during
Phase U ("Fixture Breadth"). They are the strongest evidence available that
this is a parser and not a lookup table.
"""

from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path

import pytest

from weaver.agent.feecalc_layout import INPUT_LAYOUT as FEE_INPUT
from weaver.agent.feecalc_layout import REPORT_LAYOUT as FEE_REPORT
from weaver.agent.feecalc_layout import TOTALS_LAYOUT as FEE_TOTALS
from weaver.agent.feecalc_spec import FEECALC_SPEC
from weaver.agent.scaffold import INTEREST_SPEC, generate
from weaver.cobol.data_division import UnsupportedDataItemError
from weaver.cobol.frontend import load_program, to_scaffold_spec
from weaver.cobol.pic import UnsupportedPictureError, parse as parse_pic
from weaver.layout import (
    INPUT_LAYOUT,
    REPORT_LAYOUT,
    TOTALS_LAYOUT,
    Field,
    record_width,
)

INTEREST = Path("fixtures/cobol/interest.cob")
FEECALC = Path("fixtures/cobol_feecalc/feecalc.cob")


# ---------------------------------------------------------------------
# V1 — the PICTURE parser
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "pic,sign_separate,width,scale,numeric,signed",
    [
        # Every picture appearing in the three fixtures.
        ("X(16)", False, 16, 0, False, False),
        ("X(12)", False, 12, 0, False, False),
        ("X(1)", False, 1, 0, False, False),
        ("X", False, 1, 0, False, False),
        ("X(4)", False, 4, 0, False, False),
        ("9V9(5)", False, 6, 5, True, False),
        # Trailing separate sign adds one stored byte; V adds none.
        ("S9(9)V99", True, 12, 2, True, True),
        ("S9(7)V99", True, 10, 2, True, True),
        ("S9(7)V99", False, 9, 2, True, True),
        ("S9(9)V99", False, 11, 2, True, True),
        ("S9(5)V99", False, 7, 2, True, True),
        # Numeric-edited: every symbol is one print position.
        ("-(9)9.99", False, 13, 2, True, True),
        ("-(7)9.99", False, 11, 2, True, True),
        ("-(5)9.99", False, 9, 2, True, True),
    ],
)
def test_picture_widths(pic, sign_separate, width, scale, numeric, signed):
    p = parse_pic(pic, sign_separate=sign_separate)
    assert (p.width, p.decimal_scale, p.numeric, p.signed) == (
        width,
        scale,
        numeric,
        signed,
    )


def test_edit_mask_is_one_position_wider_than_its_digits():
    """The Step B4/B5 report-line correction, computed rather than counted.

    `-(9)9.99` holds nine floating-sign positions, one mandatory digit, the
    point and two decimals: 13, not the 12 a digit count suggests. Getting
    this wrong is what silently truncated the max-magnitude records once.
    """
    assert parse_pic("-(9)9.99").width == 13
    assert REPORT_LAYOUT[2].name == "RL-BALANCE"
    assert REPORT_LAYOUT[2].width == 13


@pytest.mark.parametrize(
    "pic", ["9(5) COMP-3", "S9(4) USAGE COMP", "$$,$$9.99", "9(4)B9"]
)
def test_unsupported_pictures_raise_rather_than_guess(pic):
    with pytest.raises(UnsupportedPictureError):
        parse_pic(pic)


# ---------------------------------------------------------------------
# V2 — layouts, against the hand-derived tables
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        (INTEREST, (INPUT_LAYOUT, REPORT_LAYOUT, TOTALS_LAYOUT)),
        (FEECALC, (FEE_INPUT, FEE_REPORT, FEE_TOTALS)),
    ],
)
def test_derived_layouts_match_hand_tables(source, expected):
    model = load_program(source)
    assert model.input_layout == expected[0]
    assert model.report_layout == expected[1]
    assert model.totals_layout == expected[2]


def test_record_widths_are_the_documented_load_bearing_numbers():
    """CLAUDE.md rule 6: 39-byte input record, 42-byte report line."""
    model = load_program(INTEREST)
    assert record_width(model.input_layout) == 39
    assert record_width(model.report_layout) == 42
    assert record_width(model.totals_layout) == 42


def test_redefines_overlay_does_not_extend_the_record():
    """K2's second named failure mode: an overlay reads its target's bytes."""
    model = load_program(INTEREST)
    by_name = {f.name: f for f in model.input_layout}
    flags, dormant, hold = (
        by_name["AR-FLAGS"],
        by_name["AR-DORMANT"],
        by_name["AR-HOLD"],
    )
    assert flags.redefines is None
    assert dormant.redefines == hold.redefines == "AR-FLAGS"
    assert dormant.offset == flags.offset
    assert hold.offset == flags.offset + 1
    # The overlay fields contribute no width to the record.
    assert record_width(model.input_layout) == 39


def test_implied_decimal_does_not_shift_the_following_field():
    """K2's first named failure mode: V occupies zero bytes."""
    model = load_program(INTEREST)
    by_name = {f.name: f for f in model.input_layout}
    assert by_name["AR-BALANCE"].offset == 16
    assert by_name["AR-BALANCE"].width == 12  # 11 digits + separate sign byte
    assert by_name["AR-RATE"].offset == 28  # not 29, not 27


# ---------------------------------------------------------------------
# V3 + V4 — the full ScaffoldSpec, derived rather than declared
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,declared", [(INTEREST, INTEREST_SPEC), (FEECALC, FEECALC_SPEC)]
)
def test_derived_scaffold_spec_matches_the_hand_written_one(source, declared):
    assert to_scaffold_spec(load_program(source)) == declared


@pytest.mark.parametrize(
    "source,declared", [(INTEREST, INTEREST_SPEC), (FEECALC, FEECALC_SPEC)]
)
def test_generated_scaffold_is_byte_identical(source, declared):
    """K2's acceptance test, re-run through the frontend."""
    assert generate(to_scaffold_spec(load_program(source))) == generate(declared)


def test_condition_names_come_from_the_88_levels():
    model = load_program(INTEREST)
    assert [
        (c.java_name, c.parent_field, c.true_value) for c in model.condition_names
    ] == [
        ("isPremium", "AR-TYPE", "P"),
        ("isDormant", "AR-DORMANT", "Y"),
        ("isHold", "AR-HOLD", "Y"),
    ]


def test_working_storage_matches_the_previously_declared_tuple():
    """Replaces data_context.WORKING_STORAGE_FIELDS, which was hand-declared."""
    model = load_program(INTEREST)
    assert model.working_storage_names == (
        "WS-EOF-FLAG",
        "WS-APPLIED-RATE",
        "WS-INTEREST",
        "WS-TOTAL-INTEREST",
    )
    # The EOF flag is not a WorkingStorage class member: it is alphanumeric
    # and the generated main loop owns end-of-file, not the paragraph.
    assert [f.java_name for f in model.ws_fields] == [
        "appliedRate",
        "interest",
        "totalInterest",
    ]


def test_accumulator_is_read_from_the_add_statement():
    interest, fee = load_program(INTEREST), load_program(FEECALC)
    assert (interest.accumulator_field, interest.per_record_field) == (
        "totalInterest",
        "interest",
    )
    assert (fee.accumulator_field, fee.per_record_field) == ("totalFee", "fee")


def test_redefines_source_becomes_an_accessor_call_in_the_ctor_map():
    model = load_program(INTEREST)
    assert model.report_ctor_map["RL-DORMANT"] == "ar.dormant()"
    assert model.report_ctor_map["RL-ID"] == "ar.id"
    assert model.report_ctor_map["RL-INTEREST"] == "ws.interest"


# ---------------------------------------------------------------------
# Prompt vocabulary — pinned, because it is part of the model cache key
# ---------------------------------------------------------------------


def test_prompt_prohibition_text_is_pinned():
    """The T2 demo cache is keyed on a hash of the full prompt, so anything
    that renders the prohibition differently silently invalidates every
    cached model response for that program. This pins the rendering.

    Note for reviewers: the S1 generalization changed this line from
    "ws.appliedRate and ws.interest" (hand-written, pre-2026-08-12) to
    "ws.appliedRate, ws.interest" — a comma, not a conjunction. That is a
    real change to a hashed input, made incidentally rather than
    deliberately. It is pinned here as-is rather than reverted, because
    reverting is also a cache-affecting change and the choice belongs to
    whoever owns the demo cache.
    """
    from weaver.agent.prompt import _prohibitions

    text = _prohibitions(to_scaffold_spec(load_program(INTEREST)))
    assert "- write to ws.totalInterest -- the generated main loop owns that\n" in text
    assert (
        "  accumulation; this paragraph only sets ws.appliedRate, ws.interest\n" in text
    )


# ---------------------------------------------------------------------
# The full fixture corpus — including four programs written independently
# of this parser (Phase U, "Fixture Breadth"). They are the strongest
# evidence available that this is a parser and not a lookup table.
# ---------------------------------------------------------------------

CORPUS = [
    (
        "feecalc",
        Path("fixtures/cobol_feecalc/feecalc.cob"),
        "weaver.agent.feecalc_layout",
        "weaver.agent.feecalc_spec",
        "FEECALC_SPEC",
    ),
    (
        "taxcalc",
        Path("fixtures/cobol_taxcalc/taxcalc.cob"),
        "weaver.agent.taxcalc_layout",
        "weaver.agent.taxcalc_spec",
        "TAXCALC_SPEC",
    ),
    (
        "tieraccum",
        Path("fixtures/cobol_tieraccum/tieraccum.cob"),
        "weaver.agent.tieraccum_layout",
        "weaver.agent.tieraccum_spec",
        "TIERACCUM_SPEC",
    ),
    (
        "compound",
        Path("fixtures/cobol_compound/compound.cob"),
        "weaver.agent.compound_layout",
        "weaver.agent.compound_spec",
        "COMPOUND_SPEC",
    ),
    (
        "shipcost",
        Path("fixtures/cobol_shipcost/shipcost.cob"),
        "weaver.agent.shipcost_layout",
        "weaver.agent.shipcost_spec",
        "SHIPCOST_SPEC",
    ),
]


@pytest.mark.parametrize("name,source,layout_mod,_spec_mod,_spec_name", CORPUS)
def test_corpus_layouts_match_hand_tables(
    name, source, layout_mod, _spec_mod, _spec_name
):
    layout = importlib.import_module(layout_mod)
    model = load_program(source)
    assert model.input_layout == layout.INPUT_LAYOUT
    assert model.report_layout == layout.REPORT_LAYOUT
    assert model.totals_layout == layout.TOTALS_LAYOUT


@pytest.mark.parametrize("name,source,_layout_mod,spec_mod,spec_name", CORPUS)
def test_corpus_specs_match_hand_written(
    name, source, _layout_mod, spec_mod, spec_name
):
    declared = getattr(importlib.import_module(spec_mod), spec_name)
    derived = to_scaffold_spec(load_program(source))

    if name in ("tieraccum", "compound"):
        # Known, deliberate difference. These two programs declare
        # WORKING-STORAGE scratch items (WS-IDX, WS-STEP, WS-STEP1..4) that
        # the hand-written spec omits because its reference body expresses
        # them as Java locals. The parser cannot know that intent: it emits
        # every numeric WORKING-STORAGE item, which is the source-faithful
        # reading and gives the model each item's declared scale. The
        # reference bodies still compile against the derived scaffold —
        # unused fields are legal — so this is additive, not a conflict.
        assert dataclasses.replace(derived, ws_fields=declared.ws_fields) == declared
        derived_names = {f.java_name for f in derived.ws_fields}
        assert {f.java_name for f in declared.ws_fields} <= derived_names
        return

    assert derived == declared


@pytest.mark.parametrize("name,source,_lm,_sm,_sn", CORPUS)
def test_corpus_profiles_resolve_without_hand_written_modules(
    name, source, _lm, _sm, _sn
):
    """`program_profile` derives layouts, spec, output filename and the
    reference-body path; only artefact directories stay declared."""
    from weaver.agent.program_profiles import program_profile

    profile = program_profile(source)
    assert profile is not None
    assert profile.output_filename == f"{name}.out" or profile.output_filename.endswith(
        ".out"
    )
    assert profile.scaffold_spec.paragraph_id == profile.reference_paragraph_id
    assert profile.reference_body_path.exists(), profile.reference_body_path
    assert profile.input_data.exists(), profile.input_data
    assert profile.golden_output.exists(), profile.golden_output


def test_missing_source_returns_no_profile_rather_than_raising():
    from weaver.agent.program_profiles import program_profile

    assert program_profile(Path("does/not/exist.cob")) is None


def test_unparseable_program_raises_rather_than_falling_back(tmp_path):
    """The dangerous case: a real file the frontend cannot model must stop
    the run, never silently resolve to interest.cob's layouts."""
    from weaver.agent.program_profiles import program_profile

    bad = tmp_path / "broken.cob"
    bad.write_text(
        INTEREST.read_text(encoding="utf-8").replace(
            "PIC S9(9)V99", "PIC S9(9)V99 COMP-3"
        ),
        encoding="utf-8",
    )
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "copybooks" / "ACCOUNT-REC.cpy").write_text(
        (INTEREST.parent / "copybooks" / "ACCOUNT-REC.cpy")
        .read_text(encoding="utf-8")
        .replace("PIC S9(9)V99", "PIC S9(9)V99 COMP-3"),
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedDataItemError):
        program_profile(bad)
