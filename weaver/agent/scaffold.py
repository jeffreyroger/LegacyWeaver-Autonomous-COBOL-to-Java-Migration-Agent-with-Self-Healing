"""Deterministic Java scaffold generator — Step K2 (generalized for S1).

Generates everything except paragraph bodies, from a `ScaffoldSpec`'s field
tables alone (never from COBOL source text — see AGENT_LAYER_PLAN.md K2).
Two identical specs must produce byte-identical scaffold output: anything
iterated here is iterated in the fixed order the tables declare (tuples),
so there is nothing to sort and nothing non-deterministic.

Originally written INTEREST-specific; generalized in Step S1 so a second
program (FEECALC) reuses this generator instead of a hand-copied variant --
`INTEREST_SPEC` below reproduces the original behaviour exactly (K2's
byte-identical-output acceptance test still holds for it unchanged).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from weaver.agent.cobol_edit import JAVA_SOURCE as COBOL_EDIT_JAVA
from weaver.layout import Field, INPUT_LAYOUT, REPORT_LAYOUT, TOTALS_LAYOUT, record_width


@dataclass(frozen=True)
class ConditionName:
    java_name: str          # e.g. "isPremium"
    parent_field: str       # e.g. "AR-TYPE"
    true_value: str         # e.g. "P"


@dataclass(frozen=True)
class WorkingStorageField:
    java_name: str   # e.g. "appliedRate"
    scale: int        # e.g. 5


@dataclass(frozen=True)
class ScaffoldSpec:
    input_file: str
    output_file: str
    input_layout: tuple[Field, ...]
    report_layout: tuple[Field, ...]
    totals_layout: tuple[Field, ...]
    condition_names: tuple[ConditionName, ...]
    paragraph_id: str
    paragraph_method: str
    ws_fields: tuple[WorkingStorageField, ...]
    accumulator_field: str          # java name of the running total, e.g. "totalInterest"
    per_record_field: str           # java name added to the accumulator each record, e.g. "interest"
    report_ctor_map: dict[str, str]  # REPORT_LAYOUT field name -> java expression
    totals_ctor_map: dict[str, str]  # TOTALS_LAYOUT field name -> java expression
    # Task 5 (FR-12.1-12.3): opt-in switch for generating input_layout's
    # REDEFINES overlays as Java subclasses over a shared byte[] buffer
    # instead of the pre-existing flattened substring-accessor style (see
    # `_redefines_subclasses`). Defaults to False so every ScaffoldSpec
    # declared before this task -- INCLUDING INTEREST_SPEC below, whose
    # INPUT_LAYOUT already has two `redefines` fields (AR-DORMANT/AR-HOLD
    # redefining AR-FLAGS) consumed elsewhere as `ar.dormant()` string
    # accessors (report_ctor_map, condition_names, _main_class) -- keeps
    # taking the exact code path it always has. Flipping this to True is a
    # deliberate per-spec choice, never an automatic consequence of a field
    # merely having `redefines` set, because INTEREST_SPEC already proves
    # that assumption is false for a real, currently-shipping fixture.
    redefines_as_subclasses: bool = False
    # Phase BB1 (docs/specs/... frontend generalization, migration-framework-spec.md):
    # additional input files beyond the primary one, read in lockstep by
    # position (record i of file 2 pairs with record i of the primary file
    # -- no key-matching/merge logic, a disclosed narrower subshape than a
    # full COBOL MATCH-MERGE). Empty by default -- every ScaffoldSpec
    # declared before this phase (including INTEREST_SPEC) has exactly one
    # input file and takes the exact code path it always has.
    # `extra_input_files[i]` pairs with `extra_input_layouts[i]`.
    extra_input_files: tuple[str, ...] = ()
    extra_input_layouts: tuple[tuple[Field, ...], ...] = ()


# Declared from the 88-levels in fixtures/cobol/copybooks/ACCOUNT-REC.cpy.
INTEREST_CONDITION_NAMES: tuple[ConditionName, ...] = (
    ConditionName("isPremium", "AR-TYPE", "P"),
    ConditionName("isDormant", "AR-DORMANT", "Y"),
    ConditionName("isHold", "AR-HOLD", "Y"),
)

# Backward-compatible alias used by other Phase-2 modules written before S1.
CONDITION_NAMES = INTEREST_CONDITION_NAMES
PARAGRAPH_ID = "PROCESS-RECORD"

INTEREST_SPEC = ScaffoldSpec(
    input_file="accounts.dat",
    output_file="interest.out",
    input_layout=INPUT_LAYOUT,
    report_layout=REPORT_LAYOUT,
    totals_layout=TOTALS_LAYOUT,
    condition_names=INTEREST_CONDITION_NAMES,
    paragraph_id="PROCESS-RECORD",
    paragraph_method="processRecord",
    ws_fields=(
        WorkingStorageField("appliedRate", 5),
        WorkingStorageField("interest", 2),
        WorkingStorageField("totalInterest", 2),
    ),
    accumulator_field="totalInterest",
    per_record_field="interest",
    report_ctor_map={
        "RL-ID": "ar.id", "RL-TYPE": "ar.type", "RL-BALANCE": "ar.balance",
        "RL-INTEREST": "ws.interest", "RL-DORMANT": "ar.dormant()",
    },
    totals_ctor_map={
        "TL-LABEL": 'Scaffold.pad("TOTAL INTEREST:", 30)',
        "TL-TOTAL": "ws.totalInterest", "TL-FILLER": '" "',
    },
)


def ws_cobol_name(java_name: str) -> str:
    """Inverse of _java_field_name for WORKING-STORAGE items: "totalFee" ->
    "WS-TOTAL-FEE". Deterministic from the naming convention every
    ScaffoldSpec.ws_fields entry already follows (see K2/S1) -- there is no
    separate COBOL-name table to keep in sync."""
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)", java_name)
    return "WS-" + "-".join(p.upper() for p in parts)


def extra_record_class_names(spec: ScaffoldSpec) -> tuple[str, ...]:
    """Phase BB1: deterministic class names for `spec.extra_input_files`,
    in order -- "InputRecord2", "InputRecord3", ... (index-based, so two
    extra files can never collide on a derived name the way a
    field-prefix-derived name could)."""
    return tuple(f"InputRecord{i + 2}" for i in range(len(spec.extra_input_files)))


def extra_record_param_names(spec: ScaffoldSpec) -> tuple[str, ...]:
    return tuple(f"ar{i + 2}" for i in range(len(spec.extra_input_files)))


def java_signature(spec: ScaffoldSpec) -> str:
    extra_params = "".join(
        f", {cls} {param}" for cls, param in zip(extra_record_class_names(spec), extra_record_param_names(spec))
    )
    return f"static void {spec.paragraph_method}(AccountRecord ar{extra_params}, WorkingStorage ws)"


def ws_accessors(spec: ScaffoldSpec) -> dict[str, str]:
    """COBOL WORKING-STORAGE name -> Java accessor, for every ws_fields entry
    except the accumulator (scaffold-owned, see ws_scaffold_owned)."""
    return {
        ws_cobol_name(f.java_name): f"ws.{f.java_name}"
        for f in spec.ws_fields
        if f.java_name != spec.accumulator_field
    }


def ws_scaffold_owned(spec: ScaffoldSpec) -> set[str]:
    """WORKING-STORAGE names the generated main loop owns, never the
    synthesized paragraph body: the running-total accumulator and the EOF
    flag driving the PERFORM UNTIL loop."""
    return {ws_cobol_name(spec.accumulator_field), "WS-EOF-FLAG"}


def ws_field_names(spec: ScaffoldSpec) -> tuple[str, ...]:
    return tuple(ws_cobol_name(f.java_name) for f in spec.ws_fields) + ("WS-EOF-FLAG",)


def field_scale(spec: ScaffoldSpec, field_name: str, default: int = 2) -> int:
    """The declared decimal scale for a report/totals field name, looked up
    from the program's own ScaffoldSpec instead of a value hardcoded for
    interest.cob's fields (appliedRate/interest/totalInterest, which all
    happen to be scale 2 or 5) -- see 2026-08-12 audit. `default` only
    applies if the name isn't found in either layout, which should not
    happen for a divergence's field_name in practice."""
    for f in (*spec.report_layout, *spec.totals_layout):
        if f.name == field_name and f.numeric:
            return f.decimal_scale
    return default


