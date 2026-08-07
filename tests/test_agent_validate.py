"""Regression tests for weaver/agent/validate.py, Change 2/3 (2026-08-07):

Bug A: static_reject's bare-setScale rule false-positived on
    BigDecimal.ZERO.setScale(2) -- rejected this project's own hand-verified
    K3 reference implementation.
Bug B: no check for a single-argument .divide(x), which compiles clean and
    throws ArithmeticException at runtime on a non-terminating decimal.
Bug C: regeneration_hint's branch order matched the generic RoundingMode
    hint before the more specific divide hint, because the .divide() detail
    string itself contains the substring "RoundingMode".
"""

from weaver.agent.validate import (
    SynthesizedBody,
    ValidationError,
    regeneration_hint,
    static_reject,
)

ALLOWED = {"ar", "ws"}


def _body(text: str) -> SynthesizedBody:
    return SynthesizedBody(method_body=text, assumptions=[])


# --- Bug A: BigDecimal.ZERO.setScale(2) must NOT be rejected ---

def test_zero_setscale_without_rounding_mode_is_allowed():
    body = _body("ws.penalty = java.math.BigDecimal.ZERO.setScale(2);")
    static_reject(body, ALLOWED)  # must not raise


def test_non_zero_bare_setscale_is_still_rejected():
    body = _body("ws.penalty = ar.balance.setScale(2);")
    try:
        static_reject(body, ALLOWED)
    except ValidationError as e:
        assert e.reason == "forbidden construct"
    else:
        raise AssertionError("expected ValidationError for bare .setScale(2) on a non-ZERO value")


def test_setscale_with_explicit_rounding_mode_is_allowed():
    body = _body("ws.penalty = ar.balance.setScale(2, java.math.RoundingMode.DOWN);")
    static_reject(body, ALLOWED)  # must not raise


# --- Bug B: single-argument .divide(x) must be rejected ---

def test_single_argument_divide_is_rejected():
    body = _body("ws.interest = ar.balance.divide(ws.appliedRate);")
    try:
        static_reject(body, ALLOWED)
    except ValidationError as e:
        assert e.reason == "forbidden construct"
        assert "divide" in e.detail
    else:
        raise AssertionError("expected ValidationError for single-argument .divide(x)")


def test_divide_with_scale_and_rounding_mode_is_allowed():
    body = _body(
        "ws.interest = ar.balance.divide(ws.appliedRate, 10, java.math.RoundingMode.DOWN);"
    )
    static_reject(body, ALLOWED)  # must not raise


def test_divide_with_rounding_mode_only_is_allowed():
    body = _body(
        "ws.interest = ar.balance.divide(ws.appliedRate, java.math.RoundingMode.DOWN);"
    )
    static_reject(body, ALLOWED)  # must not raise


# --- Bug C: regeneration_hint must give the divide hint, not the generic
# RoundingMode hint, even though the divide detail string contains the
# substring "RoundingMode" ---

def test_divide_error_gets_divide_hint_not_rounding_mode_hint():
    error = ValidationError(
        "forbidden construct",
        "single-argument .divide() (no scale/RoundingMode -- can throw ArithmeticException)",
    )
    hint = regeneration_hint(error)
    assert "divide" in hint.lower()
    assert "always pass a scale and roundingmode" in hint.lower()


def test_plain_rounding_mode_error_still_gets_rounding_mode_hint():
    error = ValidationError(
        "forbidden construct",
        "RoundingMode.HALF_UP/HALF_EVEN/HALF_DOWN/CEILING/UP",
    )
    hint = regeneration_hint(error)
    assert "truncates toward zero" in hint
    assert "divide" not in hint.lower()
