"""Regression tests for weaver/agent/subprogram_prompt.py's overflow-
truncation rule, added 2026-08-23 after fixtures/cobol/multiprog/leaf_a.cob
(a COMPUTE with no ON SIZE ERROR) reliably diverged on witness-search-found
large inputs: `input.multiply(2)` is exact BigDecimal arithmetic and never
truncates, but the real GnuCOBOL oracle silently drops high-order digits
past the output field's declared width. static_reject's local-variable fix
(tests/test_agent_validate.py) was needed alongside this for a candidate
using the rule's suggested BigInteger-modulo pattern to even compile.
"""

from pathlib import Path

from weaver.agent.subprogram_prompt import build_subprogram_prompt
from weaver.cobol.subprogram import load_subprogram

LEAF_A = Path("fixtures/cobol/multiprog/leaf_a.cob")


def test_overflow_truncation_rule_present_for_a_paragraph_with_no_on_size_error():
    model = load_subprogram(LEAF_A)
    prompt = build_subprogram_prompt(model)
    assert "ON SIZE ERROR" in prompt
    assert "remainder" in prompt.lower()
    # LA-OUTPUT is PIC 9(5)V99 -- 7 total digits, scale 2.
    assert "BigInteger.TEN.pow(7)" in prompt
    assert "movePointLeft(2)" in prompt


def test_overflow_truncation_rule_omitted_when_paragraph_has_on_size_error(tmp_path):
    source = LEAF_A.read_text(encoding="utf-8").replace(
        "COMPUTE LA-OUTPUT = LA-INPUT * 2",
        "COMPUTE LA-OUTPUT = LA-INPUT * 2\n           ON SIZE ERROR\n               MOVE 0 TO LA-OUTPUT",
    )
    patched = tmp_path / "leaf_a_with_size_error.cob"
    patched.write_text(source, encoding="utf-8")
    model = load_subprogram(patched)
    prompt = build_subprogram_prompt(model)
    assert "remainder" not in prompt.lower()