def _java_field_name(cobol_name: str) -> str:
    """AR-BALANCE -> balance, RL-INTEREST -> interest, TL-TOTAL -> total."""
    parts = cobol_name.split("-")[1:]
    if not parts:
        parts = cobol_name.split("-")
    head, *rest = parts
    return head.lower() + "".join(p.capitalize() for p in rest)


def _base_fields(layout: tuple[Field, ...]) -> list[Field]:
    return [f for f in layout if f.redefines is None]


def _decode_field_expr(field: Field) -> str:
    start, end = field.offset, field.offset + field.width
    if not field.numeric:
        return f'line.substring({start}, {end})'
    if field.signed and field.trailing_separate_sign:
        digit_end = end - 1
        return (
            f'Scaffold.decodeSignedTrailing(line.substring({start}, {digit_end}), '
            f'line.charAt({digit_end}), {field.decimal_scale})'
        )
    if not field.signed:
        return f'Scaffold.decodeUnsigned(line.substring({start}, {end}), {field.decimal_scale})'
    raise NotImplementedError(
        f"field {field.name}: signed numeric encoding other than trailing-separate "
        "is not covered by this fixture's scaffold generator"
    )


def _redefines_subclasses(input_layout: tuple[Field, ...]) -> str:
    """One Java subclass per REDEFINES overlay group (FR-12.1/12.2).

    Fields sharing the same `redefines` target are grouped into a single
    subclass -- COBOL REDEFINES lets several elementary items reuse one
    byte range, and one subclass is one alternate *view* over that range,
    not one field. Each subclass extends `AccountRecord`, inherits its
    shared `buffer` field (never duplicates it), and decodes its own
    fields from that buffer using the exact same `_decode_field_expr`
    arithmetic the base class uses for its own fields -- this changes only
    the class-shape wrapper, not the decode/encode logic itself.
    """
    base_super_args = ", ".join(
        ["base.buffer"] + [f"base.{_java_field_name(f.name)}" for f in _base_fields(input_layout)]
    )

    groups: dict[str, list[Field]] = {}
    for f in input_layout:
        if f.redefines is not None:
            groups.setdefault(f.redefines, []).append(f)

    subclasses = []
    for target_name in groups:
        fields = groups[target_name]
        overlay_name = _java_field_name(target_name)[0].upper() + _java_field_name(target_name)[1:] + "Overlay"

        components = [f"        final {'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)};" for f in fields]
        decodes = [f"            this.{_java_field_name(f.name)} = {_decode_field_expr(f)};" for f in fields]

        pack_stmts = []
        for f in fields:
            jname = _java_field_name(f.name)
            if f.numeric:
                pack_stmts.append(
                    f'            System.arraycopy(CobolEdit.zeroPadded({jname}, {f.width})'
                    f'.getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, b, {f.offset}, {f.width});'
                )
            else:
                pack_stmts.append(
                    f'            System.arraycopy(Scaffold.pad({jname}, {f.width})'
                    f'.getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, b, {f.offset}, {f.width});'
                )

        subclasses.append(f"""\
    static final class {overlay_name} extends AccountRecord {{
{chr(10).join(components)}

        {overlay_name}(AccountRecord base) {{
            super({base_super_args});
            String line = new String(base.buffer, java.nio.charset.StandardCharsets.US_ASCII);
{chr(10).join(decodes)}
        }}

        byte[] getBytes() {{
            return buffer;
        }}

        void setBytes(byte[] b) {{
{chr(10).join(pack_stmts)}
            System.arraycopy(b, 0, buffer, 0, b.length);
        }}
    }}
""")
    return "\n".join(subclasses)


