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
    #
    # report["divergences"] is capped at 50 entries by design (FR-17,
    # weaver/report.py's DIVERGENCE_CAP) -- reclassifying only that sample
    # would check AC-10 against 50 records, not the 132 the SRS actually
    # means by "the measured divergence set". Found in the 2026-08-12
    # audit: this test passed by coincidence (the first 50 divergences
    # happen to have a representative UNKNOWN rate), not by construction.
    # Recompute the full, uncapped classification set the same way
    # weaver.cli.run_verify itself does for its terminal/JSON classification
    # breakdown, instead of trusting the capped report.json sample.
    classifications = _classify_all_divergences()
    assert len(classifications) == report["divergence_count"], (
        "independently recomputed classification count must match the "
        "report's divergence_count, or AC-10 isn't checking the real population"
    )
    summary = summarize(classifications)
    unknown_pct = summary.get(DefectClass.UNKNOWN.value, {}).get("percentage", 0.0)
    assert unknown_pct <= 15.0


def _classify_all_divergences() -> list:
    """Independently recompute classifications for every divergence between
    the real golden output and baseline/Baseline.java, mirroring
    weaver.cli.run_verify's own in-memory (uncapped) computation exactly --
    see AC-10's comment above for why report.json's capped list isn't enough.
    """
    from weaver.cli import _compile_candidate
    from weaver.execution import run_candidate
    from weaver.layout import REPORT_LAYOUT, TOTALS_LAYOUT

    main_class, classpath = _compile_candidate(REPO_ROOT / "baseline" / "Baseline.java")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        candidate_result = run_candidate(main_class, classpath, Path(tmp), ACCOUNTS, "interest.out")

    oracle_lines = _golden_lines()
    candidate_lines = candidate_result.output_lines or []
    input_lines = ACCOUNTS.read_text().splitlines()
    total_records = max(len(oracle_lines), len(candidate_lines))

    classifications = []
    for i in range(total_records):
        o_line = normalize_line_endings(oracle_lines[i]) if i < len(oracle_lines) else ""
        c_line = normalize_line_endings(candidate_lines[i]) if i < len(candidate_lines) else ""
        causing_input = input_lines[i] if i < len(input_lines) else None
        layout = REPORT_LAYOUT if i < len(input_lines) else TOTALS_LAYOUT
        div = compare_lines(i, o_line, c_line, causing_input, layout=layout)
        if div is not None:
            classifications.append(classify(div))
    return classifications
