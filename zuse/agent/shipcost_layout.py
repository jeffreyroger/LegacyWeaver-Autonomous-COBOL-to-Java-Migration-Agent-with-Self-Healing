"""Declared field layouts for SHIPCOST — Step U4's compound-condition
lookup program.

Mirrors the other Phase-U fixture layout modules' shape/rationale (own
module per NFR-14, not a second MVP oracle). Offsets/widths confirmed
against a real GnuCOBOL 3.2.0 run via WSL against
zuse/examples/input/data/shipcost.dat, producing
zuse/examples/input/data/expected/golden_shipcost.out (detail line 34 bytes,
totals line 41 bytes after GnuCOBOL's trailing-space strip).

TL-TOTAL started life as PIC -(5)9.99 (width 9, 6-digit capacity) and was
widened to -(7)9.99 (width 11, 8-digit capacity) after the first real
GnuCOBOL run printed "TOTAL COST: 77410.97" instead of "377410.97" --
the accumulated total across 15 records exceeded the original picture's
digit capacity and GnuCOBOL silently dropped the leading digit. This is
the exact edit-mask-too-narrow trap CLAUDE.md rule 6 documents for
interest.cob's original -(8)9.99 balance/interest fields; caught here by
the same discipline (never trust a golden file that wasn't visually
checked against the input before being frozen).
"""

from __future__ import annotations

from zuse.layout import Field, record_width  # reuse the same Field dataclass

INPUT_LAYOUT: tuple[Field, ...] = (
    Field("SR-ID", offset=0, width=16, numeric=False),
    Field("SR-WEIGHT", offset=16, width=7, numeric=True, decimal_scale=2, signed=False),
    Field("SR-ZONE", offset=23, width=1, numeric=False),
    Field("SR-FILLER", offset=24, width=6, numeric=False),
)

REPORT_LAYOUT: tuple[Field, ...] = (
    Field("EL-ID", offset=0, width=16, numeric=False),
    Field("EL-WEIGHT", offset=16, width=9, numeric=True, decimal_scale=2, signed=True),
    Field("EL-COST", offset=25, width=9, numeric=True, decimal_scale=2, signed=True),
)

TOTALS_LAYOUT: tuple[Field, ...] = (
    Field("TL-LABEL", offset=0, width=30, numeric=False),
    Field("TL-TOTAL", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
    Field("TL-FILLER", offset=41, width=1, numeric=False),
)

__all__ = ["Field", "INPUT_LAYOUT", "REPORT_LAYOUT", "TOTALS_LAYOUT", "record_width"]
