"""Synthesis driver — Steps M3/M4.

Ties together L (segment + context), M1 (prompt), the inference client
(J), M2 (validate), and assembly (K's assemble.py) into one call:
paragraph in, compiling (or diagnosed-failing) candidate out.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from weaver.agent.assemble import assemble
from weaver.agent.data_context import build_context
from weaver.agent.inference import InferenceClient, InferenceError, InferenceRequest
from weaver.agent.prompt import SYNTHESIS_SCHEMA, build_synthesis_prompt
from weaver.agent.runspec import RunSpec
from weaver.agent.scaffold import java_signature as scaffold_java_signature
from weaver.agent.segment import Paragraph, segment
from weaver.agent.validate import (
    SynthesizedBody, ValidationError, auto_qualify, parse_response, regeneration_hint, static_reject,
)

MAX_REGENERATE_ATTEMPTS = 3  # M2: regenerate up to twice, then escalate as synthesis failure
ALLOWED_IDENTIFIERS = {"ar", "ws"}  # true for every ScaffoldSpec -- the method signature always takes (ar, ws)


class SynthesisFailure(RuntimeError):
    """Raised when M2 validation fails MAX_REGENERATE_ATTEMPTS times running."""


@dataclass
class SynthesisResult:
    paragraph_id: str
    body: SynthesizedBody | None
    validation_attempts: int
    prompt: str
    raw_responses: list[str]


def synthesize_paragraph(paragraph: Paragraph, client: InferenceClient, *, spec: RunSpec | None = None,
                          ) -> SynthesisResult:
    spec = spec or RunSpec.default()
    scaffold_spec = spec.scaffold_spec
    context = build_context(paragraph, scaffold_spec)
    java_signature = scaffold_java_signature(scaffold_spec)
    prompt = build_synthesis_prompt(paragraph, context, java_signature, scaffold_spec,
                                     extra_context=spec.extra_prompt_context)

    raw_responses: list[str] = []
    last_error: ValidationError | None = None
    for attempt in range(1, MAX_REGENERATE_ATTEMPTS + 1):
        # Vary nothing about the request itself; a cache-hit replay is a
        # legitimate "regeneration" only insofar as the model is
        # deterministic (J2) -- real non-determinism recovery comes from
        # N3's repair loop, not from M2's regenerate step re-asking the
        # same question. M2 regenerates by nudging the prompt with the
        # prior failure so the retry isn't a guaranteed repeat.
        this_prompt = prompt if attempt == 1 else (
            f"{prompt}\n\nYour previous answer was rejected: {last_error}. {regeneration_hint(last_error)}"
        )
        try:
            response = client.generate(InferenceRequest(prompt=this_prompt, schema=SYNTHESIS_SCHEMA))
        except InferenceError as e:
            # The provider itself failed to produce a usable completion
            # (rate limit exhausted after retry, unparseable output, ...) --
            # treat exactly like a rejected response so it counts against
            # MAX_REGENERATE_ATTEMPTS and falls through to a normal
            # synthesis_failure/escalation instead of crashing the run.
            raw_responses.append(str(e))
            last_error = ValidationError("inference request failed", str(e))
            continue
        raw_responses.append(response.text)
        try:
            body = parse_response(response.text)
            # Change 1: mechanical fix, not a model concern -- rewrite bare
            # BigDecimal/RoundingMode to java.math.* before static_reject
            # ever sees the body.
            body.method_body, _qualified = auto_qualify(body.method_body)
            static_reject(body, ALLOWED_IDENTIFIERS)
            return SynthesisResult(paragraph.identifier, body, attempt, prompt, raw_responses)
        except ValidationError as e:
            last_error = e
            continue

    return SynthesisResult(paragraph.identifier, None, MAX_REGENERATE_ATTEMPTS, prompt, raw_responses)


@dataclass
class CompileResult:
    success: bool
    diagnostics: str | None


def assemble_and_compile(scaffold_path: Path, paragraph_id: str, body: str,
                          out_path: Path, build_dir: Path) -> CompileResult:
    assembled = assemble(scaffold_path.read_text(encoding="utf-8"), {paragraph_id: body})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(assembled, encoding="utf-8")

    build_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(build_dir), str(out_path)],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return CompileResult(True, None)
    # M3: attribute compiler diagnostics to the owning paragraph rather than
    # forwarding raw output -- there is exactly one synthesized unit in
    # this fixture, so attribution is trivial, but the shape (paragraph_id
    # -> diagnostics) is what N1 and Q1 consume later.
    return CompileResult(False, proc.stderr)


if __name__ == "__main__":
    import json
    import sys

    cobol_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/cobol/interest.cob")
    scaffold_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("generated/Scaffold.java")
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("generated/synthesis")

    paragraphs = {p.identifier: p for p in segment(cobol_path.read_text(encoding="utf-8"))}
    target = paragraphs["PROCESS-RECORD"]

    client = InferenceClient(cache_dir=Path("generated/model_cache"))
    result = synthesize_paragraph(target, client)

    report = {
        "paragraph_id": result.paragraph_id,
        "validation_attempts": result.validation_attempts,
        "synthesized": result.body is not None,
    }

    if result.body is None:
        report["status"] = "synthesis_failure"
        print(json.dumps(report, indent=2))
        sys.exit(1)

    report["assumptions"] = result.body.assumptions
    report["method_body"] = result.body.method_body

    compile_result = assemble_and_compile(
        scaffold_path, "PROCESS-RECORD", result.body.method_body,
        out_dir / "Scaffold.java", out_dir / "build",
    )
    report["compiles"] = compile_result.success
    if not compile_result.success:
        report["diagnostics"] = compile_result.diagnostics

    print(json.dumps(report, indent=2))
