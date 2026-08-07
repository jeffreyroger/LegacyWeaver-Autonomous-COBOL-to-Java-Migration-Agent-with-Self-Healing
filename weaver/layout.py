"""Declared field layouts (SRS §5.1, §5.2; NFR-14).

Layouts are data, not code, so a second fixture requires no change to
comparison.py or classification.py. Two distinct tables are declared:

    INPUT_LAYOUT  -- how to slice an input record (Step B1)
    REPORT_LAYOUT -- how to slice an oracle/candidate output line (Step D3)

TODO(Dev A / Step B1): fill in INPUT_LAYOUT from the copybook, on paper first.
TODO(Dev C / Step D3): fill in REPORT_LAYOUT from the detail-line declaration
    in the COBOL source.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """One field in a declared layout.

    offset and width are in bytes. `redefines` names the field this one
    overlays, if any (SRS §5.1 REDEFINES rule: same offset, no extra width).
    """

    name: str
    offset: int
    width: int
    numeric: bool = False
    decimal_scale: int = 0
    signed: bool = False
    trailing_separate_sign: bool = False
    redefines: str | None = None


# TODO: populate per Step B1. Total record length must be 39 bytes.
INPUT_LAYOUT: tuple[Field, ...] = ()

# TODO: populate per Step D3, derived from the report line declaration.
REPORT_LAYOUT: tuple[Field, ...] = ()


def record_width(layout: tuple[Field, ...]) -> int:
    """Sum of non-REDEFINES field widths -- the declared record length."""
    return sum(f.width for f in layout if f.redefines is None)
