"""Sanity tests for deterministic classification (FR-13).

TODO: once real divergence data exists (Step D5/E2), add the acceptance
test from AC-10: UNKNOWN <= 15% of classifications on the real 113-record
divergence set.
"""

from decimal import Decimal

from zuse.classification import DefectClass, classify
from zuse.comparison import Divergence


def _div(oracle: str, candidate: str, delta=None) -> Divergence:
    return Divergence(0, 0, "TEST-FIELD", oracle, candidate, delta, None)


def test_padding_detected_when_equal_after_strip():
    result = classify(_div(" 123", "123 "))
    assert result.defect_class == DefectClass.PADDING


def test_sign_detected_when_magnitudes_equal_opposite_sign():
    result = classify(_div("100.00", "-100.00"))
    assert result.defect_class == DefectClass.SIGN


def test_truncation_detected_for_sub_ulp_delta():
    result = classify(_div("10.01", "10.00", delta=Decimal("0.01") - Decimal("0.005")))
    assert result.defect_class == DefectClass.TRUNCATION
