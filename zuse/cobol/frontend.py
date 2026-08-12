"""COBOL program frontend — Steps U2, U3, U5.

`load_program()` reads a COBOL source plus its copybooks and returns a
`ProgramModel`: everything that used to be hand-declared per program.
`to_scaffold_spec()` converts that model into the `ScaffoldSpec` the
existing K2 generator already consumes unchanged.

Declared scope (Phase U). One input file and one output file; DISPLAY usage
only; one 01-level under the input FD and exactly two under the output FD
(detail line, then totals line); one driving paragraph followed by exactly
one synthesis unit. Everything outside that raises — a frontend that guesses
produces a plausible layout, and a plausible-but-wrong layout invalidates
every byte comparison downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from zuse.agent.scaffold import ConditionName, ScaffoldSpec, WorkingStorageField
from zuse.agent.segment import segment
from zuse.cobol import procedure
from zuse.cobol.data_division import (
    DataItem,
    UnsupportedDataItemError,
    condition_names,
    elementary_items,
    flatten,
    parse_items,
)
from zuse.cobol.naming import java_field_name, java_method_name
from zuse.cobol.source import Statement, expand_copy, statements
from zuse.layout import Field

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


class UnsupportedProgramError(ValueError):
    """A program shape outside Phase U's declared scope."""


@dataclass(frozen=True)
class ProgramModel:
    program_id: str
    source_path: Path
    input_file: str
    output_file: str
    input_layout: tuple[Field, ...]
    report_layout: tuple[Field, ...]
    totals_layout: tuple[Field, ...]
    condition_names: tuple[ConditionName, ...]
    working_storage_names: tuple[str, ...]
    ws_fields: tuple[WorkingStorageField, ...]
    driver_paragraph: str
    paragraph_id: str
    paragraph_method: str
    report_ctor_map: dict[str, str]
    totals_ctor_map: dict[str, str]
    accumulator_field: str
    per_record_field: str


# --------------------------------------------------------------------------
# Statement partitioning
# --------------------------------------------------------------------------


@dataclass
class _Partition:
    program_id: str = ""
    assignments: dict[str, str] = None  # logical file name -> external name
    fd_records: dict[str, list[Statement]] = None
    working_storage: list[Statement] = None

    def __post_init__(self) -> None:
        self.assignments = {}
        self.fd_records = {}
        self.working_storage = []


def _partition(stmts: list[Statement]) -> _Partition:
    part = _Partition()
    division = section = None
    current_fd: str | None = None

    for stmt in stmts:
        upper = stmt.text.upper()

        if upper in _DIVISION_MARKERS:
            division, section, current_fd = _DIVISION_MARKERS[upper], None, None
            continue
        if upper in _SECTION_MARKERS:
            section, current_fd = _SECTION_MARKERS[upper], None
            continue
        if upper.startswith("PROGRAM-ID"):
            # Statements split on line-terminal periods, so `PROGRAM-ID. INTEREST.`
            # arrives whole -- the interior period is part of this statement.
            part.program_id = stmt.text[len("PROGRAM-ID") :].lstrip(". ").strip()
            continue

        if division == "environment" and upper.startswith("SELECT "):
            tokens = stmt.text.split()
            logical = tokens[1].upper()
            if "ASSIGN" not in [t.upper() for t in tokens]:
                raise UnsupportedProgramError(f"SELECT without ASSIGN: {stmt.text!r}")
            rest = tokens[[t.upper() for t in tokens].index("ASSIGN") + 1 :]
            if rest and rest[0].upper() == "TO":
                rest = rest[1:]
            if not rest:
                raise UnsupportedProgramError(f"ASSIGN with no target: {stmt.text!r}")
            part.assignments[logical] = rest[0].strip("\"'")
            continue

        if division == "data" and section == "file" and upper.startswith("FD "):
            current_fd = stmt.text.split()[1].upper()
            part.fd_records.setdefault(current_fd, [])
            continue

        if not stmt.text[:1].isdigit():
            continue
        if division == "data" and section == "file" and current_fd is not None:
            part.fd_records[current_fd].append(stmt)
        elif division == "data" and section == "working-storage":
            part.working_storage.append(stmt)

    return part


