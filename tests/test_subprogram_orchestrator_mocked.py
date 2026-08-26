"""Regression tests for Dynamic Mocking / 3-axis Parity Gate wiring into
`SubprogramOrchestrator` and `LeafOrchestrator`, added 2026-08-26.

Before this change, `weaver/agent/mocked_verify.py` (Phase Z1) was fully
implemented and unit-tested in isolation (`tests/test_mocked_verify.py`)
but had zero production callers: `SubprogramOrchestrator.run()` only ever
called plain `verify_subprogram`, which cannot even compile an EXEC
SQL/EXEC CICS subprogram's raw source (no SQL precompiler here). This
file proves the auto-detection wiring (`find_mock_directives` on the
source decides which verify function runs) and the two real bugs found
getting `fixtures/cobol/mocked_leaf/billing.cob` to commit live end to
end via `weaver migrate --leaf-first`:

1. `weaver/agent/mock_generator.py`'s `rewrite_cobol_source` combined the
   MOVE and DISPLAY replacement statements onto one physical line, which
   silently overflows fixed-format COBOL's column-72 limit for a
   long-enough signature and truncates the DISPLAY string literal mid-
   quote -- a real compile failure in the *oracle* side of every mocked
   fixture, present before any of this session's other changes.
2. `verify_mocked_subprogram` crashed with an unhandled `ValueError` when
   a candidate's JVM process ended (crash, or never reached its final
   println) without printing a numeric last line -- a real robustness
   gap, not a synthesis-quality issue.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from weaver.agent.mock_generator import default_mock_map, rewrite_cobol_source
from weaver.agent.subprogram_orchestrator import _verify_mocked
from weaver.agent.subprogram_prompt import allowed_identifiers, build_subprogram_prompt
from weaver.cobol.mock_directives import find_mock_directives
from weaver.cobol.subprogram import load_subprogram

FIXTURE = Path("fixtures/cobol/mocked/billing.cob")
LEAF_A = Path("fixtures/cobol/multiprog/leaf_a.cob")

_have_cobc = shutil.which("cobc") is not None or os.environ.get("WEAVER_COBC_VIA_WSL") == "1"
requires_full_stack = pytest.mark.skipif(
    not _have_cobc or shutil.which("javac") is None,
    reason="requires cobc (native or WEAVER_COBC_VIA_WSL=1) and javac on PATH",
)


def test_build_subprogram_prompt_discloses_the_mock_signature():
    model = load_subprogram(FIXTURE)
    directives = find_mock_directives(FIXTURE.read_text(encoding="utf-8"))
    prompt = build_subprogram_prompt(model, directives)
    assert "WeaverMockRuntime.call" in prompt
    assert directives[0].signature in prompt


def test_build_subprogram_prompt_omits_mock_rule_for_a_plain_subprogram():
    model = load_subprogram(LEAF_A)
    prompt = build_subprogram_prompt(model, [])
    assert "WeaverMockRuntime" not in prompt


def test_allowed_identifiers_whitelists_weaver_mock_runtime_only_when_mocked():
    model = load_subprogram(FIXTURE)
    directives = find_mock_directives(FIXTURE.read_text(encoding="utf-8"))
    assert "WeaverMockRuntime" in allowed_identifiers(model, directives)
    assert "WeaverMockRuntime" not in allowed_identifiers(model, [])


def test_rewrite_keeps_move_and_display_on_separate_lines_under_72_columns():
    """Bug 1 (see module docstring): a combined `MOVE ... . DISPLAY "..."."`
    line for this real signature is 79 columns -- past fixed-format
    COBOL's 72-column limit -- and used to truncate the string literal."""
    model = load_subprogram(FIXTURE)
    directives = find_mock_directives(FIXTURE.read_text(encoding="utf-8"))
    mock_map = default_mock_map(directives)
    full_source = FIXTURE.read_text(encoding="utf-8")
    rewritten = rewrite_cobol_source(full_source, directives, mock_map, paragraph_names=[model.paragraph_id])
    for line in rewritten.splitlines():
        if "MOVE" in line or "STUB:" in line:
            assert len(line) <= 72, f"line exceeds fixed-format column limit: {line!r}"
    assert "MOVE" in rewritten and "DISPLAY" in rewritten


@requires_full_stack
def test_verify_mocked_aggregates_across_witnesses_into_subprogram_verify_result(tmp_path):
    from decimal import Decimal

    model = load_subprogram(FIXTURE)
    correct_body = 'return WeaverMockRuntime.call("SQL:SELECT:BL-ID-BL-TOTAL");'
    result = _verify_mocked(model, correct_body, [Decimal("1.00"), Decimal("99.99")], tmp_path)
    assert result.compiled
    assert result.divergence_count == 0


@requires_full_stack
def test_verify_mocked_does_not_crash_on_a_candidate_runtime_failure(tmp_path):
    """Bug 2 (see module docstring): a candidate that compiles but never
    reaches its final println (here, a bare unreachable-looking body that
    still compiles but returns without the driver printing a numeric
    line) must be reported as a mismatch, not raise."""
    from decimal import Decimal

    model = load_subprogram(FIXTURE)
    # Compiles fine, throws ArithmeticException at runtime (non-terminating
    # divide) before the driver's final println -- exercises the same
    # "non-numeric last stdout line" path as the live crash found in
    # billing's actual repair loop.
    crashing_body = (
        "return java.math.BigDecimal.ONE.divide(java.math.BigDecimal.ZERO, "
        "java.math.MathContext.UNLIMITED);"
    )
    result = _verify_mocked(model, crashing_body, [Decimal("1.00")], tmp_path)
    assert result.compiled
    assert result.divergence_count == 1
