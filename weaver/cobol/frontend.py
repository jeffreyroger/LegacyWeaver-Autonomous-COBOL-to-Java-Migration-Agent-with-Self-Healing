"""COBOL program frontend — Steps U2, U3, U5.

`load_program()` reads a COBOL source plus its copybooks and returns a
`ProgramModel`: everything that used to be hand-declared per program.
`to_scaffold_spec()` converts that model into the `ScaffoldSpec` the
existing K2 generator already consumes unchanged.

Declared scope (Phase U, widened by Phases BB1/BB2/BB3). One or more input
files (read in lockstep by position when more than one -- see
`weaver/agent/scaffold.py`'s `ScaffoldSpec.extra_input_files` comment) and
one or more output files (every record written unconditionally to every
output file -- see `ScaffoldSpec.extra_output_files`/`ExtraOutputFile`;
conditional routing is out of scope); DISPLAY usage only; exactly one
01-level under every input FD and one-or-two under every output FD
(detail line, then optionally a totals line -- see Phase X7); one driving
paragraph followed by one or more unit paragraphs, each `PERFORM`ed by the
driver exactly once and called in sequence every record (see
`ScaffoldSpec.extra_paragraph_ids`). Everything outside that raises — a
frontend that guesses produces a plausible layout, and a plausible-but-
wrong layout invalidates every byte comparison downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from weaver.agent.scaffold import ConditionName, ExtraOutputFile, ScaffoldSpec, WorkingStorageField
from weaver.agent.segment import segment
from weaver.cobol import callgraph, procedure
from weaver.cobol.data_division import (
    DataItem,
    UnsupportedDataItemError,
    condition_names,
    elementary_items,
    flatten,
    parse_items,
)
from weaver.cobol.naming import java_field_name, java_method_name
from weaver.cobol.source import Statement, expand_copy, statements
from weaver.layout import Field

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
    # Phase BB1: additional input files beyond the primary one, read in
    # lockstep by position -- see ScaffoldSpec.extra_input_files' comment
    # for the exact (deliberately narrow) subshape this covers. Empty for
    # every program with exactly one input file, i.e. every fixture before
    # this phase, so input_file/input_layout above are unchanged for them.
    extra_input_files: tuple[str, ...]
    extra_input_layouts: tuple[tuple[Field, ...], ...]
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
    # Phase BB2: additional output files beyond the primary one, each
    # written unconditionally once per record -- see ExtraOutputFile's own
    # comment for the exact (deliberately narrow) subshape. Empty for
    # every program with exactly one output file, i.e. every fixture
    # before this phase.
    extra_output_files: tuple[ExtraOutputFile, ...]
    # Phase BB3: additional unit paragraphs beyond the primary one
    # (paragraph_id/paragraph_method), called in sequence every record --
    # see ScaffoldSpec.extra_paragraph_ids' comment. Empty for every
    # program with exactly one unit paragraph, i.e. every fixture before
    # this phase.
    extra_paragraph_ids: tuple[str, ...]
    extra_paragraph_methods: tuple[str, ...]


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
    token: str, target: Field, input_fields: dict[str, tuple[str, Field]], ws_names: set[str]
) -> str:
    """The Java expression a `MOVE <token> TO <target>` implies.

    Phase BB1: `input_fields` maps a field name to (accessor, Field) --
    accessor is "ar" for the primary input file's fields, "ar2"/"ar3"/...
    for an extra input file's fields (`extra_record_param_names` in
    scaffold.py), so a field from any input file resolves to the right
    Java object. Every caller before this phase built this dict with
    every value's accessor fixed at "ar" (one input file), so this is a
    pure widening, not a behavior change for them.
    """
    if procedure.is_literal(token):
        return f'Scaffold.pad("{procedure.literal_text(token)}", {target.width})'

    name = token.upper()
    if name in procedure.FIGURATIVE_SPACE:
        return '" "' if target.width == 1 else f'Scaffold.pad("", {target.width})'
    if name in procedure.FIGURATIVE_ZERO:
        return f"java.math.BigDecimal.ZERO.setScale({target.decimal_scale})"

    if name in input_fields:
        accessor, source_field = input_fields[name]
        jname = java_field_name(name)
        # A REDEFINES overlay is an accessor over the target's bytes, not a
        # stored component -- scaffold.py emits it as a method.
        return f"{accessor}.{jname}()" if source_field.redefines is not None else f"{accessor}.{jname}"
    if name in ws_names:
        return f"ws.{java_field_name(name)}"

    raise UnsupportedProgramError(
        f"MOVE {token} TO {target.name}: {name!r} is neither an input-record field "
        "nor a working-storage item"
    )


def _ctor_map(
    paragraph_text: str,
    layout: tuple[Field, ...],
    input_fields: dict[str, tuple[str, Field]],
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
    if len(units) < 1:
        raise UnsupportedProgramError(
            f"{cobol_source}: expected at least one synthesis unit after the driving "
            f"paragraph, found {len(units)}"
        )
    unit = units[0]
    if len(units) > 1:
        # Phase BB3: every extra unit beyond the primary one must be
        # PERFORMed directly by the driving paragraph exactly once (the
        # same "called once per record iteration" shape scaffold.py's
        # sequential paragraph_call generates) -- never a helper paragraph
        # performed conditionally, from another unit, or not at all.
        known_units = {u.identifier for u in units}
        performed = callgraph.performs(driver.source, known_units)
        perform_counts = {u.identifier: 0 for u in units}
        for edge in performed:
            perform_counts[edge.target] = perform_counts.get(edge.target, 0) + 1
        if any(count != 1 for count in perform_counts.values()):
            raise UnsupportedProgramError(
                f"{cobol_source}: with {len(units)} unit paragraphs, the driving "
                f"paragraph {driver.identifier!r} must PERFORM each exactly once "
                f"(no conditional/nested calls); found counts={perform_counts}"
            )

    all_paragraph_source = "\n".join(p.source for p in paragraphs)
    modes = procedure.open_modes(all_paragraph_source)
    input_files = [f for f, mode in modes.items() if mode == "INPUT"]
    output_files = [f for f, mode in modes.items() if mode == "OUTPUT"]
    if len(input_files) < 1 or len(output_files) < 1:
        raise UnsupportedProgramError(
            f"{cobol_source}: expected at least one input file and at least one "
            f"output file (found inputs={input_files}, outputs={output_files})"
        )

    # Phase BB1: input_files[0] (OPEN order) is the primary file (ar);
    # any further input files are read in lockstep by position (ar2, ar3,
    # ...). Every existing fixture has exactly one input file, so
    # extra_input_files below is always empty for them.
    for f in input_files:
        records = _records_for(part, f)
        if len(records) != 1:
            raise UnsupportedProgramError(
                f"input FD {f} must declare exactly one 01-level, found {len(records)}"
            )
    if len(input_files) > 1:
        # The driving paragraph must READ every opened input file exactly
        # once per iteration -- the same lockstep shape scaffold.py's
        # indexed loop generates. Anything else (a keyed lookup, a MERGE,
        # an unread file) is outside this phase's declared subshape.
        read_files = procedure.reads(driver.source)
        read_counts = {f: read_files.count(f) for f in input_files}
        if any(count != 1 for count in read_counts.values()) or set(read_files) != set(input_files):
            raise UnsupportedProgramError(
                f"{cobol_source}: with {len(input_files)} input files, the driving "
                f"paragraph {driver.identifier!r} must READ each exactly once per "
                f"iteration (lockstep-by-position only, no keyed match/merge); "
                f"found reads={read_files}"
            )

    input_records = _records_for(part, input_files[0])
    extra_input_files = tuple(part.assignments[f] for f in input_files[1:])
    extra_input_layouts = tuple(flatten(_records_for(part, f)[0]) for f in input_files[1:])

    # Phase X7 (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md): a totals line
    # is optional per output file -- one 01-level (detail line only) is
    # accepted in addition to the original two (detail line then totals
    # line). Phase BB2 widens this to apply to every output file, not
    # just the (now-primary) one -- every existing fixture has exactly one
    # output file and always declared two 01-levels, so it always takes
    # the exact code path it always took.
    for f in output_files:
        records = _records_for(part, f)
        if len(records) not in (1, 2):
            raise UnsupportedProgramError(
                f"output FD {f} must declare one 01-level (detail line only) "
                f"or two 01-levels (detail line then totals line), found {len(records)}"
            )

    output_records = _records_for(part, output_files[0])
    has_totals = len(output_records) == 2

    input_root = input_records[0]
    input_layout = flatten(input_root)
    report_layout = flatten(output_records[0])
    totals_layout = flatten(output_records[1]) if has_totals else ()

    ws_roots = parse_items(part.working_storage)
    ws_items = tuple(item for root in ws_roots for item in elementary_items(root))
    ws_names = tuple(item.name for item in ws_items)
    ws_fields = tuple(
        WorkingStorageField(java_field_name(item.name), item.picture.decimal_scale)
        for item in ws_items
        if item.picture is not None and item.picture.numeric
    )

    # Phase BB1: field name -> (accessor, Field), merging the primary
    # file's fields ("ar") with every extra file's fields ("ar2", "ar3",
    # ...). A field name shared by two input files (unusual, and out of
    # this phase's scope to resolve) resolves to whichever file's entry
    # is inserted last -- raising instead would need its own real fixture
    # to prove out, so this is disclosed as a known limitation rather than
    # guessed at silently in the other direction.
    input_fields: dict[str, tuple[str, Field]] = {f.name: ("ar", f) for f in input_layout}
    for i, extra_layout in enumerate(extra_input_layouts):
        accessor = f"ar{i + 2}"
        input_fields.update({f.name: (accessor, f) for f in extra_layout})
    ws_name_set = set(ws_names)
    # Phase BB3: which unit sets which field is derived by scanning every
    # unit paragraph's source combined, not just the first -- for the N=1
    # case (every fixture before this phase) this is exactly unit.source.
    units_combined_source = "\n".join(u.source for u in units)

    report_ctor_map = _ctor_map(units_combined_source, report_layout, input_fields, ws_name_set)
    if has_totals:
        totals_ctor_map = _ctor_map(driver.source, totals_layout, input_fields, ws_name_set)
        accumulator_field, per_record_field = _accumulator(
            units_combined_source, ws_name_set, totals_ctor_map
        )
    else:
        totals_ctor_map = {}
        accumulator_field, per_record_field = "", ""

    # Phase BB2: every output file beyond the primary one, each derived by
    # the exact same MOVE-based ctor-map/accumulator mechanism the primary
    # output file already uses -- see ExtraOutputFile's own comment for
    # why this stops short of conditional record routing.
    extra_output_files: list[ExtraOutputFile] = []
    for f in output_files[1:]:
        f_records = _records_for(part, f)
        f_has_totals = len(f_records) == 2
        f_report_layout = flatten(f_records[0])
        f_totals_layout = flatten(f_records[1]) if f_has_totals else ()
        f_report_ctor_map = _ctor_map(units_combined_source, f_report_layout, input_fields, ws_name_set)
        if f_has_totals:
            f_totals_ctor_map = _ctor_map(driver.source, f_totals_layout, input_fields, ws_name_set)
            f_accumulator_field, f_per_record_field = _accumulator(
                units_combined_source, ws_name_set, f_totals_ctor_map
            )
        else:
            f_totals_ctor_map = {}
            f_accumulator_field, f_per_record_field = "", ""
        extra_output_files.append(ExtraOutputFile(
            file_name=part.assignments[f],
            report_layout=f_report_layout,
            totals_layout=f_totals_layout,
            report_ctor_map=f_report_ctor_map,
            totals_ctor_map=f_totals_ctor_map,
            accumulator_field=f_accumulator_field,
            per_record_field=f_per_record_field,
        ))

    return ProgramModel(
        program_id=part.program_id,
        source_path=cobol_source,
        input_file=part.assignments[input_files[0]],
        output_file=part.assignments[output_files[0]],
        input_layout=input_layout,
        extra_input_files=extra_input_files,
        extra_input_layouts=extra_input_layouts,
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
        extra_output_files=tuple(extra_output_files),
        extra_paragraph_ids=tuple(u.identifier for u in units[1:]),
        extra_paragraph_methods=tuple(java_method_name(u.identifier) for u in units[1:]),
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
        extra_input_files=model.extra_input_files,
        extra_input_layouts=model.extra_input_layouts,
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
        extra_output_files=model.extra_output_files,
        extra_paragraph_ids=model.extra_paragraph_ids,
        extra_paragraph_methods=model.extra_paragraph_methods,
    )


__all__ = [
    "ProgramModel",
    "UnsupportedDataItemError",
    "UnsupportedProgramError",
    "load_program",
    "load_program_cached",
    "to_scaffold_spec",
]
