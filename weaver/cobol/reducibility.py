"""Method Designer: control-flow reducibility -- migration-framework-spec.md
FR-11.2/11.3.

Classifies a paragraph's control flow and, where mechanically possible,
rewrites a GO TO into an EVALUATE-based equivalent. This is analysis, not
generation: like dataflow.py and callgraph.py, it informs
weaver/agent/graph.py's query surface and never writes into ScaffoldSpec
(Non-Negotiable Design Decision 4, GRAPH_PLAN.md ยง1) -- scaffold.py still
reads only ScaffoldSpec.

Scope, deliberately narrow (matches the plan's FR-11.3): only a GO TO whose
target paragraph is both known (present in the caller's paragraph table)
and mechanically rewritable is resolved. ALTER, a GO TO into a paragraph
this module cannot resolve at analysis time, or a GO TO whose target
depends on runtime-computed state, is left UNSTRUCTURED_UNRESOLVED and
excluded from synthesis -- never guessed at.

`classify()` only sees a single paragraph's source (it has no visibility
into whether a GO TO's target is resolvable elsewhere in the program), so
it can only distinguish STRUCTURED (no GO TO at all) from UNSTRUCTURED (at
least one GO TO present). The finer UNSTRUCTURED_UNRESOLVED distinction
requires the whole-program paragraph table and is made by whichever caller
also has that table (ProgramGraph.from_paragraphs(), Orchestrator._plan())
by combining classify() with rewrite()'s None result.
"""

from __future__ import annotations

import re

from weaver.agent.segment import Paragraph
from weaver.cobol.callgraph import goto_targets

# Matches a GO TO anywhere in a line, not only as the line's first token --
# the common single-line idiom `IF WS-EOF = 'Y' GO TO END-PARA END-IF.`
# puts other tokens both before and after it on the same line.
_INLINE_GOTO_RE = re.compile(r"\bGO\s+TO\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
_WHOLE_LINE_GOTO_RE = re.compile(r"^GO\s+TO\s+([A-Z0-9][A-Z0-9-]*)\.?$", re.IGNORECASE)


def classify(paragraph: Paragraph) -> str:
    """STRUCTURED if `paragraph` contains no GO TO; UNSTRUCTURED otherwise.
    See module docstring for why the finer UNSTRUCTURED_UNRESOLVED
    distinction is not made here."""
    if not goto_targets(paragraph.source):
        return "STRUCTURED"
    return "UNSTRUCTURED"


def rewrite(paragraph: Paragraph, all_paragraphs: dict[str, Paragraph]) -> str | None:
    """Mechanically rewrite every `GO TO <target>` in `paragraph` into an
    EVALUATE-based equivalent, or return None if any target cannot be
    resolved (FR-11.3: never guessed at).

    Only a target present in `all_paragraphs` is resolvable. A line that
    is *only* an unconditional `GO TO <target>.` is replaced wholesale
    with an `EVALUATE TRUE / WHEN OTHER / PERFORM <target> / END-EVALUATE`
    block. A `GO TO` embedded inline alongside other tokens on the same
    line -- the common single-branch-exit idiom
    `IF WS-EOF = 'Y' GO TO END-PARA END-IF.` -- is rewritten in place by
    substituting `PERFORM <target>` for the `GO TO <target>` substring,
    preserving the enclosing IF/END-IF exactly as written rather than
    trying to re-flow it.

    Every rewrite path is verified before returning: if the literal text
    `GO TO` still appears anywhere in the rewritten result, this function
    was not able to fully resolve the paragraph and returns None rather
    than claim success on a body that still contains an unhandled GO TO.
    """
    targets = goto_targets(paragraph.source)
    if not targets:
        return paragraph.source
    for target in targets:
        if target not in all_paragraphs:
            return None  # FR-11.3: unresolved target, never guessed at

    lines = paragraph.source.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        whole_line_match = _WHOLE_LINE_GOTO_RE.match(stripped)
        if whole_line_match:
            # The whole (non-blank) line is exactly the GO TO statement --
            # replace it wholesale with the EVALUATE block.
            target = whole_line_match.group(1).upper()
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}EVALUATE TRUE")
            out.append(f"{indent}    WHEN OTHER")
            out.append(f"{indent}        PERFORM {target}")
            out.append(f"{indent}END-EVALUATE")
        elif _INLINE_GOTO_RE.search(line):
            # GO TO appears inline alongside other tokens (e.g. inside an
            # IF ... END-IF on one line) -- substitute PERFORM <target> for
            # the GO TO <target> substring in place, leaving the rest of
            # the line (including the enclosing IF/END-IF) untouched.
            out.append(_INLINE_GOTO_RE.sub(lambda m: f"PERFORM {m.group(1).upper()}", line))
        else:
            out.append(line)

    result = "\n".join(out)
    if re.search(r"\bGO\s+TO\b", result, re.IGNORECASE):
        # Safety net: some GO TO shape wasn't actually resolved above --
        # never claim success on a body that still contains one (FR-11.3).
        return None
    return result
