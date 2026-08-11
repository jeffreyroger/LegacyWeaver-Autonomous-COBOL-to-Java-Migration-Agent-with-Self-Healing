"""The repair loop — Step N4 (bounding + regression guard), tying together
N1 (attribution/verification), N2 (deterministic patchers), and N3
(model-assisted repair).

Termination guarantees:
- At most MAX_ATTEMPTS patch attempts per unit.
- A repeated patch hash terminates immediately and escalates (the model
  has stopped generating new ideas -- N4.2).
- Every patch is re-verified against the full 200-record input, not just
  the record that triggered repair; a patch that increases total
  divergence count is reverted and recorded as a failed attempt, never
  accepted (N4.4 -- the regression guard).
- A wall-clock cap applies independent of the attempt cap (N4.5).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent.attribution import AttributionResult, verify_unit
from weaver.agent.inference import InferenceClient, InferenceRequest
from weaver.agent.prompt import SYNTHESIS_SCHEMA
from weaver.agent.repair_deterministic import try_deterministic_repair
from weaver.agent.repair_model import RepairAttempt, build_repair_prompt
from weaver.agent.runspec import RunSpec
from weaver.agent.scaffold import field_scale as scaffold_field_scale, java_signature as scaffold_java_signature
from weaver.agent.segment import Paragraph
from weaver.agent.validate import auto_qualify, ValidationError, parse_response, regeneration_hint, static_reject
from weaver.classification import Classification
from weaver.report import Report

MAX_ATTEMPTS = 3
WALL_CLOCK_CAP_SECONDS = 120
ALLOWED_IDENTIFIERS = {"ar", "ws"}  # true for every ScaffoldSpec -- the method signature always takes (ar, ws)


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


@dataclass
class RepairOutcome:
    unit_id: str
    resolved: bool
    final_body: str
    attempts: list[RepairAttempt] = field(default_factory=list)
    escalated: bool = False
    escalation_reason: str | None = None
    trace: list[dict] = field(default_factory=list)
    final_report: Report | None = None  # backend divergence endpoint reads this verbatim


def _trace_event(events: list[dict], **kwargs) -> None:
    events.append({"timestamp": time.time(), **kwargs})


def repair_unit(
    unit_id: str,
    paragraph: Paragraph,
    initial_body: str,
    initial_result: AttributionResult,
    client: InferenceClient,
    work_dir: Path,
    *,
    spec: RunSpec | None = None,
) -> RepairOutcome:
    spec = spec or RunSpec.default()
    max_repairs = spec.max_repairs
    java_signature = scaffold_java_signature(spec.scaffold_spec)

    start_time = time.monotonic()
    attempts: list[RepairAttempt] = []
    seen_hashes: set[str] = {_body_hash(initial_body)}

    best_body = initial_body
    best_result = initial_result
    best_count = initial_result.report.divergence_count if initial_result.compiled else None

    def _report_of(r: AttributionResult) -> Report | None:
        return r.report if r.compiled else None

    for attempt_number in range(1, max_repairs + 1):
        if time.monotonic() - start_time > WALL_CLOCK_CAP_SECONDS:
            return RepairOutcome(unit_id, False, best_body, attempts, True, "wall-clock cap exceeded",
                                  final_report=_report_of(best_result))

        # --- decide what kind of repair this attempt needs ---
        if not best_result.compiled:
            defect_class = "COMPILE_ERROR"
            classification = None
            failing_div = None
            patch_body = None
        else:
            if best_result.report.divergence_count == 0:
                return RepairOutcome(unit_id, True, best_body, attempts, final_report=_report_of(best_result))
            classification: Classification = best_result.classifications[0]
            failing_div = best_result.report.divergences[0]
            defect_class = classification.defect_class
            target_scale = scaffold_field_scale(spec.scaffold_spec, failing_div.field_name)
            patch = try_deterministic_repair(defect_class, best_body, target_scale)
            patch_body = patch.patched_body if patch else None

        # --- N2: deterministic repair, no model call ---
        if patch_body is not None:
            new_body = patch_body
            source = "deterministic"
        else:
            # --- N3: model-assisted repair ---
            prompt = build_repair_prompt(
                paragraph, java_signature, best_body, defect_class,
                classification if best_result.compiled else None,
                failing_div, attempts, spec.scaffold_spec,
            )
            response = client.generate(InferenceRequest(prompt=prompt, schema=SYNTHESIS_SCHEMA))
            try:
                parsed = parse_response(response.text)
                # Change 1: same mechanical qualification fix as M2.
                parsed.method_body, _qualified = auto_qualify(parsed.method_body)
                static_reject(parsed, ALLOWED_IDENTIFIERS)
                new_body = parsed.method_body
            except ValidationError as e:
                # Change 3: a precise hint, not just the raw error -- this
                # is what the next attempt's prompt history (N3 item 7)
                # actually shows the model.
                attempts.append(RepairAttempt(
                    attempt_number, best_body,
                    f"model response invalid: {e}. Hint given on retry: {regeneration_hint(e)}",
                ))
                continue
            source = "model"

        # --- N4.2: repeated-hash termination ---
        new_hash = _body_hash(new_body)
        if new_hash in seen_hashes:
            return RepairOutcome(
                unit_id, False, best_body, attempts, True,
                "repeated patch hash -- model has stopped generating new ideas",
                final_report=_report_of(best_result),
            )
        seen_hashes.add(new_hash)

        # --- verify against the FULL input set ---
        attempt_dir = work_dir / f"attempt_{attempt_number}"
        result = verify_unit(unit_id, new_body, attempt_dir, spec=spec)

        if not result.compiled:
            attempts.append(RepairAttempt(attempt_number, new_body, "compile_error", result.compile_diagnostics))
            best_result = result
            best_body = new_body
            continue

        new_count = result.report.divergence_count
        if new_count == 0:
            attempts.append(RepairAttempt(attempt_number, new_body, f"resolved ({source})"))
            return RepairOutcome(unit_id, True, new_body, attempts, final_report=_report_of(result))

        # --- N4.4: regression guard ---
        if best_count is not None and new_count > best_count:
            attempts.append(RepairAttempt(
                attempt_number, new_body,
                f"regression ({source}): divergences {best_count} -> {new_count}, reverted",
            ))
            continue  # best_body/best_result unchanged -- patch discarded

        attempts.append(RepairAttempt(
            attempt_number, new_body,
            f"still diverges ({source}): {new_count} divergences remain "
            f"(was {best_count if best_count is not None else 'compile_error'})",
        ))
        best_body, best_result, best_count = new_body, result, new_count

    return RepairOutcome(
        unit_id, False, best_body, attempts, True,
        f"attempt budget ({max_repairs}) exhausted",
        final_report=_report_of(best_result),
    )