def _account_record_class(spec: ScaffoldSpec) -> str:
    input_layout = spec.input_layout
    fields = _base_fields(input_layout)
    has_redefines = any(f.redefines is not None for f in input_layout)

    if not (spec.redefines_as_subclasses and has_redefines):
        # Unchanged from before Task 5 -- flattened substring accessors.
        components = []
        decodes = []
        for f in fields:
            jname = _java_field_name(f.name)
            jtype = "java.math.BigDecimal" if f.numeric else "String"
            components.append(f"    final {jtype} {jname};")
            decodes.append(f"                {_decode_field_expr(f)}")

        ctor_params = ", ".join(
            f"{'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)}"
            for f in fields
        )
        ctor_assigns = "\n".join(f"        this.{_java_field_name(f.name)} = {_java_field_name(f.name)};" for f in fields)
        decode_args = ",\n".join(decodes)

        # REDEFINES accessors, relative to their target's byte range.
        redefines_accessors = []
        targets = {f.name: f for f in input_layout}
        for f in input_layout:
            if f.redefines is None:
                continue
            target = targets[f.redefines]
            rel_start = f.offset - target.offset
            rel_end = rel_start + f.width
            method = _java_field_name(f.name)
            target_jname = _java_field_name(target.name)
            redefines_accessors.append(
                f"    String {method}() {{ return {target_jname}.substring({rel_start}, {rel_end}); }}"
            )

        condition_methods = []
        for c in spec.condition_names:
            parent = next((f for f in input_layout if f.name == c.parent_field), None)
            if parent is None:
                continue
            if parent.redefines is not None:
                accessor = f"{_java_field_name(parent.name)}()"
            else:
                accessor = _java_field_name(parent.name)
            condition_methods.append(
                f'    boolean {c.java_name}() {{ return {accessor}.equals("{c.true_value}"); }}'
            )

        return f"""\
final class AccountRecord {{
{chr(10).join(components)}

    AccountRecord({ctor_params}) {{
{ctor_assigns}
    }}

    static AccountRecord decode(String line) {{
        return new AccountRecord(
{decode_args}
        );
    }}

{chr(10).join(redefines_accessors)}

{chr(10).join(condition_methods)}
}}
"""

    # Task 5 (FR-12.1-12.3): REDEFINES overlays as subclasses over a shared
    # byte[] buffer, gated on spec.redefines_as_subclasses -- see the field
    # comment on ScaffoldSpec for why this isn't automatic.
    components = ["    final byte[] buffer;"]
    decodes = []
    for f in fields:
        jname = _java_field_name(f.name)
        jtype = "java.math.BigDecimal" if f.numeric else "String"
        components.append(f"    final {jtype} {jname};")
        decodes.append(f"                {_decode_field_expr(f)}")

    ctor_params = ", ".join(
        ["byte[] buffer"] + [
            f"{'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)}"
            for f in fields
        ]
    )
    ctor_assigns = "\n".join(
        ["        this.buffer = buffer;"]
        + [f"        this.{_java_field_name(f.name)} = {_java_field_name(f.name)};" for f in fields]
    )
    decode_args = ",\n".join(decodes)

    condition_methods = []
    for c in spec.condition_names:
        parent = next((f for f in input_layout if f.name == c.parent_field), None)
        if parent is None or parent.redefines is not None:
            # Overlay-owned condition names live on their subclass, not here.
            continue
        accessor = _java_field_name(parent.name)
        condition_methods.append(
            f'    boolean {c.java_name}() {{ return {accessor}.equals("{c.true_value}"); }}'
        )

    return f"""\
class AccountRecord {{
{chr(10).join(components)}

    AccountRecord({ctor_params}) {{
{ctor_assigns}
    }}

    static AccountRecord decode(String line) {{
        byte[] buffer = line.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        return new AccountRecord(
            buffer,
{decode_args}
        );
    }}

    byte[] getBytes() {{
        return buffer;
    }}

    void setBytes(byte[] b) {{
        System.arraycopy(b, 0, buffer, 0, b.length);
    }}

{chr(10).join(condition_methods)}
}}

{_redefines_subclasses(input_layout)}"""