def _records_for(part: _Partition, fd_name: str) -> list[DataItem]:
    stmts = part.fd_records.get(fd_name)
    if stmts is None:
        raise UnsupportedProgramError(f"no FD found for file {fd_name!r}")
    return parse_items(stmts)


# --------------------------------------------------------------------------
# Main-loop wiring (U5)
# --------------------------------------------------------------------------


def _java_source_expr(
    token: str, target: Field, input_fields: dict[str, Field], ws_names: set[str]
) -> str:
    """The Java expression a `MOVE <token> TO <target>` implies."""
    if procedure.is_literal(token):
        return f'Scaffold.pad("{procedure.literal_text(token)}", {target.width})'

    name = token.upper()
    if name in procedure.FIGURATIVE_SPACE:
        return '" "' if target.width == 1 else f'Scaffold.pad("", {target.width})'
    if name in procedure.FIGURATIVE_ZERO:
        return f"java.math.BigDecimal.ZERO.setScale({target.decimal_scale})"

    if name in input_fields:
        source_field = input_fields[name]
        jname = java_field_name(name)
        # A REDEFINES overlay is an accessor over the target's bytes, not a
        # stored component -- scaffold.py emits it as a method.
        return f"ar.{jname}()" if source_field.redefines is not None else f"ar.{jname}"
    if name in ws_names:
        return f"ws.{java_field_name(name)}"

    raise UnsupportedProgramError(
        f"MOVE {token} TO {target.name}: {name!r} is neither an input-record field "
        "nor a working-storage item"
    )


def _ctor_map(
    paragraph_text: str,
    layout: tuple[Field, ...],
    input_fields: dict[str, Field],
    ws_names: set[str],
) -> dict[str, str]:
    by_name = {f.name: f for f in layout if f.redefines is None}
    out: dict[str, str] = {}
    for move in procedure.moves(paragraph_text):
        target = by_name.get(move.target)
        if target is None:
            continue
        out[target.name] = _java_source_expr(
            move.source, target, input_fields, ws_names
        )

    missing = [f.name for f in by_name.values() if f.name not in out]
    if missing:
        raise UnsupportedProgramError(
            f"no MOVE found for output field(s) {missing} -- the generated main loop "
            "would have nothing to write there"
        )
    # Emit in layout order so two runs over the same source agree byte for byte.
    return {f.name: out[f.name] for f in by_name.values()}


