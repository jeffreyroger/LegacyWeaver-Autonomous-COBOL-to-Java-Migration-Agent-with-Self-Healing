"""LINKAGE SECTION subprogram frontend — Phase X1
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md).

Parses the subprogram shape `fixtures/cobol/multiprog/leaf_a.cob`/
`leaf_b.cob` use, generalized in Phase X8 to any number of LINKAGE
parameters: one `PROGRAM-ID`, a `LINKAGE SECTION` with N >= 2 numeric
elementary items in `PROCEDURE DIVISION USING` order, and exactly one
paragraph. By this repo's disclosed convention (Phase X8, no COBOL syntax
marks input vs output direction), the last USING parameter is the output;
every other USING parameter is an input -- LEAF-A/LEAF-B's original
one-input/one-output shape is the N=2 special case and is unchanged by
this generalization.

Non-Negotiable Design Decision 1 (SUBPROGRAM_VERIFICATION_PLAN.md §2):
`weaver/cobol/frontend.py`'s existing, hardened, file-based contract is
never touched by this module — this is a new, parallel parser for a
different program shape, reusing `data_division.py`'s PIC-parsing and
`segment.py`'s paragraph-splitting machinery unchanged, exactly the way
`frontend.py` itself already does.

Anything outside the shape above (an FD, a FILE-CONTROL, fewer than two
LINKAGE items, a non-numeric item, more than one paragraph) raises
`UnsupportedSubprogramError` -- never guessed at (Non-Negotiable Design
Decision 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from weaver.agent.segment import segment
from weaver.cobol.data_division import UnsupportedDataItemError, flatten, parse_items
from weaver.cobol.source import Statement, statements
from weaver.layout import Field

_PROGRAM_ID_RE = re.compile(r"[A-Z0-9][A-Z0-9-]*")

_DIVISION_MARKERS = {
    "IDENTIFICATION DIVISION": "identification",
    "ENVIRONMENT DIVISION": "environment",
    "DATA DIVISION": "data",
    "PROCEDURE DIVISION": "procedure",
}
_SECTION_MARKERS = {
    "FILE SECTION": "file",
    "WORKING-STORAGE SECTION": "working-storage",
    "LINKAGE SECTION": "linkage",
    "INPUT-OUTPUT SECTION": "input-output",
    "FILE-CONTROL": "file-control",
}


class UnsupportedSubprogramError(ValueError):
    """A program shape outside Phase X1's declared scope."""


@dataclass(frozen=True)
class SubprogramModel:
    program_id: str
    source_path: Path
    input_params: tuple[Field, ...]
    output_params: tuple[Field, ...]
    paragraph_id: str
    paragraph_source: str

    @property
    def input_param(self) -> Field:
        """Back-compat accessor for the N=2 (one input, one output) shape
        LEAF-A/LEAF-B and pre-Phase-X8 callers use."""
        if len(self.input_params) != 1:
            raise ValueError(
                f"{self.program_id} has {len(self.input_params)} input params; "
                "use input_params, not the singular input_param accessor"
            )
        return self.input_params[0]

    @property
    def output_param(self) -> Field:
        if len(self.output_params) != 1:
            raise ValueError(
                f"{self.program_id} has {len(self.output_params)} output params; "
                "use output_params, not the singular output_param accessor"
            )
        return self.output_params[0]


def _using_params(stmt_text: str) -> list[str]:
    """`PROCEDURE DIVISION USING LA-INPUT LA-OUTPUT` -> ["LA-INPUT", "LA-OUTPUT"]."""
    upper_tokens = stmt_text.upper().split()
    if "USING" not in upper_tokens:
        raise UnsupportedSubprogramError(
            f"PROCEDURE DIVISION with no USING clause is not a subprogram: {stmt_text!r}"
        )
    tokens = stmt_text.split()
    using_idx = [t.upper() for t in tokens].index("USING")
    params = tokens[using_idx + 1 :]
    if len(params) < 2:
        raise UnsupportedSubprogramError(
            f"a subprogram needs at least one input and one output USING "
            f"parameter; found {len(params)} ({params}): {stmt_text!r}"
        )
    return [p.upper() for p in params]


