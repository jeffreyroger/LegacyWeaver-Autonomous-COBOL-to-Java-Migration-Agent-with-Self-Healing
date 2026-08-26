"""Synthesis + repair wiring for a subprogram unit — Phase X4
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md).

`SubprogramOrchestrator` is a sibling to `weaver.agent.orchestrator.Orchestrator`,
not a modification of it (Non-Negotiable Design Decision 1's spirit,
extended): file-based and subprogram-based units are different enough
shapes to keep their driving loops separate. Reuses `InferenceClient`
(J1/J2, already generic over any prompt) for the model call and
`weaver.agent.subprogram_verify.verify_subprogram` (Phase X3) in place of
`attribution.verify_unit` -- commit criteria is the same the file-based
path uses: zero divergences, here over the witness set rather than over
report-line records.

Bounded by `RunSpec.max_repairs` (existing field, CLAUDE.md rule 13 --
reused rather than adding a new one).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from weaver.agent.inference import InferenceClient, InferenceError, InferenceRequest
from weaver.agent.prompt import SYNTHESIS_SCHEMA
from weaver.agent.runspec import RunSpec
from weaver.agent.subprogram_prompt import allowed_identifiers, build_subprogram_prompt
from weaver.agent.subprogram_verify import SubprogramDivergence, SubprogramVerifyResult, verify_subprogram
from weaver.agent.validate import ValidationError, auto_qualify, parse_response, regeneration_hint, static_reject
from weaver.cobol.mock_directives import find_mock_directives
from weaver.cobol.subprogram import SubprogramModel, load_subprogram


def _verify_mocked(model: SubprogramModel, body: str, witnesses: list[Decimal],
                    work_dir: Path) -> SubprogramVerifyResult:
    """Dynamic Mocking / three-axis Parity Gate (migration-framework-spec.md
    Section 2.1/2.2, Phase Z1's `weaver.agent.mocked_verify`), aggregated
    over this unit's witness set into the same `SubprogramVerifyResult`
    shape `verify_subprogram` returns, so the repair loop below needs no
    branch beyond choosing which verify function to call. A witness fails
    here if ANY of the three parity axes (terminal state, paragraphs hit,
    external stub log) diverges -- not terminal state alone -- since a
    candidate that reaches the right number by skipping the mocked call
    entirely is exactly the defect this gate exists to catch."""
    from weaver.agent.mocked_verify import verify_mocked_subprogram

    divergences: list[SubprogramDivergence] = []
    for i, witness in enumerate(witnesses):
        result = verify_mocked_subprogram(model, body, witness, work_dir / f"witness-{i}")
        if not result.compiled:
            return SubprogramVerifyResult(compiled=False, compile_error=result.compile_error)
        if not result.all_axes_match:
            divergences.append(SubprogramDivergence(
                witness_input=witness,
                oracle_output=result.oracle_output,
                candidate_output=result.candidate_output,
            ))
    return SubprogramVerifyResult(compiled=True, divergences=tuple(divergences))

TRACE_PATH = Path("generated/subprogram_trace.jsonl")
WORK_DIR = Path("generated/subprogram_orchestrator")


@dataclass
class SubprogramUnitResult:
    program_id: str
    status: str  # "committed" | "escalated"
    final_body: str | None
    model_calls: int
    duration_seconds: float
    verify_result: SubprogramVerifyResult | None = None
    escalation_reason: str | None = None


@dataclass
class SubprogramOrchestrator:
    cobol_source: Path
    witnesses: list[Decimal]
    spec: RunSpec = field(default_factory=RunSpec.default)
    trace_path: Path = TRACE_PATH
    work_dir: Path = WORK_DIR
    fresh_trace: bool = True
    # Backend attachment point, added 2026-08-26 for multi-program runs --
    # symmetric with weaver.agent.orchestrator.Orchestrator's own on_event
    # parameter. Optional and None by default: an existing caller (every
    # test, LeafOrchestrator before this change) is unaffected.
    on_event: Callable[[dict], None] | None = None

    def __post_init__(self) -> None:
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        if self.fresh_trace:
            self.trace_path.write_text("", encoding="utf-8")
        else:
            self.trace_path.touch(exist_ok=True)
        provider = os.environ.get("WEAVER_INFERENCE_PROVIDER", "ollama")
        self.client = InferenceClient(cache_dir=Path("generated/model_cache"), provider=provider)

    def _emit(self, node: str, action: str, duration: float, model_calls: int = 0, outcome: str = "") -> None:
        event = {
            "timestamp": time.time(), "unit": self.cobol_source.stem, "node": node,
            "action": action, "duration_seconds": round(duration, 3),
            "model_calls": model_calls, "outcome": outcome,
        }
        with self.trace_path.open("a") as f:
            f.write(json.dumps(event) + "\n")
        if self.on_event is not None:
            self.on_event(event)

    def run(self) -> SubprogramUnitResult:
        start = time.monotonic()
        model = load_subprogram(self.cobol_source)
        full_source = self.cobol_source.read_text(encoding="utf-8")
        mock_directives = find_mock_directives(full_source)
        base_prompt = build_subprogram_prompt(model, mock_directives)
        allowed = allowed_identifiers(model, mock_directives)

        model_calls = 0
        prompt = base_prompt
        last_body: str | None = None
        last_verify: SubprogramVerifyResult | None = None
        max_attempts = self.spec.max_repairs + 1  # first attempt + max_repairs retries

        for attempt in range(1, max_attempts + 1):
            t0 = time.monotonic()
            try:
                response = self.client.generate(InferenceRequest(prompt=prompt, schema=SYNTHESIS_SCHEMA))
            except InferenceError as e:
                self._emit("synthesise", "generate", time.monotonic() - t0, model_calls=1,
                            outcome=f"inference_error: {e}")
                model_calls += 1
                prompt = f"{base_prompt}\n\nYour previous request failed: {e}. Try again."
                continue
            model_calls += 1

            try:
                body = parse_response(response.text)
                body.method_body, _ = auto_qualify(body.method_body)
                static_reject(body, allowed)
            except ValidationError as e:
                self._emit("synthesise", "generate", time.monotonic() - t0, model_calls=1,
                            outcome=f"validation_error: {e}")
                prompt = f"{base_prompt}\n\nYour previous answer was rejected: {e}. {regeneration_hint(e)}"
                continue

            last_body = body.method_body
            self._emit("synthesise", "generate", time.monotonic() - t0, model_calls=1, outcome="ok")

            t0 = time.monotonic()
            verify_dir = self.work_dir / model.program_id / f"attempt-{attempt}"
            if mock_directives:
                last_verify = _verify_mocked(model, last_body, self.witnesses, verify_dir)
            else:
                last_verify = verify_subprogram(model, last_body, self.witnesses, verify_dir)
            if not last_verify.compiled:
                self._emit("verify", "subprogram_verify", time.monotonic() - t0,
                            outcome=f"compile_error: {last_verify.compile_error}")
                prompt = (f"{base_prompt}\n\nYour previous answer failed to compile: "
                          f"{last_verify.compile_error}")
                continue

            if last_verify.divergence_count == 0:
                duration = time.monotonic() - start
                self._emit("commit", "accept", duration, outcome="verified clean (0 divergences)")
                return SubprogramUnitResult(model.program_id, "committed", last_body, model_calls,
                                             duration, last_verify)

            self._emit("verify", "subprogram_verify", time.monotonic() - t0,
                        outcome=f"{last_verify.divergence_count} divergences")
            divergence_note = "; ".join(
                f"input={d.witness_input} expected_output={d.oracle_output} your_output={d.candidate_output}"
                for d in last_verify.divergences[:3]
            )
            if mock_directives:
                # A mocked EXEC SQL/CICS call's output is a fixed canned
                # value, constant across every witness (weaver/agent/
                # mock_generator.py's default_mock_map derives one value
                # per signature, not per input) -- found live 2026-08-26:
                # showing raw (input, expected_output) pairs alone made the
                # model curve-fit a spurious input-dependent formula through
                # what is actually a constant, instead of recognizing it
                # must call the mock. State that explicitly.
                prompt = (f"{base_prompt}\n\nYour previous answer compiled but diverged: "
                          f"{divergence_note}. This value is NOT computed from the input -- "
                          "it is an external mocked call's return value, which is why it looks "
                          "the same (or nearly the same) across different inputs. Do not try to "
                          "fit a formula to it. Call WeaverMockRuntime.call(signature) with the "
                          "exact signature given above and return its result directly.")
            else:
                prompt = (f"{base_prompt}\n\nYour previous answer compiled but diverged from the real "
                          f"COBOL subprogram's actual output on these witness inputs: {divergence_note}. "
                          "Fix the logic so every witness matches exactly.")

        duration = time.monotonic() - start
        reason = ("no compiling/validated body produced" if last_verify is None
                  else f"{last_verify.divergence_count} divergences after {max_attempts} attempts")
        self._emit("escalate", "give_up", duration, outcome=reason)
        return SubprogramUnitResult(model.program_id, "escalated", last_body, model_calls, duration,
                                     last_verify, escalation_reason=reason)


__all__ = ["SubprogramOrchestrator", "SubprogramUnitResult"]
