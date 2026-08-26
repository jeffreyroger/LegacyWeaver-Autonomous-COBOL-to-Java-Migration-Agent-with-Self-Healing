"""Regression tests for RunSpec.use_batch_synthesis wiring into
Orchestrator, added 2026-08-26.

Before this change, weaver/agent/hierarchical_segment.py and
weaver/agent/batch_synthesize.py/batch_prompt.py (Phase AA1,
migration-framework-spec.md Section 3.1) were fully implemented and unit-
tested in isolation but had zero production callers -- Orchestrator only
ever called synthesize_paragraph, one model call per paragraph, no matter
how large the program. This wires hierarchical batch synthesis in as an
opt-in FIRST-DRAFT source for _process_unit, falling back to the existing
per-paragraph path when the flag is off (default) or a unit's draft is
missing -- the already-proven repair loop is untouched either way.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weaver.agent.orchestrator import Orchestrator
from weaver.agent.runspec import RunSpec
from weaver.agent.segment import Paragraph


def _paragraph(identifier: str, source: str) -> Paragraph:
    return Paragraph(identifier=identifier, source=source, start_line=1, end_line=source.count("\n") + 1)


def test_use_batch_synthesis_defaults_to_false_and_leaves_draft_bodies_empty(tmp_path):
    spec = RunSpec.default()
    assert spec.use_batch_synthesis is False
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")
    assert orch._batch_draft_bodies == {}


def test_run_batch_synthesis_populates_draft_bodies_from_a_mocked_client(tmp_path, monkeypatch):
    import json

    spec = RunSpec.default().replace(use_batch_synthesis=True)
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")

    fake_response = MagicMock()
    fake_response.text = json.dumps({"bodies": {"COMPUTE-PENALTY": "ws.total = ws.total.add(ar.balance);"}})
    orch.client = MagicMock()
    orch.client.generate.return_value = fake_response

    units = [_paragraph("COMPUTE-PENALTY", "       COMPUTE-PENALTY.\n           ADD AR-BALANCE TO WS-TOTAL.\n")]
    orch._run_batch_synthesis(units)

    assert orch._batch_draft_bodies == {"COMPUTE-PENALTY": "ws.total = ws.total.add(ar.balance);"}
    assert orch.client.generate.call_count == 1


def test_run_batch_synthesis_failure_leaves_draft_bodies_empty_never_raises(tmp_path):
    spec = RunSpec.default().replace(use_batch_synthesis=True)
    orch = Orchestrator(spec=spec, trace_path=tmp_path / "trace.jsonl", state_path=tmp_path / "state.json")

    fake_response = MagicMock()
    fake_response.text = "not valid json"
    orch.client = MagicMock()
    orch.client.generate.return_value = fake_response

    units = [_paragraph("COMPUTE-PENALTY", "       COMPUTE-PENALTY.\n           ADD AR-BALANCE TO WS-TOTAL.\n")]
    orch._run_batch_synthesis(units)  # must not raise

    assert orch._batch_draft_bodies == {}


def test_cli_flag_threads_use_batch_synthesis():
    from weaver.cli import build_parser, build_migrate_spec

    parser = build_parser()
    args_on = parser.parse_args(["migrate", "fixtures/cobol/interest.cob", "--use-batch-synthesis"])
    assert build_migrate_spec(args_on).use_batch_synthesis is True

    args_off = parser.parse_args(["migrate", "fixtures/cobol/interest.cob"])
    assert build_migrate_spec(args_off).use_batch_synthesis is False