def load_subprogram(cobol_source: Path) -> SubprogramModel:
    """Parse a LINKAGE-SECTION-only subprogram into the narrow model
    Phase X1 declares (see module docstring)."""
    cobol_source = Path(cobol_source)
    text = cobol_source.read_text(encoding="utf-8")

    program_id = ""
    division = section = None
    linkage_stmts: list[Statement] = []
    using_params: list[str] | None = None

    for stmt in statements(text):
        upper = stmt.text.upper()

        if upper in _DIVISION_MARKERS:
            division, section = _DIVISION_MARKERS[upper], None
            continue
        if upper in _SECTION_MARKERS:
            section = _SECTION_MARKERS[upper]
            if section in ("file", "file-control"):
                raise UnsupportedSubprogramError(
                    f"{cobol_source}: a subprogram has no file I/O, but found {upper!r}"
                )
            continue
        if upper.startswith("PROGRAM-ID"):
            program_id = stmt.text[len("PROGRAM-ID") :].lstrip(". ").strip().upper()
            continue
        if upper.startswith("PROCEDURE DIVISION"):
            using_params = _using_params(stmt.text)
            continue
        if upper.startswith("SELECT ") or upper.startswith("FD "):
            raise UnsupportedSubprogramError(
                f"{cobol_source}: a subprogram has no file I/O, but found {stmt.text!r}"
            )

        if division == "data" and section == "linkage" and stmt.text[:1].isdigit():
            linkage_stmts.append(stmt)

    if not program_id:
        raise UnsupportedSubprogramError(f"{cobol_source}: no PROGRAM-ID found")
    if not _PROGRAM_ID_RE.fullmatch(program_id):
        # Defence in depth: subprogram_verify.py (Phase X3) uses program_id
        # verbatim in generated filenames and shell commands (cobc -o
        # <program_id>.so, CALL "<program_id>" inside a generated driver).
        # A COBOL identifier is always [A-Z0-9-]+ -- anything else is
        # rejected here, at the source, rather than trusted downstream.
        raise UnsupportedSubprogramError(
            f"{cobol_source}: PROGRAM-ID {program_id!r} is not a valid COBOL identifier"
        )
    if using_params is None:
        raise UnsupportedSubprogramError(f"{cobol_source}: no PROCEDURE DIVISION found")

    try:
        linkage_roots = parse_items(linkage_stmts)
    except UnsupportedDataItemError as exc:
        raise UnsupportedSubprogramError(f"{cobol_source}: {exc}") from exc

    if len(linkage_roots) < 2:
        raise UnsupportedSubprogramError(
            f"{cobol_source}: a subprogram needs at least two LINKAGE SECTION "
            f"items (one input, one output), found {len(linkage_roots)} "
            f"({[r.name for r in linkage_roots]})"
        )

    fields_by_name: dict[str, Field] = {}
    for root in linkage_roots:
        if root.picture is None:
            raise UnsupportedSubprogramError(
                f"{cobol_source}: LINKAGE SECTION item {root.name} is a group, not an "
                "elementary numeric item -- outside Phase X1's scope"
            )
        flat = flatten(root)
        if len(flat) != 1 or not flat[0].numeric:
            raise UnsupportedSubprogramError(
                f"{cobol_source}: LINKAGE SECTION item {root.name} must be a single "
                "numeric elementary item"
            )
        fields_by_name[root.name.upper()] = flat[0]

    missing = [p for p in using_params if p not in fields_by_name]
    if missing:
        raise UnsupportedSubprogramError(
            f"{cobol_source}: PROCEDURE DIVISION USING names {missing} not declared "
            f"in LINKAGE SECTION ({list(fields_by_name)})"
        )
    # Disclosed convention (Phase X8): the last USING parameter is the
    # output, every other USING parameter is an input -- COBOL's own
    # syntax carries no input/output direction marker.
    input_params = tuple(fields_by_name[p] for p in using_params[:-1])
    output_params = (fields_by_name[using_params[-1]],)

    paragraphs = segment(text)
    if len(paragraphs) != 1:
        raise UnsupportedSubprogramError(
            f"{cobol_source}: Phase X1 models exactly one paragraph, found "
            f"{len(paragraphs)} ({[p.identifier for p in paragraphs]})"
        )
    unit = paragraphs[0]

    return SubprogramModel(
        program_id=program_id,
        source_path=cobol_source,
        input_params=input_params,
        output_params=output_params,
        paragraph_id=unit.identifier,
        paragraph_source=unit.source,
    )


__all__ = ["SubprogramModel", "UnsupportedSubprogramError", "load_subprogram"]
