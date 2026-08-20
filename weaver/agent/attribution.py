"""Unit attribution — Step N1.

Only the whole program produces output, so a lone differential run can't
say which paragraph caused a divergence. The fix: start from the reference
implementation (K3 -- all bodies known correct, zero divergence), replace
exactly one body with the candidate under test, and verify. Any divergence
that appears is attributable to that unit because nothing else changed.

The reference implementation is scaffolding for attribution, not part of
the product (plan's explicit instruction to state this plainly).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from weaver.agent.assemble import assemble
from weaver.agent.runspec import RunSpec
from weaver.agent.verify import verify_candidate
from weaver.classification import Classification
from weaver.report import Report

SCAFFOLD_PATH = Path("generated/Scaffold.java")
REFERENCE_BODY_PATH = Path("reference/process_record.body.java")


@dataclass
class AttributionResult:
    unit_id: str
    report: Report
    classifications: list[Classification]
    compiled: bool
    compile_diagnostics: str | None
    # Phase Y1 (delta debugging, migration-framework-spec.md Section 2.2):
    # the already-compiled candidate's classpath dir, so a minimizer can
    # re-run the SAME compiled candidate against reduced input files
    # without recompiling. None when compilation failed (nothing to run).
    build_dir: Path | None = None


def verify_unit(unit_id: str, candidate_body: str, work_dir: Path,
                *, spec: RunSpec | None = None) -> AttributionResult:
    """Assemble the reference implementation with `unit_id`'s body replaced
    by `candidate_body`, compile, and verify. All other units keep their
    known-correct reference bodies, so any resulting divergence is
    attributable to `unit_id` alone.

    `spec` supplies the scaffold, input data, and golden output. Defaults to
    RunSpec.default() so existing call sites keep working; it is threaded
    explicitly so a caller-supplied path is never silently ignored.
    """
    spec = spec or RunSpec.default()

    bodies = {spec.reference_paragraph_id: spec.reference_body_path.read_text(encoding="utf-8")}
    bodies[unit_id] = candidate_body  # overwrite the unit under test

    assembled = assemble(spec.scaffold_path.read_text(encoding="utf-8"), bodies)
    src_path = work_dir / "Scaffold.java"
    build_dir = work_dir / "build"
    work_dir.mkdir(parents=True, exist_ok=True)
    src_path.write_text(assembled, encoding="utf-8")

    proc = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(build_dir), str(src_path)],
                           capture_output=True, text=True)
    if proc.returncode != 0:
        return AttributionResult(unit_id, Report(unit_id, 0), [], False, proc.stderr)

    report, classifications = verify_candidate(
        "Scaffold", build_dir,
        golden_output=spec.golden_output,
        input_data=spec.input_data,
        output_filename=spec.scaffold_spec.output_file,
        report_layout=spec.scaffold_spec.report_layout,
        totals_layout=spec.scaffold_spec.totals_layout,
    )
    return AttributionResult(unit_id, report, classifications, True, None, build_dir=build_dir)


if __name__ == "__main__":
    import sys
    from pathlib import Path as _P

    # N1 acceptance test: deliberately corrupt PROCESS-RECORD (skip the
    # dormant zero-out) and confirm divergences appear, attributed to it.
    corrupted = REFERENCE_BODY_PATH.read_text(encoding="utf-8").replace(
        'ws.interest = java.math.BigDecimal.ZERO.setScale(2);',
        'ws.interest = new java.math.BigDecimal("999.99");  // deliberately wrong',
    )
    result = verify_unit("PROCESS-RECORD", corrupted, _P("generated/attribution_test"))
    print(f"unit={result.unit_id} compiled={result.compiled} "
          f"divergences={result.report.divergence_count}")
    assert result.compiled
    assert result.report.divergence_count > 0, "corruption should have produced divergences"
    print("N1 acceptance test: PASS -- corruption attributed to PROCESS-RECORD")
