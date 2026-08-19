"""M7 — the equivalence gate (GRAPH_PLAN.md, hard, blocking gate).

Non-Negotiable Design Decision 3: `verify_unit_from_cache` must reproduce
`attribution.verify_unit`'s exact divergence set and classification before
it is allowed anywhere near a real repair loop. This is the one test that
actually proves it, against the real fixture, using a real harvested
cache (real GnuCOBOL run) and both verifiers compiled and run for real
(real javac). Skipped without cobc on PATH.

Scope note, found and deliberately excluded here: attribution.verify_unit
compares the *whole report*, including the derived TOTALS-LINE
(`TL-TOTAL`), which is an aggregate across all 200 records via the
scaffold-owned accumulator (`ws.totalInterest`) -- something
verify_unit_from_cache structurally cannot see, by design (the
accumulator is excluded from what gets seeded/checked; see
replay_verify.py's module docstring). The two verifiers are compared only
on the per-record field that both sides can independently observe
(`RL-INTEREST` on attribution's side, `WS-INTEREST` on replay's side --
the same value, per INTEREST_SPEC.report_ctor_map: "RL-INTEREST":
"ws.interest").
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from weaver.agent.attribution import verify_unit
from weaver.agent.graph import from_paragraphs
from weaver.agent.instrument import instrument
from weaver.agent.replay_verify import verify_unit_from_cache
from weaver.agent.runspec import RunSpec
from weaver.agent.segment import segment
from weaver.agent.trace_harvest import harvest

requires_cobc = pytest.mark.skipif(shutil.which("cobc") is None, reason="requires GnuCOBOL (cobc) on PATH")

REFERENCE_BODY_PATH = RunSpec.default().reference_body_path


def _harvested_fixtures(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    spec = RunSpec.default()
    source = spec.cobol_source.read_text(encoding="utf-8")
    paragraphs = segment(source)
    graph = from_paragraphs("INTEREST", paragraphs)
    copybook_dir = spec.cobol_source.parent / "copybooks"
    instrumented = instrument(source, paragraphs, graph, copybook_dir=copybook_dir)

    src_path = tmp_path / "interest_instrumented.cob"
    src_path.write_text(instrumented, encoding="utf-8")
    shutil.copy2(copybook_dir / "ACCOUNT-REC.cpy", tmp_path / "ACCOUNT-REC.cpy")
    proc = subprocess.run(["cobc", "-x", "interest_instrumented.cob"], cwd=tmp_path,
                           capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    binary = tmp_path / "interest_instrumented"
    return harvest(binary, tmp_path / "harvest_run", spec.input_data, "interest.out")


def _divergent_records(report, field_name: str) -> dict[int, str]:
    """record_index -> value pair, for divergences on the given field."""
    return {d.record_index: (d.oracle_value, d.candidate_value) for d in report.divergences
            if d.field_name == field_name}


@requires_cobc
def test_reference_body_agrees_zero_divergences_both_paths(tmp_path):
    spec = RunSpec.default()
    fixtures = _harvested_fixtures(tmp_path / "harvest")
    reference_body = REFERENCE_BODY_PATH.read_text(encoding="utf-8")

    attribution_result = verify_unit("PROCESS-RECORD", reference_body, tmp_path / "attribution", spec=spec)
    replay_result = verify_unit_from_cache("PROCESS-RECORD", reference_body, fixtures, tmp_path / "replay", spec=spec)

    assert attribution_result.compiled and replay_result.compiled
    # attribution's report may legitimately have zero OR the same
    # divergence on both sides; for a correct body both must be clean.
    assert attribution_result.report.divergence_count == 0
    assert replay_result.report.divergence_count == 0


def _assert_equivalent(attribution_result, replay_result):
    assert attribution_result.compiled and replay_result.compiled
    assert attribution_result.report.divergence_count > 0, "the planted defect should have caused divergences"
    assert replay_result.report.divergence_count > 0

    attribution_divs = _divergent_records(attribution_result.report, "RL-INTEREST")
    replay_divs = _divergent_records(replay_result.report, "WS-INTEREST")

    assert set(attribution_divs) == set(replay_divs), (
        f"divergent record sets disagree: attribution-only={set(attribution_divs) - set(replay_divs)}, "
        f"replay-only={set(replay_divs) - set(attribution_divs)}"
    )

    attribution_class_by_record = {
        d.record_index: c.defect_class
        for d, c in zip(attribution_result.report.divergences, attribution_result.classifications)
        if d.field_name == "RL-INTEREST"
    }
    replay_class_by_record = {
        d.record_index: c.defect_class
        for d, c in zip(replay_result.report.divergences, replay_result.classifications)
        if d.field_name == "WS-INTEREST"
    }
    for record_index in attribution_divs:
        assert attribution_class_by_record[record_index] == replay_class_by_record[record_index], (
            f"record {record_index}: classification disagrees "
            f"({attribution_class_by_record[record_index]} vs {replay_class_by_record[record_index]})"
        )


@requires_cobc
def test_sign_defect_agrees_between_both_verifiers(tmp_path):
    """A deliberately planted SIGN defect (spurious .negate() on the
    non-dormant interest computation) must produce the exact same set of
    divergent records and the exact same classification on both paths."""
    spec = RunSpec.default()
    fixtures = _harvested_fixtures(tmp_path / "harvest")
    reference_body = REFERENCE_BODY_PATH.read_text(encoding="utf-8")

    marker = ".setScale(2, java.math.RoundingMode.DOWN);\n}"
    assert reference_body.count(marker) == 1, "fixture assumption broken -- update the replacement target"
    broken_body = reference_body.replace(marker, ".setScale(2, java.math.RoundingMode.DOWN).negate();\n}")

    attribution_result = verify_unit("PROCESS-RECORD", broken_body, tmp_path / "attribution", spec=spec)
    replay_result = verify_unit_from_cache("PROCESS-RECORD", broken_body, fixtures, tmp_path / "replay", spec=spec)

    _assert_equivalent(attribution_result, replay_result)


@requires_cobc
def test_scale_defect_agrees_between_both_verifiers(tmp_path):
    """A deliberately planted SCALE defect (dividing by 100x too much,
    shifting the decimal point) must also produce the same divergent-
    record set and classification on both paths -- a second, independent
    defect class strengthens confidence in the equivalence proof beyond a
    single data point.

    Found while designing this test: an earlier attempt changed the
    *final* .setScale(2, DOWN) to .setScale(4, DOWN) directly. That broke
    a different invariant -- CobolEdit.floatingSign's internal
    .setScale(2, RoundingMode.UNNECESSARY) call (which assumes ws.interest
    already carries the field's true scale) then threw
    ArithmeticException, crashing the whole program rather than producing
    a clean per-field SCALE divergence. weaver.comparison also attributes
    a crashed/empty record to whichever field it examines first, not
    necessarily RL-INTEREST -- a real but separate concern from what this
    test is checking. This version keeps the final .setScale(2, DOWN)
    intact and instead perturbs the divisor, so scale stays valid
    throughout and only the *value* is wrong.
    """
    spec = RunSpec.default()
    fixtures = _harvested_fixtures(tmp_path / "harvest")
    reference_body = REFERENCE_BODY_PATH.read_text(encoding="utf-8")

    marker = "new java.math.BigDecimal(365), 10"
    assert reference_body.count(marker) == 1, "fixture assumption broken -- update the replacement target"
    broken_body = reference_body.replace(marker, "new java.math.BigDecimal(36500), 10")

    attribution_result = verify_unit("PROCESS-RECORD", broken_body, tmp_path / "attribution", spec=spec)
    replay_result = verify_unit_from_cache("PROCESS-RECORD", broken_body, fixtures, tmp_path / "replay", spec=spec)

    _assert_equivalent(attribution_result, replay_result)
