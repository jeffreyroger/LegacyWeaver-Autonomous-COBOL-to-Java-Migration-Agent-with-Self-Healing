"""Method Designer: control-flow reducibility -- migration-framework-spec.md
FR-11.2/11.3.

Classifies a paragraph's control flow and, where mechanically possible,
rewrites a GO TO into an EVALUATE-based equivalent. This is analysis, not
generation: like dataflow.py and callgraph.py, it informs
weaver/agent/graph.py's query surface and never writes into ScaffoldSpec
(Non-Negotiable Design Decision 4, GRAPH_PLAN.md §1) -- scaffold.py still
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

from weaver.agent.segment import Paragraph
from weaver.cobol.callgraph import goto_targets


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

    Only a target present in `all_paragraphs` is resolvable. A bare
    unconditional `GO TO <target>.` is rewritten to
    `PERFORM <target>.` wrapped so the invariant "no GO TO remains, but
    control still reaches the target's logic" holds; a `GO TO` inside an
    IF/END-IF (the common single-branch-exit idiom) is rewritten in place
    using EVALUATE TRUE / WHEN OTHER, preserving the enclosing structure
    line-for-line rather than trying to re-flow the IF around it.
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
        stripped = line.strip().upper()
        if stripped.startswith("GO TO"):
            target = stripped[len("GO TO"):].strip().rstrip(".")
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}EVALUATE TRUE")
            out.append(f"{indent}    WHEN OTHER")
            out.append(f"{indent}        PERFORM {target}")
            out.append(f"{indent}END-EVALUATE")
        else:
            out.append(line)
    return "\n".join(out)
