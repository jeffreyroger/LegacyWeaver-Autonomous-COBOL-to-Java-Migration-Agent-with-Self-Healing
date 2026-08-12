"""Sanity tests for the comparison contract (FR-10, FR-12).

AC-9 (self-comparison zero false positives) and AC-8 (single-field
localisation) are exercised at the full-pipeline level in Phase D's
manual acceptance runs (see docs/specs/ for the recorded results);
these are unit-level checks of the comparison primitives themselves.
"""

from zuse.comparison import compare_lines, normalize_line_endings
from zuse.layout import REPORT_LAYOUT, TOTALS_LAYOUT


def test_normalize_line_endings_converts_crlf_to_lf():
    assert normalize_line_endings("a\r\nb\r\n") == "a\nb\n"


def test_identical_lines_produce_no_divergence():
    assert compare_lines(0, "same line", "same line", input_record=None) is None


def test_differing_lines_resolve_to_the_first_declared_field_that_differs():
    # RL-ID occupies offset 0-15; a difference confined to that window
    # must resolve to RL-ID, not fall through to UNDECLARED.
    div = compare_lines(0, "AAAA".ljust(16), "BBBB".ljust(16), input_record="raw-input")
    assert div is not None
    assert div.field_name == "RL-ID"
    assert div.causing_input_record == "raw-input"


def test_totals_line_divergence_resolves_against_totals_layout_not_detail_layout():
    # The 201st report line (totals) has a different field layout than the
    # 200 detail lines above it (TL-LABEL/TL-TOTAL/TL-FILLER, not
    # RL-ID/RL-TYPE/RL-BALANCE/RL-INTEREST/RL-DORMANT). Comparing it with
    # the wrong layout still finds *a* divergence (misleadingly named
    # RL-INTEREST) since the byte windows happen to overlap for this
    # fixture; comparing with the correct layout must name it TL-TOTAL.
    label = "TOTAL INTEREST:".ljust(30)
    oracle_line = label + "7816266.36".rjust(11) + " "
    candidate_line = label + "8639646.64".rjust(11) + " "
    assert len(oracle_line) == len(candidate_line) == 42

    div = compare_lines(200, oracle_line, candidate_line, input_record=None, layout=TOTALS_LAYOUT)
    assert div is not None
    assert div.field_name == "TL-TOTAL"


def test_difference_outside_any_declared_field_is_reported_undeclared():
    from zuse.layout import record_width

    base = " " * record_width(REPORT_LAYOUT)  # identical across every declared field
    # A difference only in a trailing byte beyond the declared layout
    # cannot resolve to any field, so it must fall back to UNDECLARED.
    line_a, line_b = base + "1", base + "2"
    div = compare_lines(0, line_a, line_b, input_record=None)
    assert div is not None
    assert div.field_name == "UNDECLARED"
