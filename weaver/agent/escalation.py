"""Escalation diagnostic record — Step Q1.

When the agent gives up, it must give up well. Nine required elements
(plan's exact list): unit identifier, failing input record, oracle and
candidate values with delta, defect class and confidence, every attempt
with its patch and why it failed, assumptions the model recorded during
synthesis, suspected source lines, and the decision requested.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from weaver.agent.repair_model import RepairAttempt
from weaver.agent.segment import Paragraph
from weaver.classification import Classification
from weaver.comparison import Divergence


@dataclass
class DiagnosticRecord:
    unit_identifier: str
    failing_input_record: str | None
    oracle_value: str | None
    candidate_value: str | None
    delta: str | None
    defect_class: str | None
    confidence: float | None
    attempts: list[dict] = field(default_factory=list)  # each: {attempt, patch_summary, why_it_failed}
    assumptions: list[str] = field(default_factory=list)
    suspected_source_lines: str = ""
    decision_requested: str = ""

    def render(self) -> str:
        """Readable without reference to the codebase (Q1 acceptance test)."""
        lines = [
            f"ESCALATION: {self.unit_identifier}",
            "",
            f"Failing input record: {self.failing_input_record!r}",
            f"Oracle value:    {self.oracle_value!r}",
            f"Candidate value: {self.candidate_value!r}",
            f"Delta:           {self.delta}",
            f"Defect class:    {self.defect_class} (confidence {self.confidence})",
            "",
            f"Assumptions the model recorded during synthesis: {self.assumptions or '(none)'}",
            f"Suspected source lines: {self.suspected_source_lines}",
            "",
            "Every attempt made:",
        ]
        if not self.attempts:
            lines.append("  (no repair attempts were made -- synthesis itself failed)")
        for a in self.attempts:
            lines.append(f"  attempt {a['attempt']}: {a['patch_summary']}")
            lines.append(f"    why it failed: {a['why_it_failed']}")
        lines += ["", f"Decision requested: {self.decision_requested}"]
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def build_diagnostic_record(
    unit: Paragraph,
    escalation_reason: str,
    classification: Classification | None,
    failing_divergence: Divergence | None,
    attempts: list[RepairAttempt],
    synthesis_assumptions_or_raw: list[str],
) -> DiagnosticRecord:
    attempt_dicts = [
        {
            "attempt": a.attempt_number,
            "patch_summary": (a.body[:200] + "...") if len(a.body) > 200 else a.body,
            "why_it_failed": a.outcome + (f" ({a.diagnostics[:300]})" if a.diagnostics else ""),
        }
        for a in attempts
    ]

    return DiagnosticRecord(
        unit_identifier=unit.identifier,
        failing_input_record=failing_divergence.causing_input_record if failing_divergence else None,
        oracle_value=failing_divergence.oracle_value if failing_divergence else None,
        candidate_value=failing_divergence.candidate_value if failing_divergence else None,
        delta=str(failing_divergence.numeric_delta) if failing_divergence else None,
        defect_class=classification.defect_class.value if classification else None,
        confidence=classification.confidence if classification else None,
        attempts=attempt_dicts,
        assumptions=synthesis_assumptions_or_raw if isinstance(synthesis_assumptions_or_raw, list) else [],
        suspected_source_lines=f"{unit.identifier} lines {unit.start_line}-{unit.end_line}",
        decision_requested=(
            f"Escalated: {escalation_reason}. Accept the last attempted body as-is, "
            "supply a corrected reference body by hand, or extend the repair budget "
            "for this unit and retry."
        ),
    )