def _extra_record_class(class_name: str, layout: tuple[Field, ...]) -> str:
    """Phase BB1: an additional input file's record class -- flattened
    substring accessors only (reuses `_decode_field_expr`/`_java_field_name`
    unchanged). Deliberately narrower than `_account_record_class`: no
    REDEFINES-as-subclasses, no condition-name accessors. A fixture whose
    extra input file needs either is outside this phase's declared scope
    (frontend.py raises rather than silently dropping the feature)."""
    fields = _base_fields(layout)
    components = []
    decodes = []
    for f in fields:
        jname = _java_field_name(f.name)
        jtype = "java.math.BigDecimal" if f.numeric else "String"
        components.append(f"    final {jtype} {jname};")
        decodes.append(f"                {_decode_field_expr(f)}")

    ctor_params = ", ".join(
        f"{'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)}" for f in fields
    )
    ctor_assigns = "\n".join(f"        this.{_java_field_name(f.name)} = {_java_field_name(f.name)};" for f in fields)
    decode_args = ",\n".join(decodes)

    return f"""\
final class {class_name} {{
{chr(10).join(components)}

    {class_name}({ctor_params}) {{
{ctor_assigns}
    }}

    static {class_name} decode(String line) {{
        return new {class_name}(
{decode_args}
        );
    }}
}}
"""


