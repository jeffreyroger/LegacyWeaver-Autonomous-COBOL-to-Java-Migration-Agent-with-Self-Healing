"""Phase Y1 wiring test -- RunSpec.use_delta_debugging=True makes
repair_unit hand build_repair_prompt a ddmin-minimized counterexample
(one of the several real divergent records attribution.verify_unit found)
instead of arbitrarily using divergences[0], using the real compiled
candidate's build_dir (no fakes on the compile/verify side)."""

import shutil

import pytest

from weaver.agent import repair_loop as repair_loop_module
from weaver.agent.attribution import REFERENCE_BODY_PATH, verify_unit
from weaver.agent.inference import InferenceResponse
from weaver.agent.repair_loop import repair_unit
from weaver.agent.runspec import RunSpec
from weaver.agent.segment import Paragraph

requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


class _OneShotClient:
    """Returns the real reference body (known-correct) on the first and
    only call -- proves the loop reaches a model call with a captured
    failing_div, without needing a live model."""

    def __init__(self, body: str):
        self._body = body
        self.calls = 0

    def generate(self, request) -> InferenceResponse:
        import json
        self.calls += 1
        return InferenceResponse(
            text=json.dumps({"method_body": self._body, "assumptions": []}),
            eval_count=0, eval_duration_ns=0, from_cache=False,
        )


@requires_javac
def test_delta_debugging_selects_a_real_minimized_counterexample(tmp_path, monkeypatch):
    spec = RunSpec.default().replace(use_delta_debugging=True, max_repairs=1)
    reference_body = REFERENCE_BODY_PATH.read_text(encoding="utf-8")
    corrupted = reference_body.replace(
        "ws.interest = java.math.BigDecimal.ZERO.setScale(2);",
        'ws.interest = new java.math.BigDecimal("999.99");  // deliberately wrong',
    )
    initial_result = verify_unit("PROCESS-RECORD", corrupted, tmp_path / "attribution", spec=spec)
    assert initial_result.compiled
    same_field = [d for d in initial_result.report.divergences if d.field_name == "RL-INTEREST"]
    assert len(same_field) > 1, "need multiple same-field divergences for minimization to have real work to do"

    captured = {}
    real_build_repair_prompt = repair_loop_module.build_repair_prompt

    def spying_build_repair_prompt(paragraph, java_signature, body, defect_class, classification,
                                    failing_div, attempts, scaffold_spec):
        captured["failing_div"] = failing_div
        return real_build_repair_prompt(paragraph, java_signature, body, defect_class, classification,
                                         failing_div, attempts, scaffold_spec)

    monkeypatch.setattr(repair_loop_module, "build_repair_prompt", spying_build_repair_prompt)

    paragraph = Paragraph(identifier="PROCESS-RECORD", source=corrupted, start_line=1, end_line=1)
    client = _OneShotClient(reference_body)
    outcome = repair_unit("PROCESS-RECORD", paragraph, corrupted, initial_result, client,
                           tmp_path / "repair", spec=spec)

    assert outcome.resolved  # the scripted client hands back the real known-correct body
    assert "failing_div" in captured
    assert captured["failing_div"].field_name == "RL-INTEREST"
    assert captured["failing_div"].record_index in {d.record_index for d in same_field}
