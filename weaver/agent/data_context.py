"""Build the per-paragraph data context — Step L2.

For each paragraph, determine which fields it touches by matching
identifiers in its text against the field table, classified read/write by
statement verb. Over-inclusion is fine (costs prompt tokens, not
correctness, per the plan); under-inclusion is the failure mode to avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from weaver.agent.scaffold import CONDITION_NAMES, ConditionName
from weaver.agent.segment import Paragraph
from weaver.layout import INPUT_LAYOUT, Field

# WORKING-STORAGE items are not in weaver.layout (that module is scoped to
# the MVP harness's I/O byte layouts, SRS §5.1/5.2), so they're declared
# here — still data, not parsed from source, matching K's approach to
# condition names.
WORKING_STORAGE_FIELDS: tuple[str, ...] = (
    "WS-EOF-FLAG", "WS-APPLIED-RATE", "WS-INTEREST", "WS-TOTAL-INTEREST",
)

_WRITE_VERBS = (
    "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "SET", "INITIALIZE",
)

# "MOVE X TO Y [Y2 ...]" / "COMPUTE Y = ..." / "ADD X TO Y" / "SET cond TO TRUE"
# -- the write target is the identifier(s) after TO, or the COMPUTE LHS.
_TO_TARGET_RE = re.compile(r"\bTO\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
_COMPUTE_LHS_RE = re.compile(r"\bCOMPUTE\s+([A-Z0-9][A-Z0-9-]*)\s*=", re.IGNORECASE)
_SET_TARGET_RE = re.compile(r"\bSET\s+([A-Z0-9][A-Z0-9-]*)\s+TO\s+TRUE", re.IGNORECASE)


@dataclass(frozen=True)
class DataContext:
    paragraph_id: str
    read_fields: tuple[str, ...]
    written_fields: tuple[str, ...]
    condition_names: tuple[ConditionName, ...]


def _all_identifiers() -> dict[str, Field]:
    return {f.name: f for f in INPUT_LAYOUT}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Z][A-Z0-9-]*", text.upper()))


def build_context(paragraph: Paragraph) -> DataContext:
    known_fields = list(_all_identifiers().keys()) + list(WORKING_STORAGE_FIELDS)
    present = {name for name in known_fields if name in _tokens(paragraph.source)}

    written: set[str] = set()
    for m in _TO_TARGET_RE.finditer(paragraph.source):
        name = m.group(1).upper()
        if name in present:
            written.add(name)
    for m in _COMPUTE_LHS_RE.finditer(paragraph.source):
        name = m.group(1).upper()
        if name in present:
            written.add(name)
    for m in _SET_TARGET_RE.finditer(paragraph.source):
        # SET targets a condition name (e.g. WS-EOF), not a plain field;
        # still recorded as written since it mutates the parent field.
        written.add(m.group(1).upper())

    read = present - written

    # Attach any condition name whose parent field appears in the paragraph.
    conditions = tuple(
        c for c in CONDITION_NAMES
        if c.parent_field in present or c.parent_field in read or c.parent_field in written
    )

    if not present:
        # Empty context is a failure mode (L2 acceptance test) -- fall back
        # to the full field table rather than sending nothing.
        read = set(known_fields)
        written = set()
        conditions = CONDITION_NAMES

    return DataContext(
        paragraph_id=paragraph.identifier,
        read_fields=tuple(sorted(read)),
        written_fields=tuple(sorted(written)),
        condition_names=conditions,
    )


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from weaver.agent.segment import segment

    src = Path(sys.argv[1]).read_text()
    for p in segment(src):
        ctx = build_context(p)
        print(f"{ctx.paragraph_id}:")
        print(f"  read:       {ctx.read_fields}")
        print(f"  written:    {ctx.written_fields}")
        print(f"  conditions: {[c.java_name for c in ctx.condition_names]}")