def _accumulator(
    paragraph_text: str, ws_names: set[str], totals_ctor_map: dict[str, str]
) -> tuple[str, str]:
    """(accumulator_field, per_record_field).

    The accumulator is identified by what the totals line reports, not by
    counting ADDs: a unit paragraph may legitimately contain several, and an
    inner-loop `ADD WS-STEP TO WS-ACCUM` is not the running total even though
    it is the first one encountered. Once the accumulator is known, the
    per-record item is the source of the ADD that targets it.
    """
    accumulators = [
        expr[len("ws.") :]
        for expr in totals_ctor_map.values()
        if expr.startswith("ws.")
    ]
    if len(accumulators) != 1:
        raise UnsupportedProgramError(
            f"the totals line must report exactly one working-storage accumulator, "
            f"found {accumulators}"
        )
    accumulator = accumulators[0]

    sources = [
        java_field_name(a.source)
        for a in procedure.adds(paragraph_text)
        if a.source in ws_names and java_field_name(a.target) == accumulator
    ]
    if len(sources) != 1:
        raise UnsupportedProgramError(
            f"expected exactly one `ADD <ws item> TO {accumulator}` in the unit "
            f"paragraph, found {len(sources)}"
        )
    return accumulator, sources[0]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def load_program(cobol_source: Path, copybook_dir: Path | None = None) -> ProgramModel:
    """Parse a COBOL program into the model the scaffold generator needs."""
    cobol_source = Path(cobol_source)
    text = cobol_source.read_text()
    if copybook_dir is None:
        copybook_dir = cobol_source.parent / "copybooks"

    part = _partition(statements(expand_copy(text, copybook_dir)))

    paragraphs = segment(text)
    if len(paragraphs) < 2:
        raise UnsupportedProgramError(
            f"{cobol_source}: expected a driving paragraph plus at least one unit, "
            f"found {len(paragraphs)}"
        )
    driver, units = paragraphs[0], paragraphs[1:]
    if len(units) != 1:
        raise UnsupportedProgramError(
            f"{cobol_source}: ScaffoldSpec holds a single synthesis unit; this program "
            f"has {len(units)} ({[u.identifier for u in units]})"
        )
    unit = units[0]

    modes = procedure.open_modes("\n".join(p.source for p in paragraphs))
    input_files = [f for f, mode in modes.items() if mode == "INPUT"]
    output_files = [f for f, mode in modes.items() if mode == "OUTPUT"]
    if len(input_files) != 1 or len(output_files) != 1:
        raise UnsupportedProgramError(
            f"{cobol_source}: Phase U models exactly one input and one output file "
            f"(found inputs={input_files}, outputs={output_files})"
        )

    input_records = _records_for(part, input_files[0])
    if len(input_records) != 1:
        raise UnsupportedProgramError(
            f"input FD {input_files[0]} must declare exactly one 01-level, "
            f"found {len(input_records)}"
        )
    output_records = _records_for(part, output_files[0])
    if len(output_records) != 2:
        raise UnsupportedProgramError(
            f"output FD {output_files[0]} must declare exactly two 01-levels "
            f"(detail line then totals line), found {len(output_records)}"
        )

    input_root = input_records[0]
    input_layout = flatten(input_root)
    report_layout = flatten(output_records[0])
    totals_layout = flatten(output_records[1])

    ws_roots = parse_items(part.working_storage)
    ws_items = tuple(item for root in ws_roots for item in elementary_items(root))
    ws_names = tuple(item.name for item in ws_items)
    ws_fields = tuple(
        WorkingStorageField(java_field_name(item.name), item.picture.decimal_scale)
        for item in ws_items
        if item.picture is not None and item.picture.numeric
    )

    input_fields = {f.name: f for f in input_layout}
    ws_name_set = set(ws_names)

    report_ctor_map = _ctor_map(unit.source, report_layout, input_fields, ws_name_set)
    totals_ctor_map = _ctor_map(driver.source, totals_layout, input_fields, ws_name_set)
    accumulator_field, per_record_field = _accumulator(
        unit.source, ws_name_set, totals_ctor_map
    )

    return ProgramModel(
        program_id=part.program_id,
        source_path=cobol_source,
        input_file=part.assignments[input_files[0]],
        output_file=part.assignments[output_files[0]],
        input_layout=input_layout,
        report_layout=report_layout,
        totals_layout=totals_layout,
        condition_names=condition_names(input_root),
        working_storage_names=ws_names,
        ws_fields=ws_fields,
        driver_paragraph=driver.identifier,
        paragraph_id=unit.identifier,
        paragraph_method=java_method_name(unit.identifier),
        report_ctor_map=report_ctor_map,
        totals_ctor_map=totals_ctor_map,
        accumulator_field=accumulator_field,
        per_record_field=per_record_field,
    )


@lru_cache(maxsize=8)
def load_program_cached(
    cobol_source: Path, copybook_dir: Path | None = None
) -> ProgramModel:
    """`load_program` memoised on its arguments.

    The repair loop verifies a unit many times per run and every call needs
    the same layouts; parsing is deterministic, so caching changes timing
    only. Keyed on both paths, so a caller that supplies a different
    copybook directory gets a different model rather than a stale one.
    """
    return load_program(cobol_source, copybook_dir)


def to_scaffold_spec(model: ProgramModel) -> ScaffoldSpec:
    """The `ScaffoldSpec` K2's generator consumes — now derived, not declared."""
    return ScaffoldSpec(
        input_file=model.input_file,
        output_file=model.output_file,
        input_layout=model.input_layout,
        report_layout=model.report_layout,
        totals_layout=model.totals_layout,
        condition_names=model.condition_names,
        paragraph_id=model.paragraph_id,
        paragraph_method=model.paragraph_method,
        ws_fields=model.ws_fields,
        accumulator_field=model.accumulator_field,
        per_record_field=model.per_record_field,
        report_ctor_map=model.report_ctor_map,
        totals_ctor_map=model.totals_ctor_map,
    )


__all__ = [
    "ProgramModel",
    "UnsupportedDataItemError",
    "UnsupportedProgramError",
    "load_program",
    "load_program_cached",
    "to_scaffold_spec",
]
