"""repair_unit's termination guarantees — Step N4.

repair_loop.py's docstring makes four explicit promises: an attempt cap
(N4.1), immediate escalation on a repeated patch hash (N4.2), a regression
guard that never accepts a patch worse than the best seen so far (N4.4),
and a wall-clock cap (N4.5). None of these had direct unit coverage before
this file — they were only exercised indirectly through
tests/test_candidate_supplied.py (Orchestrator, real toolchain, only the
"resolved cleanly" and "no repair possible" paths) and
tests/test_memory_writeback.py (write-back, not the loop itself).

These tests call repair_unit directly with a fake InferenceClient and a
monkeypatched weaver.agent.repair_loop.verify_unit, so the loop's own
control flow is exercised without needing javac/GnuCOBOL on PATH. Only the
two things repair_unit necessarily depends on but cannot itself decide
(compilation, differential verification) are faked; the loop logic
(hashing, deterministic-vs-model dispatch, regression comparison, budget/
clock bookkeeping) is the real code under test.
"""

from __future__ import annotations

from decimal import Decimal

from weaver.agent import repair_loop as repair_loop_module
from weaver.agent.attribution import AttributionResult
from weaver.agent.inference import InferenceResponse
from weaver.agent.repair_loop import repair_unit
from weaver.agent.runspec import RunSpec
from weaver.agent.segment import Paragraph
from weaver.classification import Classification, DefectClass
from weaver.comparison import Divergence
from weaver.report import Report

UNIT_ID = "PROCESS-RECORD"


def _paragraph() -> Paragraph:
    return Paragraph(identifier=UNIT_ID, source="COMPUTE WS-INTEREST = 0.", start_line=1, end_line=1)


def _divergence(field_name: str = "RL-INTEREST") -> Divergence:
    return Divergence(
        record_index=1, byte_offset=0, field_name=field_name,
        oracle_value="10.00", candidate_value="100.00",
        numeric_delta=Decimal("90.00"), causing_input_record="001",
    )


def _result(divergence_count: int, defect_class: DefectClass = DefectClass.SCALE,
            compiled: bool = True) -> AttributionResult:
    div = _divergence()
    report = Report(UNIT_ID, total_records=200, divergences=[div] * min(divergence_count, 1),
                     divergence_count=divergence_count)
    classifications = [Classification(defect_class, 0.9, {})] if divergence_count else []
    return AttributionResult(UNIT_ID, report, classifications, compiled, None)