def _line_class(class_name: str, layout: tuple[Field, ...]) -> str:
    fields = _base_fields(layout)
    components = []
    for f in fields:
        jtype = "java.math.BigDecimal" if f.numeric else "String"
        components.append(f"    final {jtype} {_java_field_name(f.name)};")
    ctor_params = ", ".join(
        f"{'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)}"
        for f in fields
    )
    ctor_assigns = "\n".join(f"        this.{_java_field_name(f.name)} = {_java_field_name(f.name)};" for f in fields)

    encode_parts = []
    for f in fields:
        jname = _java_field_name(f.name)
        if f.numeric and f.edit_style == "zero_padded":
            encode_parts.append(f"CobolEdit.zeroPadded({jname}, {f.width})")
        elif f.numeric:
            encode_parts.append(f"CobolEdit.floatingSign({jname}, {f.width}, {f.decimal_scale})")
        else:
            encode_parts.append(f'Scaffold.pad({jname}, {f.width})')
    encode_expr = " + ".join(encode_parts)

    return f"""\
final class {class_name} {{
{chr(10).join(components)}

    {class_name}({ctor_params}) {{
{ctor_assigns}
    }}

    String encode() {{
        return {encode_expr};
    }}
}}
"""


def _working_storage_class(spec: ScaffoldSpec) -> str:
    decls = "\n".join(
        f"    java.math.BigDecimal {f.java_name} = java.math.BigDecimal.ZERO.setScale({f.scale});"
        for f in spec.ws_fields
    )
    return f"""\
final class WorkingStorage {{
{decls}
}}
"""


def _paragraph_stub(spec: ScaffoldSpec) -> str:
    return f"""\
    {java_signature(spec)} {{
        // PARAGRAPH:{spec.paragraph_id}:BEGIN
        throw new UnsupportedOperationException("{spec.paragraph_id} not yet synthesized");
        // PARAGRAPH:{spec.paragraph_id}:END
    }}
"""


