"""Hierarchical recursive segment-and-merge -- Phase AA1
(migration-framework-spec.md Section 3.1): "For massive source code files,
the code is recursively split into functional blocks... utilizing
topological call rankings to maintain global context."

Generic over any `weaver.agent.segment.Paragraph` list -- no `ScaffoldSpec`,
no report/totals/accumulator concepts, no dependency on this repo's
existing interest.cob-flavored synthesis machinery. The only two real
things this module needs are already built, unmodified, and reused
verbatim:
  - `weaver.cobol.callgraph.performs()` (Phase W task 3) for intra-file
    PERFORM edges, restricted to the paragraph's own known identifiers.
  - `weaver.agent.segment.Paragraph`'s atomic unit -- a paragraph is never
    split; "recursive" splitting only ever divides a *list* of paragraphs.

Leaf-first ordering (callees before callers) is chosen deliberately, not
arbitrarily: it is the same principle `weaver/cobol/program_dag.py` already
applies at cross-program granularity (Task 7) -- when paragraph B is
translated before paragraph A (which PERFORMs B), A's block can be told
B's already-translated Java method signature as real context, exactly
matching the spec's "topological call rankings to maintain global
context" phrase.

Cycles (mutually recursive PERFORMs, not rare in COBOL control flow) are
never treated as an error: `topological_paragraph_order` degrades to a
deterministic, disclosed fallback (documented on `HAD_CYCLE`) rather than
raising or silently mis-ordering.
"""

from __future__ import annotations

from dataclasses import dataclass

from weaver.cobol.callgraph import performs
from weaver.agent.segment import Paragraph


def paragraph_call_graph(paragraphs: list[Paragraph]) -> dict[str, frozenset[str]]:
    """id -> the set of other known paragraph ids it PERFORMs (including
    PERFORM ... THRU's endpoint). Self-PERFORMs are dropped -- they carry
    no ordering information."""
    known = {p.identifier for p in paragraphs}
    graph: dict[str, frozenset[str]] = {}
    for p in paragraphs:
        callees: set[str] = set()
        for edge in performs(p.source, known):
            if edge.target != p.identifier:
                callees.add(edge.target)
            if edge.thru_target and edge.thru_target != p.identifier:
                callees.add(edge.thru_target)
        graph[p.identifier] = frozenset(callees)
    return graph


@dataclass(frozen=True)
class TopologicalOrder:
    order: tuple[str, ...]  # leaf-first: a callee always precedes every paragraph that PERFORMs it, except within a cycle
    had_cycle: bool


def topological_paragraph_order(paragraphs: list[Paragraph]) -> TopologicalOrder:
    """Leaf-first (callees-before-callers) order over the intra-file
    PERFORM call graph. Standard Kahn's algorithm peeling nodes with
    zero remaining out-edges (i.e. paragraphs that call nothing not yet
    placed). When a cycle leaves no zero-out-degree node, the node with
    the fewest remaining out-edges is peeled next (ties broken
    alphabetically for determinism) -- a disclosed, deterministic
    approximation, never a crash and never a silent, unprincipled order.
    """
    graph = {k: set(v) for k, v in paragraph_call_graph(paragraphs).items()}
    remaining = set(graph)
    order: list[str] = []
    had_cycle = False

    while remaining:
        zero_out = sorted(n for n in remaining if not (graph[n] & remaining))
        if not zero_out:
            had_cycle = True
            # No true leaf remains -- peel the node with fewest live
            # out-edges (closest to being a leaf), alphabetical tiebreak.
            zero_out = [min(remaining, key=lambda n: (len(graph[n] & remaining), n))]
        for node in zero_out:
            order.append(node)
            remaining.discard(node)

    return TopologicalOrder(order=tuple(order), had_cycle=had_cycle)


@dataclass(frozen=True)
class Block:
    index: int
    depth: int
    paragraph_ids: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.paragraph_ids)


def _line_count(paragraphs_by_id: dict[str, Paragraph], ids: list[str]) -> int:
    return sum(paragraphs_by_id[i].source.count("\n") + 1 for i in ids)


def segment_hierarchical(
    paragraphs: list[Paragraph], *, max_paragraphs_per_block: int = 8, max_lines_per_block: int = 400,
) -> list[Block]:
    """Splits `paragraphs` into topologically-ordered blocks, each within
    both budgets, by RECURSIVELY halving any oversized ordered slice --
    the literal "recursively split into functional blocks" the spec
    names. A single paragraph is always atomic: if one paragraph alone
    exceeds `max_lines_per_block`, it still becomes its own one-paragraph
    block rather than being further divided (there is no smaller COBOL
    unit than a paragraph in this harness -- Non-Negotiable posture shared
    with every other narrow-scope parser in this repo: split what can
    honestly be split, never guess at splitting further).
    """
    paragraphs_by_id = {p.identifier: p for p in paragraphs}
    ordered_ids = list(topological_paragraph_order(paragraphs).order)

    blocks: list[Block] = []
    counter = [0]

    def _split(ids: list[str], depth: int) -> None:
        if not ids:
            return
        if len(ids) <= max_paragraphs_per_block and _line_count(paragraphs_by_id, ids) <= max_lines_per_block:
            blocks.append(Block(index=counter[0], depth=depth, paragraph_ids=tuple(ids)))
            counter[0] += 1
            return
        if len(ids) == 1:
            # Cannot subdivide a single paragraph further -- emit it as
            # its own oversized block rather than raise.
            blocks.append(Block(index=counter[0], depth=depth, paragraph_ids=tuple(ids)))
            counter[0] += 1
            return
        mid = len(ids) // 2
        _split(ids[:mid], depth + 1)
        _split(ids[mid:], depth + 1)

    _split(ordered_ids, 0)
    return blocks


__all__ = [
    "Block", "TopologicalOrder", "paragraph_call_graph",
    "topological_paragraph_order", "segment_hierarchical",
]
