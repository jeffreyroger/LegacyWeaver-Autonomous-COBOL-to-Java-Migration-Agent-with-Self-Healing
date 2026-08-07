"""Integration tests against the real fixture (SRS §6 acceptance criteria).

Unlike test_comparison.py/test_classification.py (synthetic strings),
these run against the actual generated data, the actual golden output,
and the actual compiled oracle/candidate -- the same artefacts a judge
would reproduce from a clean checkout. Requires `cobc` and `javac` on
PATH (skipped automatically if either is missing, e.g. plain Windows
without WSL).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from weaver.classification import DefectClass, classify, summarize
from weaver.comparison import compare_lines, normalize_line_endings

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = REPO_ROOT / "fixtures" / "data" / "expected" / "golden_interest.out"
ACCOUNTS = REPO_ROOT / "fixtures" / "data" / "accounts.dat"

requires_toolchain = pytest.mark.skipif(
    shutil.which("cobc") is None or shutil.which("javac") is None,
    reason="requires cobc and javac on PATH (SRS §2.4 toolchain)",
)


def _golden_lines() -> list[str]:
    return GOLDEN.read_text().splitlines()


# ---------------------------------------------------------------------
# AC-9: self-comparison of the real golden output against itself must
# report zero divergences. This is the blocking gate (SRS §6.3): if
# this fails, every other divergence count in the project is suspect.
# ---------------------------------------------------------------------

def test_ac9_self_comparison_yields_zero_false_positives():
    lines = _golden_lines()
    assert len(lines) == 201, "golden output must be 200 detail + 1 totals line"

    divergences = [
        compare_lines(i, normalize_line_endings(line), normalize_line_endings(line), input_record=None)
        for i, line in enumerate(lines)
    ]
    assert all(d is None for d in divergences)


# ---------------------------------------------------------------------
# AC-8: a single, known, deliberately altered field must resolve to
# exactly one divergence with the correct field id, offset, and delta.
# ---------------------------------------------------------------------

def test_ac8_single_field_alteration_localises_correctly():
    lines = _golden_lines()
    original = lines[0]

    # Deliberately corrupt only the RL-INTEREST field (offset 30, width 11)
    # of record 0 by adding 0.01 to whatever value is printed there.
    from decimal import Decimal
    from weaver.layout import REPORT_LAYOUT

    interest_field = next(f for f in REPORT_LAYOUT if f.name == "RL-INTEREST")
    raw = original[interest_field.offset: interest_field.offset + interest_field.width]
    altered_value = Decimal(raw.strip()) + Decimal("0.01")
    altered_raw = f"{altered_value:.2f}".rjust(interest_field.width)
    altered_line = (
        original[: interest_field.offset] + altered_raw
        + original[interest_field.offset + interest_field.width:]
    )
    assert len(altered_line) == len(original)

    div = compare_lines(0, original, altered_line, input_record="dummy-input-record")
    assert div is not None
    assert div.field_name == "RL-INTEREST"
    assert div.byte_offset == interest_field.offset
    assert div.numeric_delta == Decimal("-0.01")
    assert div.causing_input_record == "dummy-input-record"

    # And every other line must still compare clean.
    other_divergences = [
        compare_lines(i, normalize_line_endings(l), normalize_line_endings(l), input_record=None)
        for i, l in enumerate(lines) if l != original
    ]
    assert all(d is None for d in other_divergences)


# ---------------------------------------------------------------------
# Full pipeline against the real oracle + real baseline. Requires the
# COBOL and Java toolchains, so it's skipped where they're unavailable
# rather than faking a result.
# ---------------------------------------------------------------------

@requires_toolchain
def test_full_pipeline_against_real_fixture(tmp_path):
    report_path = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "-m", "weaver.cli", "verify",
         "fixtures/cobol/interest.cob", "baseline/Baseline.java", "fixtures/data/accounts.dat",
         "--report", str(report_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1, result.stdout + result.stderr  # baseline is deliberately wrong
    assert report_path.exists()

    import json
    report = json.loads(report_path.read_text())

    assert report["total_records"] == 201
    assert report["divergence_count"] == 132
    assert report["exit_codes_match"] is True
    assert report["verified"] is False

    # AC-10: UNKNOWN classifications must not exceed 15% of the total.
    classifications = [
        classify(_reconstruct_divergence(d)) for d in report["divergences"]
    ]
    summary = summarize(classifications)
    unknown_pct = summary.get(DefectClass.UNKNOWN.value, {}).get("percentage", 0.0)
    assert unknown_pct <= 15.0


def _reconstruct_divergence(d: dict):
    from decimal import Decimal
    from weaver.comparison import Divergence

    delta = Decimal(d["numeric_delta"]) if d["numeric_delta"] is not None else None
    return Divergence(
        record_index=d["record_index"],
        byte_offset=d["byte_offset"],
        field_name=d["field_name"],
        oracle_value=d["oracle_value"],
        candidate_value=d["candidate_value"],
        numeric_delta=delta,
        causing_input_record=d["causing_input_record"],
    )
