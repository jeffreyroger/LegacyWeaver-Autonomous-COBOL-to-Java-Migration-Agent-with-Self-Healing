"""ProgramGraph — GRAPH_PLAN.md M3.

Fulfils SRS FR-2.1 (dependency graph), FR-2.2 (migration ordering), and
FR-2.3 (plan exposure). Assembles weaver.cobol.callgraph's (M1)
PERFORM/CALL edges and weaver.cobol.dataflow's (M2) read/write sets across
a whole program's paragraphs, attaching the paragraph identity neither of
those modules bakes in themselves.

Additive only (Non-Negotiable Design Decision 4, GRAPH_PLAN.md §1):
weaver/agent/scaffold.py continues to read only ScaffoldSpec. This module
answers a different question -- relationships and (later, M6) captured
runtime state -- never layout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from weaver.agent.segment import Paragraph
from weaver.cobol.callgraph import calls as extract_calls
from weaver.cobol.callgraph import performs as extract_performs
from weaver.cobol.dataflow import ReadWriteSet, read_write_set


@dataclass(frozen=True)
class PerformEdge:
    source: str
    target: str
    kind: str  # "SIMPLE" | "THRU"
    thru_target: str | None = None


@dataclass(frozen=True)
class CallEdge:
    source: str
    program: str


@dataclass(frozen=True)
class ProgramGraph:
    program_id: str
    paragraphs: tuple[str, ...]
    performs: tuple[PerformEdge, ...] = field(default_factory=tuple)
    calls: tuple[CallEdge, ...] = field(default_factory=tuple)
    read_write_sets: dict[str, ReadWriteSet] = field(default_factory=dict)

    def callees(self, paragraph_id: str) -> list[str]:
        return [e.target for e in self.performs if e.source == paragraph_id]

    def callers(self, paragraph_id: str) -> list[str]:
        return [e.source for e in self.performs if e.target == paragraph_id]

    def writers_of(self, field_name: str) -> list[str]:
        return sorted(
            pid for pid, rw in self.read_write_sets.items() if field_name in rw.writes
        )

    def readers_of(self, field_name: str) -> list[str]:
        return sorted(
            pid for pid, rw in self.read_write_sets.items() if field_name in rw.reads
        )

    def topological_order(self) -> list[list[str]]:
        """Leaf-first order (SRS FR-2.2). A paragraph that PERFORMs
        another depends on it: the callee must appear first. A PERFORM
        cycle has no leaf, so it is collapsed into one composite unit
        (all remaining un-orderable nodes) and flagged by its length > 1,
        per FR-2.2's explicit wording."""
        dependents: dict[str, set[str]] = {p: set() for p in self.paragraphs}
        for e in self.performs:
            dependents[e.source].add(e.target)  # source depends on target

        remaining = set(self.paragraphs)
        order: list[list[str]] = []
        while remaining:
            leaves = sorted(p for p in remaining if not (dependents[p] & remaining))
            if not leaves:
                # Every remaining node has an unresolved dependency inside
                # `remaining` itself -- a cycle. Collapse the rest as one
                # composite, flagged by having more than one member.
                order.append(sorted(remaining))
                break
            for leaf in leaves:
                order.append([leaf])
            remaining -= set(leaves)
        return order

    def to_dict(self) -> dict:
        return {
            "program_id": self.program_id,
            "paragraphs": list(self.paragraphs),
            "performs": [
                {"source": e.source, "target": e.target, "kind": e.kind, "thru_target": e.thru_target}
                for e in self.performs
            ],
            "calls": [{"source": e.source, "program": e.program} for e in self.calls],
            "read_write_sets": {
                pid: {"reads": sorted(rw.reads), "writes": sorted(rw.writes)}
                for pid, rw in self.read_write_sets.items()
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def from_paragraphs(program_id: str, paragraphs: list[Paragraph]) -> ProgramGraph:
    """Build the graph for a whole program from its already-segmented
    paragraphs (e.g. segment()'s output)."""
    known = {p.identifier for p in paragraphs}

    performs: list[PerformEdge] = []
    calls: list[CallEdge] = []
    read_write_sets: dict[str, ReadWriteSet] = {}

    for p in paragraphs:
        for perform in extract_performs(p.source, known):
            performs.append(
                PerformEdge(source=p.identifier, target=perform.target,
                            kind=perform.kind, thru_target=perform.thru_target)
            )
        for call in extract_calls(p.source):
            calls.append(CallEdge(source=p.identifier, program=call.program))
        read_write_sets[p.identifier] = read_write_set(p.identifier, p.source)

    return ProgramGraph(
        program_id=program_id,
        paragraphs=tuple(p.identifier for p in paragraphs),
        performs=tuple(performs),
        calls=tuple(calls),
        read_write_sets=read_write_sets,
    )