def _main_class(spec: ScaffoldSpec) -> str:
    input_width = record_width(spec.input_layout)
    report_fields = _base_fields(spec.report_layout)
    report_ctor_args = []
    for f in report_fields:
        if f.name not in spec.report_ctor_map:
            raise NotImplementedError(f"no main-loop mapping declared for {f.name}")
        report_ctor_args.append(spec.report_ctor_map[f.name])
    report_ctor = ", ".join(report_ctor_args)

    # Phase X7 (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md): a totals line
    # is optional (frontend.py's has_totals branch). No existing fixture
    # has an empty totals_layout, so this is a new, additive branch --
    # every existing spec keeps generating the exact accumulator-update +
    # TotalsLine-write code it always did.
    has_totals = bool(spec.totals_layout)
    if has_totals:
        totals_fields = _base_fields(spec.totals_layout)
        totals_ctor_args = []
        for f in totals_fields:
            if f.name not in spec.totals_ctor_map:
                raise NotImplementedError(f"no main-loop mapping declared for {f.name}")
            totals_ctor_args.append(spec.totals_ctor_map[f.name])
        totals_ctor = ", ".join(totals_ctor_args)
        accumulator_line = (
            f"            ws.{spec.accumulator_field} = "
            f"ws.{spec.accumulator_field}.add(ws.{spec.per_record_field});\n"
        )
        totals_write_block = f"""
        TotalsLine tl = new TotalsLine({totals_ctor});
        out.append(rstripSpaces(tl.encode())).append("\\n");
"""
    else:
        accumulator_line = ""
        totals_write_block = ""

    # Phase BB1: N >= 1 input files read in lockstep by position (record i
    # of every extra file pairs with record i of the primary file -- see
    # ScaffoldSpec.extra_input_files' own comment for why this is a
    # deliberately narrower subshape than a full key-matching MERGE).
    # extra_class_names/extra_param_names are both empty when
    # extra_input_files is empty, so every branch below renders to exactly
    # what it always rendered to for a single-input-file spec.
    extra_class_names = extra_record_class_names(spec)
    extra_param_names = extra_record_param_names(spec)
    extra_widths = [record_width(layout) for layout in spec.extra_input_layouts]

    extra_consts = "".join(
        f'    private static final String INPUT_FILE{i + 2} = "{name}";\n'
        f"    private static final int RECORD_WIDTH{i + 2} = {width};\n"
        for i, (name, width) in enumerate(zip(spec.extra_input_files, extra_widths))
    )
    extra_reads = "".join(
        f"        java.util.List<String> lines{i + 2} = java.nio.file.Files.readAllLines(\n"
        f"            java.nio.file.Paths.get(INPUT_FILE{i + 2}), java.nio.charset.StandardCharsets.US_ASCII);\n"
        for i in range(len(spec.extra_input_files))
    )
    extra_length_checks = "".join(
        f'        if (lines{i + 2}.size() != lines.size()) {{\n'
        f'            throw new IllegalStateException("INPUT_FILE{i + 2} record count " '
        f'+ lines{i + 2}.size() + " != primary input record count " + lines.size());\n'
        f"        }}\n"
        for i in range(len(spec.extra_input_files))
    )
    extra_decodes = "".join(
        f'            String line{i + 2} = String.format("%-" + RECORD_WIDTH{i + 2} + "s", lines{i + 2}.get(recordIndex));\n'
        f"            {cls} {param} = {cls}.decode(line{i + 2});\n"
        for i, (cls, param) in enumerate(zip(extra_class_names, extra_param_names))
    )
    extra_call_args = "".join(f", {param}" for param in extra_param_names)
    has_extra_inputs = bool(spec.extra_input_files)

    # Two loop-header variants, not one conditionally-indexed loop, so a
    # single-input-file spec (every fixture before Phase BB1) renders the
    # EXACT foreach-loop text it always has -- tests/test_scaffold_redefines.py
    # asserts byte-identical generated Java against a frozen capture, and an
    # indexed-for-loop text change would break that even though the runtime
    # behavior is equivalent.
    if has_extra_inputs:
        loop_header = (
            "        for (int recordIndex = 0; recordIndex < lines.size(); recordIndex++) {\n"
            "            String rawLine = lines.get(recordIndex);\n"
        )
    else:
        loop_header = "        for (String rawLine : lines) {\n"
    paragraph_call = f"            {spec.paragraph_method}(ar{extra_call_args}, ws);"

    return f"""\
public class Scaffold {{
    private static final String INPUT_FILE = "{spec.input_file}";
    private static final String OUTPUT_FILE = "{spec.output_file}";
    private static final int RECORD_WIDTH = {input_width};
{extra_consts}
    static java.math.BigDecimal decodeUnsigned(String digits, int scale) {{
        java.math.BigDecimal unscaled = new java.math.BigDecimal(new java.math.BigInteger(digits));
        return unscaled.movePointLeft(scale);
    }}

    static java.math.BigDecimal decodeSignedTrailing(String digits, char sign, int scale) {{
        java.math.BigDecimal unscaled = new java.math.BigDecimal(new java.math.BigInteger(digits));
        java.math.BigDecimal value = unscaled.movePointLeft(scale);
        return sign == '-' ? value.negate() : value;
    }}

    static String pad(String s, int width) {{
        return String.format("%-" + width + "s", s);
    }}

    static String rstripSpaces(String s) {{
        int end = s.length();
        while (end > 0 && s.charAt(end - 1) == ' ') {{
            end--;
        }}
        return s.substring(0, end);
    }}

    public static void main(String[] args) throws java.io.IOException {{
        java.util.List<String> lines = java.nio.file.Files.readAllLines(
            java.nio.file.Paths.get(INPUT_FILE), java.nio.charset.StandardCharsets.US_ASCII);
{extra_reads}{extra_length_checks}
        StringBuilder out = new StringBuilder();
        WorkingStorage ws = new WorkingStorage();

{loop_header}            if (rawLine.isEmpty()) {{
                continue;
            }}
            String line = String.format("%-" + RECORD_WIDTH + "s", rawLine);
            AccountRecord ar = AccountRecord.decode(line);
{extra_decodes}{paragraph_call}
{accumulator_line}
            ReportLine rl = new ReportLine({report_ctor});
            // GnuCOBOL LINE SEQUENTIAL strips trailing spaces on WRITE.
            out.append(rstripSpaces(rl.encode())).append("\\n");
        }}
{totals_write_block}
        java.nio.file.Files.write(java.nio.file.Paths.get(OUTPUT_FILE),
            out.toString().getBytes(java.nio.charset.StandardCharsets.US_ASCII));
    }}

{_paragraph_stub(spec)}}}
"""


