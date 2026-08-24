"""Regression tests for LeafOrchestrator._render_call_semantics, added
2026-08-23 (migration-framework-spec.md Section 5 "Upstream Propagation").

Found while debugging fixtures/cobol/multiprog/root.cob's synthesis: just
showing a calling program's model raw (input, output) witness pairs for a
CALLed subprogram was not enough -- granite-code:20b ignored them and fell
back to a memorized COBOL idiom. Fitting the real witnesses against the
two shapes this project's own fixtures need (constant multiplier, constant
additive offset) and stating the fitted relationship as an already-proven
fact is what actually got the model to translate CALL "LEAF-A"/"LEAF-B"
correctly -- verified live end-to-end (weaver migrate --leaf-first
fixtures/cobol/multiprog committed ROOT's PROCESS-RECORD on the first
synthesis attempt, 0 divergences against the real golden output).
"""

from decimal import Decimal
from pathlib import Path

from weaver.agent.leaf_orchestrator import LeafOrchestrator
from weaver.agent.trace_harvest import UnitFixture
from weaver.cobol.subprogram import load_subprogram

LEAF_A = Path("fixtures/cobol/multiprog/leaf_a.cob")
LEAF_B = Path("fixtures/cobol/multiprog/leaf_b.cob")


def _fixtures(pairs: list[tuple[Decimal, Decimal]], in_name: str, out_name: str,
               in_scale: int, out_scale: int) -> list[UnitFixture]:
    def _raw(value: Decimal, scale: int) -> str:
        return str(int(value.scaleb(scale)))

    return [
        UnitFixture(paragraph_id="MAIN-PARA", record_index=i,
                    input_state={in_name: _raw(inp, in_scale)},
                    output_state={out_name: _raw(out, out_scale)})
        for i, (inp, out) in enumerate(pairs)
    ]


def test_fits_a_constant_multiplier():
    model = load_subprogram(LEAF_A)
    fixtures = _fixtures(
        [(Decimal("1.00"), Decimal("2.00")), (Decimal("2.50"), Decimal("5.00")),
         (Decimal("10.00"), Decimal("20.00"))],
        "LA-INPUT", "LA-OUTPUT", 2, 2,
    )
    text = LeafOrchestrator._render_call_semantics("LEAF-A", model, fixtures)
    assert "output = input * 2" in text
    assert "already-verified" not in text or "IS this subprogram" in text


def test_fits_a_constant_additive_offset():
    model = load_subprogram(LEAF_B)
    fixtures = _fixtures(
        [(Decimal("1.00"), Decimal("11.00")), (Decimal("2.50"), Decimal("12.50")),
         (Decimal("0.00"), Decimal("10.00"))],
        "LB-INPUT", "LB-OUTPUT", 2, 2,
    )
    text = LeafOrchestrator._render_call_semantics("LEAF-B", model, fixtures)
    assert "output = input + 10" in text


def test_falls_back_to_raw_examples_when_no_simple_formula_fits():
    """A subprogram whose real behavior is neither a constant multiplier
    nor a constant additive offset gets only the raw witness examples --
    never a fabricated formula (disclosed narrow scope, see
    leaf_orchestrator.py's _render_call_semantics docstring)."""
    model = load_subprogram(LEAF_A)
    fixtures = _fixtures(
        [(Decimal("1.00"), Decimal("1.00")), (Decimal("2.00"), Decimal("4.00")),
         (Decimal("3.00"), Decimal("9.00"))],  # squares -- neither shape fits
        "LA-INPUT", "LA-OUTPUT", 2, 2,
    )
    text = LeafOrchestrator._render_call_semantics("LEAF-A", model, fixtures)
    assert "Fitted relationship" not in text
    assert "input=1" in text and "output=1" in text
