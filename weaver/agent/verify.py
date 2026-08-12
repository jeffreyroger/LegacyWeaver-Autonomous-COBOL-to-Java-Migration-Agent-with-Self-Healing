"""Verify a compiled Java candidate against the confirmed oracle output.

Compares against `fixtures/data/expected/golden_interest.out` rather than
re-invoking the compiled GnuCOBOL binary on every repair iteration: the
golden file *is* a confirmed-reproducible oracle run (CLAUDE.md rule 6,
10 consecutive independent runs), and the repair loop needs many fast
verify calls per unit -- re-running an external binary per attempt buys
nothing extra here. `weaver verify`'s live-oracle path remains the
authority for the actual MVP acceptance tests; this is Phase 2's inner-loop
verifier only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from weaver.classification import Classification, classify
from weaver.comparison import compare_lines, normalize_line_endings
from weaver.execution import run_candidate
from weaver.layout import REPORT_LAYOUT, TOTALS_LAYOUT
from weaver.report import Report

GOLDEN_OUTPUT = Path("fixtures/data/expected/golden_interest.out")
INPUT_DATA = Path("fixtures/data/accounts.dat")
OUTPUT_FILENAME = "interest.out"


def verify_candidate(main_class: str, classpath: Path, golden_output: Path = GOLDEN_OUTPUT,
                      input_data: Path = INPUT_DATA, output_filename: str = OUTPUT_FILENAME,
                      report_layout: tuple = REPORT_LAYOUT, totals_layout: tuple = TOTALS_LAYOUT,
                      ) -> tuple[Report, list[Classification]]:
    golden_lines = golden_output.read_text(encoding="utf-8").splitlines()
    input_lines = input_data.read_text(encoding="utf-8").splitlines()

    # Field name -> declared decimal scale, so classification uses each
    # field's own scale instead of a value hardcoded for interest.cob's
    # fields (both of which happen to be scale 2) -- see 2026-08-12 audit.
    field_scales = {f.name: f.decimal_scale for f in (*report_layout, *totals_layout) if f.numeric}

    with tempfile.TemporaryDirectory() as tmp:
        result = run_candidate(main_class, classpath, Path(tmp), input_data, output_filename)

    candidate_lines = result.output_lines or []
    total_records = max(len(golden_lines), len(candidate_lines))
    report = Report(unit_id=main_class, total_records=total_records, exit_codes_match=(result.exit_code == 0))

    classifications = []
    for i in range(total_records):
        o_line = normalize_line_endings(golden_lines[i]) if i < len(golden_lines) else ""
        c_line = normalize_line_endings(candidate_lines[i]) if i < len(candidate_lines) else ""
        causing_input = input_lines[i] if i < len(input_lines) else None
        layout = report_layout if i < len(input_lines) else totals_layout

        div = compare_lines(i, o_line, c_line, causing_input, layout=layout)
        if div is not None:
            report.add_divergence(div)
            field_scale = field_scales.get(div.field_name, 2)
            classifications.append(classify(div, field_decimal_scale=field_scale))

    return report, classifications
