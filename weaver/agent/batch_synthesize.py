"""Hierarchical batch synthesis -- Phase AA1 (migration-framework-spec.md
Section 3.1's "Code Processing Agent translates these segments, and the
Text Processing Agent iteratively merges the segment-level outputs").

Drives `weaver/agent/hierarchical_segment.py`'s blocks through one LLM
call per block (`weaver/agent/batch_prompt.py`), reusing
`weaver/agent/validate.py`'s hardened per-body checks (`auto_qualify`,
`static_reject`) unmodified -- a batch response is just several bodies
validated the same way a single-paragraph response already is, not a
second validation rule. The merge step is `weaver/agent/assemble.py`'s
existing, unmodified `assemble()`: it already accepts a `dict[str, str]`
of every paragraph's body at once, which is exactly what this module
produces by unioning every block's validated bodies in leaf-first order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from weaver.agent.batch_prompt import BATCH_SYNTHESIS_SCHEMA, build_batch_prompt
from weaver.agent.hierarchical_segment import Block, segment_hierarchical
from weaver.agent.inference import InferenceRequest
from weaver.agent.segment import Paragraph
from weaver.agent.validate import SynthesizedBody, ValidationError, auto_qualify, static_reject
from weaver.cobol.naming import java_method_name


class BatchValidationError(ValidationError):
    pass


def parse_batch_response(raw_text: str, expected_ids: list[str]) -> dict[str, str]:
    """Returns `{paragraph_id: method_body}` for exactly `expected_ids`.
    Raises `BatchValidationError` for malformed JSON, a missing "bodies"
    key, a non-string body, or a response covering a different paragraph
    set than the block actually asked for -- never silently drops or
    invents a paragraph's body."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise BatchValidationError("malformed JSON", str(e)) from e
    if not isinstance(data, dict) or "bodies" not in data:
        raise BatchValidationError("missing required key", "bodies")
    bodies = data["bodies"]
    if not isinstance(bodies, dict):
        raise BatchValidationError("bodies is not a JSON object")

    missing = set(expected_ids) - bodies.keys()
    extra = bodies.keys() - set(expected_ids)
    if missing:
        raise BatchValidationError("bodies missing paragraph(s)", str(sorted(missing)))
    if extra:
        raise BatchValidationError("bodies names paragraph(s) outside this block", str(sorted(extra)))
    for pid, body in bodies.items():
        if not isinstance(body, str):
            raise BatchValidationError(f"body for {pid} is not a string")
    return dict(bodies)


@dataclass
class HierarchicalSynthesisResult:
    bodies: dict[str, str] = field(default_factory=dict)          # paragraph_id -> validated Java body
    method_names: dict[str, str] = field(default_factory=dict)     # paragraph_id -> camelCase method name
    blocks: list[Block] = field(default_factory=list)
    had_cycle: bool = False


def synthesize_hierarchical(
    paragraphs: list[Paragraph], client, ws_fields: list[str], *,
    max_paragraphs_per_block: int = 8, max_lines_per_block: int = 400,
    allowed_identifiers: set[str] | None = None,
) -> HierarchicalSynthesisResult:
    """Segments `paragraphs`, synthesizes each block with one LLM call
    (leaf-first, so a later block's prompt can name every earlier block's
    already-translated methods), validates every returned body through
    the same hardened checks single-paragraph synthesis uses, and returns
    the merged `{paragraph_id: body}` map ready for `assemble()`."""
    from weaver.agent.hierarchical_segment import topological_paragraph_order

    allowed_identifiers = allowed_identifiers or {"ws"}
    paragraphs_by_id = {p.identifier: p for p in paragraphs}
    blocks = segment_hierarchical(
        paragraphs, max_paragraphs_per_block=max_paragraphs_per_block, max_lines_per_block=max_lines_per_block
    )
    had_cycle = topological_paragraph_order(paragraphs).had_cycle

    result = HierarchicalSynthesisResult(blocks=blocks, had_cycle=had_cycle)

    for block in blocks:
        block_paragraphs = [paragraphs_by_id[pid] for pid in block.paragraph_ids]
        prompt = build_batch_prompt(block_paragraphs, dict(result.method_names), ws_fields)
        response = client.generate(InferenceRequest(prompt=prompt, schema=BATCH_SYNTHESIS_SCHEMA))
        raw_bodies = parse_batch_response(response.text, list(block.paragraph_ids))

        for pid, raw_body in raw_bodies.items():
            body, _ = auto_qualify(raw_body)
            synthesized = SynthesizedBody(method_body=body, assumptions=[])
            static_reject(synthesized, allowed_identifiers | set(result.method_names.values()))
            result.bodies[pid] = synthesized.method_body
            result.method_names[pid] = java_method_name(pid)

    return result


__all__ = [
    "BatchValidationError", "HierarchicalSynthesisResult",
    "parse_batch_response", "synthesize_hierarchical",
]
