"""Renders a witness_search.py witness (`{field_name: Decimal}`) back into
a fixed-width input-record line for any `weaver.layout.Field` layout --
Phase X8's full-program adapter (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md,
migration-framework-spec.md Section 5.2 Step 2).

Generic over whatever `Field` tuple a caller supplies (any program's
`ScaffoldSpec.input_layout`, not one hardcoded fixture). Reuses each
`Field`'s own offset/width/decimal_scale/signed/trailing_separate_sign
attributes -- the same PIC-derived metadata `weaver/layout.py` already
declares -- rather than reimplementing PIC packing.

Scope note (disclosed): only numeric fields are driven by witness values;
non-numeric fields (ids, type codes, flags) are filled with a fixed
placeholder (spaces, or 'A' for alphabetic-looking fields) since
witness-search's domain algorithms operate over numeric PIC clauses only
(Section 1). A record built this way is valid, fixed-width, and accepted
by the real GnuCOBOL oracle -- it exercises the numeric fields' witness
values, not any non-numeric business-rule branch.
"""

from __future__ import annotations

from decimal import Decimal

from weaver.layout import Field, record_width


def _encode_numeric(field: Field, value: Decimal) -> str:
    scaled = int((abs(value) * (10 ** field.decimal_scale)).to_integral_exact())
    digits = f"{scaled:0{field.width - (1 if field.trailing_separate_sign else 0)}d}"
    if field.trailing_separate_sign:
        sign = "-" if value < 0 else "+"
        return digits + sign
    return digits


def render_record(layout: tuple[Field, ...], witness: dict[str, Decimal]) -> str:
    """Builds one fixed-width record string of length `record_width(layout)`.
    `witness` maps numeric field names to their witness `Decimal` value;
    any numeric field not present in `witness` is filled with zero."""
    width = record_width(layout)
    buf = [" "] * width
    for field in layout:
        if field.redefines is not None:
            continue
        if field.numeric:
            value = witness.get(field.name, Decimal(0))
            text = _encode_numeric(field, value)
        else:
            text = "A" * field.width
        text = text[: field.width].ljust(field.width) if not field.numeric else text.rjust(field.width, "0")
        buf[field.offset : field.offset + field.width] = list(text)
    line = "".join(buf)
    assert len(line) == width, f"record width {len(line)} != {width}"
    return line


__all__ = ["render_record"]
