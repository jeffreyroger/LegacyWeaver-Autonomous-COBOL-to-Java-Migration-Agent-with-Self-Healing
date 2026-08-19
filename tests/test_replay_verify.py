"""verify_unit_from_cache — GRAPH_PLAN.md M6 (verifier half) / M7 setup.

Design (agreed after empirically testing GnuCOBOL's own DISPLAY format --
see the design discussion this module implements): never re-implement
COBOL decode/encode semantics a second time.

- `ar` is never taken from the cache at all -- record_index maps directly
  to a line in the real input_data file, decoded via the *real*
  AccountRecord.decode() the assembled Scaffold.java already has.
- `ws` seeding/checking uses GnuCOBOL's own DISPLAY text directly:
  empirically confirmed (this session, WSL GnuCOBOL 3.2.0) that a signed
  WORKING-STORAGE field with no SEPARATE clause DISPLAYs as clean
  "+0000123.45"/"-0000123.45" text, and Java's `BigDecimal(String)`
  parses that directly -- no custom decode helper needed for WS fields.
- Only ScaffoldSpec.ws_fields *excluding the accumulator* are seeded/
  checked (weaver.agent.scaffold.ws_accessors already computes exactly
  this set -- the accumulator is scaffold-owned, not paragraph-owned, a
  distinction discovered by reading generated/Scaffold.java's actual
  main-loop wiring during this design).

These tests cover the toolchain-free half: fixture-data serialization and
driver source generation. The real compile+run integration (M7's
equivalence proof against attribution.verify_unit) needs cobc+javac and
lives in test_replay_verify_live.py, skipped here.
"""

from __future__ import annotations

from weaver.agent.replay_verify import _fixture_data_text, _generate_driver
from weaver.agent.scaffold import INTEREST_SPEC, ws_accessors
from weaver.agent.trace_harvest import UnitFixture


def test_fixture_data_text_emits_one_row_per_field_per_phase():
    fixtures = [
        UnitFixture("PROCESS-RECORD", 0, {"WS-APPLIED-RATE": "0.06325"}, {"WS-INTEREST": "+0000123.45"}),
    ]
    text = _fixture_data_text(fixtures)
    lines = text.strip("\n").splitlines()

    assert "0\tENTRY\tWS-APPLIED-RATE\t0.06325" in lines
    assert "0\tEXIT\tWS-INTEREST\t+0000123.45" in lines


def test_fixture_data_text_covers_multiple_records():
    fixtures = [
        UnitFixture("PROCESS-RECORD", 0, {"A": "1"}, {"B": "2"}),
        UnitFixture("PROCESS-RECORD", 1, {"A": "3"}, {"B": "4"}),
    ]
    text = _fixture_data_text(fixtures)
    assert "0\tENTRY\tA\t1" in text
    assert "1\tENTRY\tA\t3" in text


def test_generate_driver_seeds_only_non_accumulator_ws_fields():
    driver = _generate_driver(INTEREST_SPEC)

    accessors = ws_accessors(INTEREST_SPEC)
    assert "WS-APPLIED-RATE" in accessors and "WS-INTEREST" in accessors
    for cobol_name, java_expr in accessors.items():
        assert f'"{cobol_name}"' in driver
        assert java_expr in driver

    # The accumulator is scaffold-owned -- must never be seeded/checked by
    # the unit-level driver (it's not part of what the candidate touches).
    assert "WS-TOTAL-INTEREST" not in driver


def test_generate_driver_calls_the_candidate_paragraph_method():
    driver = _generate_driver(INTEREST_SPEC)
    assert f"Scaffold.{INTEREST_SPEC.paragraph_method}(ar, ws)" in driver


def test_generate_driver_handles_a_throwing_candidate_without_crashing_the_driver():
    """A synthesized body can throw at runtime (e.g. an unhandled
    ArithmeticException) -- the driver must report that record's checks as
    diverged, not let the whole harvest run die on one bad record."""
    driver = _generate_driver(INTEREST_SPEC)
    assert "catch" in driver