HEADER = """\
/*
 * Scaffold.java — GENERATED, do not hand-edit (Step K2).
 *
 * Produced deterministically by weaver/agent/scaffold.py from a
 * ScaffoldSpec's field tables. Everything here is control flow, decoding,
 * and encoding implied by the declared byte offsets and edit masks — no
 * paragraph business logic. The one paragraph body that requires
 * interpretation is a stub between substitution markers;
 * weaver/agent/assemble.py replaces it with a synthesized or hand-written
 * body without touching anything else in this file.
 */

"""


def generate(spec: ScaffoldSpec = INTEREST_SPEC) -> str:
    parts = [
        HEADER,
        COBOL_EDIT_JAVA,
        "\n",
        _account_record_class(spec),
        "\n",
    ]
    for cls_name, layout in zip(extra_record_class_names(spec), spec.extra_input_layouts):
        parts.append(_extra_record_class(cls_name, layout))
        parts.append("\n")
    parts.append(_line_class("ReportLine", spec.report_layout))
    parts.append("\n")
    # Phase X7: no existing fixture has an empty totals_layout, so this
    # unconditionally emits TotalsLine for every one of them, unchanged.
    # An empty totals_layout (ROOT.cob's totals-optional shape) has no
    # fields to encode -- _main_class already never references TotalsLine
    # in that case (its own has_totals branch), so the class itself is
    # skipped rather than emitting a broken zero-field encode().
    if spec.totals_layout:
        parts.append(_line_class("TotalsLine", spec.totals_layout))
        parts.append("\n")
    parts.append(_working_storage_class(spec))
    parts.append("\n")
    parts.append(_main_class(spec))
    return "".join(parts)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("generated/Scaffold.java")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate(), encoding="utf-8")
    print(f"wrote {out_path}")
