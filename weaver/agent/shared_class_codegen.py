"""Standalone Java class emitter for a `weaver.agent.class_designer`
`SharedLayout` -- Phase AA2 (migration-framework-spec.md Section 3.2).

Deliberately does NOT call `weaver/agent/scaffold.py`'s `_account_record_class`/
`_line_class` (those emit `Scaffold.decodeUnsigned(...)`/`Scaffold.pad(...)`
calls -- fine for a class nested inside one program's own `Scaffold.java`,
wrong for a class meant to be compiled once and referenced by several
independently-generated programs). This module mirrors the same decode/
encode logic those functions use, inlined against a small local
`CobolDecode` helper instead, so the emitted class has zero dependency on
any particular program's scaffold and is genuinely shareable.
"""

from __future__ import annotations

from weaver.agent.cobol_edit import JAVA_SOURCE as COBOL_EDIT_JAVA
from weaver.layout import Field

_DECODE_HELPER = """\
final class CobolDecode {
    private CobolDecode() {}

    static java.math.BigDecimal unsigned(String digits, int scale) {
        return new java.math.BigDecimal(new java.math.BigInteger(digits)).movePointLeft(scale);
    }

    static java.math.BigDecimal signedTrailing(String digits, char sign, int scale) {
        java.math.BigDecimal value = new java.math.BigDecimal(new java.math.BigInteger(digits)).movePointLeft(scale);
        return sign == '-' ? value.negate() : value;
    }
}
"""


def _java_field_name(cobol_name: str) -> str:
    parts = cobol_name.split("-")[1:] or cobol_name.split("-")
    head, *rest = parts
    return head.lower() + "".join(p.capitalize() for p in rest)


def _base_fields(layout: tuple[Field, ...]) -> list[Field]:
    return [f for f in layout if f.redefines is None]


def _decode_expr(field: Field) -> str:
    start, end = field.offset, field.offset + field.width
    if not field.numeric:
        return f"line.substring({start}, {end})"
    if field.signed and field.trailing_separate_sign:
        digit_end = end - 1
        return (
            f"CobolDecode.signedTrailing(line.substring({start}, {digit_end}), "
            f"line.charAt({digit_end}), {field.decimal_scale})"
        )
    if not field.signed:
        return f"CobolDecode.unsigned(line.substring({start}, {end}), {field.decimal_scale})"
    raise NotImplementedError(
        f"field {field.name}: signed numeric encoding other than trailing-separate "
        "is not covered by this shared-class generator"
    )


def _encode_expr(field: Field) -> str:
    jname = _java_field_name(field.name)
    if not field.numeric:
        return f'pad({jname}, {field.width})'
    if field.edit_style == "zero_padded":
        return f"CobolEdit.zeroPadded({jname}, {field.width})"
    return f"CobolEdit.floatingSign({jname}, {field.width}, {field.decimal_scale})"


def generate_shared_helpers() -> str:
    """`CobolDecode` + the existing, unmodified `CobolEdit` shared helper
    (`weaver/agent/cobol_edit.py`, already used by every per-program
    scaffold -- reused here verbatim, not re-derived), as ONE file meant
    to be emitted exactly once per output directory. `generate_shared_record_class`
    references these classes by name rather than re-declaring them in
    every record class's own file -- inlining them per-class (an earlier
    version of this module did) works when exactly one shared class is
    compiled in isolation, but breaks with a real `javac: duplicate class:
    CobolEdit` the moment two or more shared classes are compiled
    together, which is the realistic case (a real migration wants every
    discovered shared class available at once). Found and fixed during
    the 2026-08-20 spec-compliance validation pass, before it ever shipped
    as a silent multi-file bug.
    """
    return f"{_DECODE_HELPER}\n{COBOL_EDIT_JAVA}"


def generate_shared_record_class(class_name: str, layout: tuple[Field, ...], layout_kind: str = "input_layout") -> str:
    """The record class alone (fields, constructor, and -- depending on
    `layout_kind` -- `decode(String)` and/or `encode()`) -- references
    `CobolDecode`/`CobolEdit` by name; callers must also emit
    `generate_shared_helpers()`'s output exactly once alongside any
    number of record classes from this function (never once per class).

    `layout_kind` mirrors `weaver/agent/scaffold.py`'s own asymmetry
    exactly: an `"input_layout"` record is only ever DECODED from a raw
    line in this harness (`AccountRecord.decode`, never an `encode()`);
    a `"report_layout"`/`"totals_layout"` record is only ever ENCODED to
    a raw line (`ReportLine`/`TotalsLine.encode()`, never a `decode()`).
    Emitting both unconditionally is wrong, not just redundant: a
    report/totals field is commonly `signed=True` with a floating-sign
    edit style, a shape `_decode_expr` (mirroring `scaffold.py`'s own
    `_decode_field_expr`, which has the identical narrow scope) does not
    support -- and should not need to, since nothing in this harness ever
    decodes a report line.
    """
    if layout_kind not in ("input_layout", "report_layout", "totals_layout"):
        raise ValueError(f"unknown layout_kind: {layout_kind!r}")
    wants_decode = layout_kind == "input_layout"
    wants_encode = layout_kind in ("report_layout", "totals_layout")

    fields = _base_fields(layout)
    components = [f"    final {'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)};" for f in fields]
    ctor_params = ", ".join(
        f"{'java.math.BigDecimal' if f.numeric else 'String'} {_java_field_name(f.name)}" for f in fields
    )
    ctor_assigns = "\n".join(f"        this.{_java_field_name(f.name)} = {_java_field_name(f.name)};" for f in fields)

    decode_method = ""
    if wants_decode:
        decode_args = ",\n".join(f"                {_decode_expr(f)}" for f in fields)
        decode_method = f"""
    static {class_name} decode(String line) {{
        return new {class_name}(
{decode_args}
        );
    }}
"""

    encode_method = ""
    if wants_encode:
        encode_expr = " + ".join(_encode_expr(f) for f in fields)
        encode_method = f"""
    String encode() {{
        return {encode_expr};
    }}

    private static String pad(String s, int width) {{
        return String.format("%-" + width + "s", s);
    }}
"""

    return f"""\
final class {class_name} {{
{chr(10).join(components)}

    {class_name}({ctor_params}) {{
{ctor_assigns}
    }}
{decode_method}{encode_method}}}
"""


__all__ = ["generate_shared_helpers", "generate_shared_record_class"]
