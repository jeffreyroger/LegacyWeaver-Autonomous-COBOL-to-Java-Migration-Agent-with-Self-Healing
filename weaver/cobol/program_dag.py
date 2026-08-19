"""Cross-program CALL DAG -- migration-framework-spec.md Section 5.1,
FR-13.1/13.2.

Extends weaver/cobol/callgraph.py's same-file literal CALL extraction to
same-directory cross-file resolution: a CALL "X" in one program resolves to
the sibling file whose PROGRAM-ID is X. Dynamic (CALL <identifier>) targets
stay unresolved -- same scope limit callgraph.py's calls() already applies
per GRAPH_PLAN.md's stated same-file, statically-known-only scope, now
extended to same-directory.

topological_order() reuses weaver/agent/_toposort.py's Kahn's-algorithm
implementation (extracted from ProgramGraph.topological_order(),
GRAPH_PLAN.md M3) rather than a second one, per the plan's explicit
instruction not to reimplement it or add a NetworkX dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from weaver.cobol.callgraph import calls as extract_calls

_PROGRAM_ID_RE = re.compile(r"\bPROGRAM-ID\.\s*([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)


@dataclass(frozen=True)
class ProgramCallEdge:
    caller: str
    callee: str


@dataclass(frozen=True)
class ProgramDAG:
    programs: list[str] = field(default_factory=list)
    edges: list[ProgramCallEdge] = field(default_factory=list)

    def topological_order(self) -> list[list[str]]:
        from weaver.agent._toposort import topological_order as _topo

        # A caller depends on its callee: the callee must appear first
        # (leaf-first). _toposort's edge convention is (source, target)
        # meaning source depends on target, so (caller, callee) matches
        # directly -- no reversal needed.
        edges = [(e.caller, e.callee) for e in self.edges]
        return _topo(self.programs, edges)


def from_directory(path: Path) -> ProgramDAG:
    program_id_by_file: dict[Path, str] = {}
    source_by_program: dict[str, str] = {}
    for cob_file in sorted(Path(path).glob("*.cob")):
        text = cob_file.read_text(encoding="utf-8")
        match = _PROGRAM_ID_RE.search(text)
        if match is None:
            continue
        name = match.group(1).upper()
        program_id_by_file[cob_file] = name
        source_by_program[name] = text

    edges: list[ProgramCallEdge] = []
    for cob_file, name in program_id_by_file.items():
        for call in extract_calls(source_by_program[name]):
            callee_name = call.program.upper()
            if callee_name in source_by_program:
                edges.append(ProgramCallEdge(caller=name, callee=callee_name))

    return ProgramDAG(programs=sorted(source_by_program.keys()), edges=edges)
