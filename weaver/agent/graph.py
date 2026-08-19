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
from weaver.cobol.callgraph import goto_targets
from weaver.cobol.callgraph import performs as extract_performs
from weaver.cobol.dataflow import ReadWriteSet, read_write_set
from weaver.cobol.reducibility import classify as classify_reducibility
from weaver.cobol.reducibility import rewrite as rewrite_goto


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
class GotoEdge:
    source: str
    target: str


@dataclass(frozen=True)
class ProgramGraph:
    program_id: str
    paragraphs: tuple[str, ...]
    performs: tuple[PerformEdge, ...] = field(default_factory=tuple)
    calls: tuple[CallEdge, ...] = field(default_factory=tuple)
    read_write_sets: dict[str, ReadWriteSet] = field(default_factory=dict)
    goto_edges: tuple[GotoEdge, ...] = field(default_factory=tuple)
    # paragraph_id -> "STRUCTURED" | "UNSTRUCTURED" | "UNSTRUCTURED_UNRESOLVED"
    # (FR-11.2/11.3, weaver/cobol/reducibility.py).
    reducibility: dict[str, str] = field(default_factory=dict)

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
        from weaver.agent._toposort import topological_order as _topo

        edges = [(e.source, e.target) for e in self.performs]
        return _topo(list(self.paragraphs), edges)

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
            "goto_edges": [{"source": e.source, "target": e.target} for e in self.goto_edges],
            "reducibility": dict(self.reducibility),
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
    goto_edges: list[GotoEdge] = []
    reducibility: dict[str, str] = {}

    by_id = {p.identifier: p for p in paragraphs}

    for p in paragraphs:
        for perform in extract_performs(p.source, known):
            performs.append(
                PerformEdge(source=p.identifier, target=perform.target,
                            kind=perform.kind, thru_target=perform.thru_target)
            )
        for call in extract_calls(p.source):
            calls.append(CallEdge(source=p.identifier, program=call.program))
        read_write_sets[p.identifier] = read_write_set(p.identifier, p.source)

        for target in goto_targets(p.source):
            goto_edges.append(GotoEdge(source=p.identifier, target=target))

        classification = classify_reducibility(p)
        if classification == "UNSTRUCTURED" and rewrite_goto(p, by_id) is None:
            classification = "UNSTRUCTURED_UNRESOLVED"
        reducibility[p.identifier] = classification

    return ProgramGraph(
        program_id=program_id,
        paragraphs=tuple(p.identifier for p in paragraphs),
        performs=tuple(performs),
        calls=tuple(calls),
        read_write_sets=read_write_sets,
        goto_edges=tuple(goto_edges),
        reducibility=reducibility,
    )
