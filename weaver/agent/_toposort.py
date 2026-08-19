"""Shared Kahn's-algorithm leaf-first topological sort.

Extracted from ProgramGraph.topological_order() (GRAPH_PLAN.md M3) so
weaver/cobol/program_dag.py's cross-program DAG (FR-13.2) reuses the exact
same implementation rather than a second one, per the plan's explicit
instruction not to add a NetworkX dependency or reimplement Kahn's
algorithm a second time.
"""

from __future__ import annotations


def topological_order(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """Leaf-first order. Each edge (source, target) means source depends
    on target -- target must appear before source. A cycle has no leaf, so
    it is collapsed into one composite unit (all remaining un-orderable
    nodes) and flagged by its length > 1."""
    dependents: dict[str, set[str]] = {n: set() for n in nodes}
    for source, target in edges:
        dependents[source].add(target)

    remaining = set(nodes)
    order: list[list[str]] = []
    while remaining:
        leaves = sorted(n for n in remaining if not (dependents[n] & remaining))
        if not leaves:
            order.append(sorted(remaining))
            break
        for leaf in leaves:
            order.append([leaf])
        remaining -= set(leaves)
    return order
