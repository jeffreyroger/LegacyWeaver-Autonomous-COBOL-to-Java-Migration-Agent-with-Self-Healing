"""COBOL-specific delta-debugging adapter -- migration-framework-spec.md
Section 2.2. Plugs `weaver/agent/delta_debug.py`'s generic `ddmin` into
this harness's real verification pipeline: the oracle `ddmin` needs is a
real re-run of the already-compiled candidate (`AttributionResult.build_dir`,
Phase Y1) against a reduced input file, comparing each surviving record's
output line -- at its original index -- against the already-known-correct
`golden_output` line for that same index. No new GnuCOBOL invocation is
needed (every candidate re-run reuses the golden file the harness already
trusts, consistent with `weaver/agent/verify.py`'s existing "fast repeated
verify, real oracle already captured once" design).

Because each detail line in this harness's programs is a pure function of
its own input record (only the totals line accumulates across records),
minimizing "which records must remain in the input for this divergence to
still reproduce" converges on the single record already responsible --
the value delta debugging adds here is a *proven*, not arbitrarily
first-in-list, minimal counterexample, plus a reusable, real
`ddmin`-based mechanism for any harness input that does have cross-element
interaction.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from weaver.agent.delta_debug import ddmin
from weaver.comparison import Divergence, compare_lines, normalize_line_endings
from weaver.execution import run_candidate
from weaver.layout import Field


@dataclass(frozen=True)
class MinimizedCounterexample:
    record_indices: tuple[int, ...]
    records: tuple[str, ...]
    divergence: Divergence


def minimize_divergent_records(
    main_class: str, build_dir: Path, input_lines: list[str], golden_lines: list[str],
    candidate_record_indices: list[int], target_field: str, report_layout: tuple[Field, ...],
    work_dir: Path, *, input_file_name: str, output_file_name: str,
) -> MinimizedCounterexample:
    """`candidate_record_indices` are the (already-known, from a full-input
    verify run) 0-based indices of every divergent record whose divergence
    is on `target_field` -- the same defect class the repair loop is
    currently targeting. Returns the ddmin-minimal subset (usually one
    record) and the surviving `Divergence` for the first still-failing
    record, so `build_repair_prompt` gets a proven-minimal, not
    arbitrarily-first, counterexample.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    def _divergence_for(indices: list[int]) -> Divergence | None:
        if not indices:
            return None
        reduced_input = "\n".join(input_lines[i] for i in indices) + "\n"
        with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
            tmp_path = Path(tmp)
            # The compiled candidate class hardcodes its expected input
            # filename (weaver/agent/scaffold.py's INPUT_FILE constant) --
            # the copied reduced file must match it exactly.
            input_path = tmp_path / input_file_name
            input_path.write_text(reduced_input, encoding="utf-8")
            result = run_candidate(main_class, build_dir, tmp_path / "run", input_path, output_file_name)
            candidate_lines = result.output_lines or []
            for local_pos, original_index in enumerate(indices):
                if local_pos >= len(candidate_lines):
                    break
                o_line = normalize_line_endings(golden_lines[original_index])
                c_line = normalize_line_endings(candidate_lines[local_pos])
                div = compare_lines(original_index, o_line, c_line, input_lines[original_index], layout=report_layout)
                if div is not None and div.field_name == target_field:
                    return div
        return None

    def is_failing(indices: list[int]) -> bool:
        return _divergence_for(indices) is not None

    minimal_indices = ddmin(candidate_record_indices, is_failing)
    if not minimal_indices:
        minimal_indices = candidate_record_indices[:1]
    divergence = _divergence_for(minimal_indices)
    if divergence is None:
        # Should not happen given ddmin's precondition, but never fabricate
        # a counterexample -- fall back to the first known-divergent record.
        divergence = _divergence_for(candidate_record_indices[:1])
        minimal_indices = candidate_record_indices[:1]

    return MinimizedCounterexample(
        record_indices=tuple(minimal_indices),
        records=tuple(input_lines[i] for i in minimal_indices),
        divergence=divergence,
    )


__all__ = ["MinimizedCounterexample", "minimize_divergent_records"]
