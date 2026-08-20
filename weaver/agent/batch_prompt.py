"""Batch synthesis prompt -- Phase AA1 (migration-framework-spec.md
Section 3.1). Where `weaver/agent/prompt.py` asks for exactly one
paragraph's Java method body (interest.cob's per-unit synthesis path,
unmodified by this module), this asks for a whole
`weaver.agent.hierarchical_segment.Block`'s worth at once -- one LLM call
per block instead of one per paragraph, which is the token-budget point
of segmenting a massive file in the first place.

"Topological call rankings to maintain global context" (Section 3.1) is
`already_translated`: every paragraph translated in an earlier, leaf-first
block (`weaver.agent.hierarchical_segment.segment_hierarchical`'s block
order) is listed by name so the current block's paragraphs can call them
as ordinary sibling methods, instead of the model re-inventing or ignoring
logic that already has a real, committed translation.
"""

from __future__ import annotations

from weaver.agent.segment import Paragraph

BATCH_SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "bodies": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bodies"],
}


def build_batch_prompt(
    block_paragraphs: list[Paragraph], already_translated: dict[str, str], ws_fields: list[str],
) -> str:
    """`already_translated` maps a paragraph id already committed by an
    earlier block to its Java method name (e.g. `{"VALIDATE-INPUT":
    "validateInput"}`) -- the current block's paragraphs may call it as
    `validateInput()` on the same object. `ws_fields` lists working-storage
    field names available as `ws.<field>` -- the sole shared state
    surface, mirroring the single-paragraph prompt's `ws`/`ar` convention
    without depending on that prompt's interest.cob-specific report/totals
    machinery (this module has no `ScaffoldSpec`)."""
    paragraph_ids = [p.identifier for p in block_paragraphs]

    already_lines = "\n".join(
        f'- `{pid}` was already translated in an earlier block -- call it as `{method}()` '
        f"on `this`; do not re-implement its logic."
        for pid, method in already_translated.items()
    ) or "(none yet -- this is the first block)"

    ws_lines = "\n".join(f"- `ws.{name}`" for name in ws_fields) or "(no shared working-storage fields declared)"

    sources = "\n\n".join(
        f"--- {p.identifier} ---\n{p.source}" for p in block_paragraphs
    )

    return f"""You are translating a block of COBOL paragraphs into Java methods, as
part of a hierarchical (segment-and-merge) translation of a large
program. Each paragraph becomes exactly one Java method on the same
class, named by camelCasing its identifier (e.g. `VALIDATE-INPUT` ->
`validateInput`).

Rules:
- Return exactly one body per paragraph in this block: {paragraph_ids}.
- A body is the Java statements for that paragraph's method, not the
  method signature itself.
- Shared working-storage fields available to every method:
{ws_lines}
- Already-translated sibling methods you may call directly:
{already_lines}
- Do not invent a field or method that isn't listed above.
- Preserve each paragraph's own control flow and arithmetic; do not merge
  two paragraphs' logic into one body.

COBOL source for this block's paragraphs:
{sources}

Respond with JSON exactly matching this shape:
{{"bodies": {{{", ".join(f'"{pid}": "<java statements>"' for pid in paragraph_ids)}}}, "assumptions": []}}
"""


__all__ = ["BATCH_SYNTHESIS_SCHEMA", "build_batch_prompt"]