class _ScriptedClient:
    """Fake InferenceClient: returns each response in `responses` in order,
    one per .generate() call. Raises if called more times than scripted."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, request) -> InferenceResponse:
        self.calls += 1
        if not self._responses:
            raise AssertionError("model called more times than the test scripted")
        text = self._responses.pop(0)
        return InferenceResponse(text=text, eval_count=0, eval_duration_ns=0, from_cache=False)


def _body_json(method_body: str) -> str:
    import json
    return json.dumps({"method_body": method_body, "assumptions": []})


def test_resolves_via_deterministic_repair_without_a_model_call(monkeypatch, tmp_path):
    """SCALE has a deterministic patcher (N2) — the loop must apply it and
    verify, never falling through to a model call."""
    initial_body = (
        'ws.interest = ar.balance.multiply(ws.appliedRate)'
        '.divide(new java.math.BigDecimal("365"), java.math.RoundingMode.DOWN)'
        '.setScale(4, java.math.RoundingMode.DOWN);'
    )

    def fake_verify_unit(unit_id, body, work_dir, *, spec=None):
        if ".setScale(2, java.math.RoundingMode.DOWN)" in body:
            return _result(0)
        return _result(3, DefectClass.SCALE)

    monkeypatch.setattr(repair_loop_module, "verify_unit", fake_verify_unit)
    client = _ScriptedClient([])  # never called

    outcome = repair_unit(UNIT_ID, _paragraph(), initial_body, _result(3, DefectClass.SCALE), client,
                           tmp_path, spec=RunSpec.default())

    assert outcome.resolved is True
    assert client.calls == 0
    assert outcome.attempts[-1].outcome == "resolved (deterministic)"


def test_repeated_patch_hash_escalates_immediately(monkeypatch, tmp_path):
    """N4.2: if the model returns the exact same body already seen, the
    loop must stop rather than retrying forever."""
    initial_body = "not valid java {{{"

    def fake_verify_unit(unit_id, body, work_dir, *, spec=None):
        return _result(0, compiled=False)  # never compiles -> always model path

    monkeypatch.setattr(repair_loop_module, "verify_unit", fake_verify_unit)
    client = _ScriptedClient([_body_json(initial_body)])  # identical to seed hash

    outcome = repair_unit(UNIT_ID, _paragraph(), initial_body,
                           AttributionResult(UNIT_ID, Report(UNIT_ID, 0), [], False, "syntax error"),
                           client, tmp_path, spec=RunSpec.default().replace(max_repairs=3))

    assert outcome.resolved is False
    assert outcome.escalated is True
    assert "repeated patch hash" in outcome.escalation_reason
    assert client.calls == 1  # escalated before trying a 2nd, different attempt


def test_regression_guard_reverts_a_worse_patch(monkeypatch, tmp_path):
    """N4.4: a patch that increases divergence count must be discarded, not
    accepted, and the loop must keep the best body seen so far."""
    initial_body = "ws.interest = ORIGINAL;"
    worse_body = "ws.interest = WORSE;"

    def fake_verify_unit(unit_id, body, work_dir, *, spec=None):
        if body == worse_body:
            return _result(9, DefectClass.CONTROL_FLOW)
        return _result(3, DefectClass.CONTROL_FLOW)

    monkeypatch.setattr(repair_loop_module, "verify_unit", fake_verify_unit)
    # CONTROL_FLOW has no deterministic patcher, so both attempts go through
    # the model: first the regressive patch, then give up (budget exhausted).
    client = _ScriptedClient([_body_json(worse_body)])

    outcome = repair_unit(UNIT_ID, _paragraph(), initial_body,
                           _result(3, DefectClass.CONTROL_FLOW), client, tmp_path,
                           spec=RunSpec.default().replace(max_repairs=1))

    assert outcome.resolved is False
    assert outcome.final_body == initial_body  # reverted, not the worse patch
    assert "regression" in outcome.attempts[0].outcome
    assert "3 -> 9" in outcome.attempts[0].outcome


def test_attempt_budget_exhausted_escalates_with_reason(monkeypatch, tmp_path):
    """N4.1: distinct, still-wrong patches on every attempt must stop at
    max_repairs, not loop forever."""
    initial_body = "ws.interest = ORIGINAL;"

    def fake_verify_unit(unit_id, body, work_dir, *, spec=None):
        return _result(5, DefectClass.CONTROL_FLOW)  # always diverges, never worse

    monkeypatch.setattr(repair_loop_module, "verify_unit", fake_verify_unit)
    client = _ScriptedClient([
        _body_json("ws.interest = ATTEMPT_1;"),
        _body_json("ws.interest = ATTEMPT_2;"),
    ])

    outcome = repair_unit(UNIT_ID, _paragraph(), initial_body,
                           _result(5, DefectClass.CONTROL_FLOW), client, tmp_path,
                           spec=RunSpec.default().replace(max_repairs=2))

    assert outcome.resolved is False
    assert outcome.escalated is True
    assert outcome.escalation_reason == "attempt budget (2) exhausted"
    assert len(outcome.attempts) == 2
    assert client.calls == 2


def test_wall_clock_cap_escalates_without_consuming_the_full_attempt_budget(monkeypatch, tmp_path):
    """N4.5: the wall-clock cap is independent of the attempt cap — a slow
    provider must not be allowed to keep retrying past it."""
    monkeypatch.setattr(repair_loop_module, "WALL_CLOCK_CAP_SECONDS", -1)

    def fake_verify_unit(unit_id, body, work_dir, *, spec=None):
        raise AssertionError("verify_unit must not be reached once the wall-clock cap has expired")

    monkeypatch.setattr(repair_loop_module, "verify_unit", fake_verify_unit)
    client = _ScriptedClient([])  # never called either

    outcome = repair_unit(UNIT_ID, _paragraph(), "ws.interest = ORIGINAL;",
                           _result(5, DefectClass.CONTROL_FLOW), client, tmp_path,
                           spec=RunSpec.default().replace(max_repairs=3))

    assert outcome.resolved is False
    assert outcome.escalation_reason == "wall-clock cap exceeded"
    assert client.calls == 0
