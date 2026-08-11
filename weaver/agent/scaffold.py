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


def java_signature(spec: ScaffoldSpec) -> str:
    return f"static void {spec.paragraph_method}(AccountRecord ar, WorkingStorage ws)"


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


def _account_record_class(spec: ScaffoldSpec) -> str:
    input_layout = spec.input_layout
    fields = _base_fields(input_layout)
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
        if f.numeric:
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
    static void {spec.paragraph_method}(AccountRecord ar, WorkingStorage ws) {{
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

    totals_fields = _base_fields(spec.totals_layout)
    totals_ctor_args = []
    for f in totals_fields:
        if f.name not in spec.totals_ctor_map:
            raise NotImplementedError(f"no main-loop mapping declared for {f.name}")
        totals_ctor_args.append(spec.totals_ctor_map[f.name])
    totals_ctor = ", ".join(totals_ctor_args)

    return f"""\
public class Scaffold {{
    private static final String INPUT_FILE = "{spec.input_file}";
    private static final String OUTPUT_FILE = "{spec.output_file}";
    private static final int RECORD_WIDTH = {input_width};

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

        StringBuilder out = new StringBuilder();
        WorkingStorage ws = new WorkingStorage();

        for (String rawLine : lines) {{
            if (rawLine.isEmpty()) {{
                continue;
            }}
            String line = String.format("%-" + RECORD_WIDTH + "s", rawLine);
            AccountRecord ar = AccountRecord.decode(line);
            {spec.paragraph_method}(ar, ws);
            ws.{spec.accumulator_field} = ws.{spec.accumulator_field}.add(ws.{spec.per_record_field});

            ReportLine rl = new ReportLine({report_ctor});
            // GnuCOBOL LINE SEQUENTIAL strips trailing spaces on WRITE.
            out.append(rstripSpaces(rl.encode())).append("\\n");
        }}

        TotalsLine tl = new TotalsLine({totals_ctor});
        out.append(rstripSpaces(tl.encode())).append("\\n");

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
        _line_class("ReportLine", spec.report_layout),
        "\n",
        _line_class("TotalsLine", spec.totals_layout),
        "\n",
        _working_storage_class(spec),
        "\n",
        _main_class(spec),
    ]
    return "".join(parts)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("generated/Scaffold.java")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate(), encoding="utf-8")
    print(f"wrote {out_path}")
