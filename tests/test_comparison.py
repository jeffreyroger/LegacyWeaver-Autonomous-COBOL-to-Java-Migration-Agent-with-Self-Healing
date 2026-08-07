"""Sanity tests for the comparison contract (FR-10, FR-12).

TODO: once weaver.layout.REPORT_LAYOUT is populated (Step D3), add:
  - AC-9 self-comparison: golden vs golden -> zero divergences, verified.
  - AC-8 single-field localisation: a candidate differing in exactly one
    known field yields exactly one divergence with correct field id,
    offset, delta, and causing input record.
"""

from decimal import Decimal

from weaver.comparison import compare_lines, normalize_line_endings


def test_normalize_line_endings_converts_crlf_to_lf():
    assert normalize_line_endings("a\r\nb\r\n") == "a\nb\n"


def test_identical_lines_produce_no_divergence():
    assert compare_lines(0, "same line", "same line", input_record=None) is None


def test_differing_lines_without_declared_layout_are_reported_undeclared():
    div = compare_lines(0, "AAAA", "BBBB", input_record="raw-input")
    assert div is not None
    assert div.field_name == "UNDECLARED"
    assert div.causing_input_record == "raw-input"
