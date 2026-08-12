"""Declared field layouts for COMPOUND — Step U3's pure-arithmetic program.

Mirrors the other Phase-U fixture layout modules' shape/rationale (own
module per NFR-14, not a second MVP oracle). Offsets/widths confirmed
against a real GnuCOBOL 3.2.0 run via WSL against
zuse/examples/input/data/compound.dat, producing
zuse/examples/input/data/expected/golden_compound.out (detail line 40 bytes,
totals line 41 bytes after GnuCOBOL's trailing-space strip).
"""

from __future__ import annotations

from zuse.layout import Field, record_width  # reuse the same Field dataclass

INPUT_LAYOUT: tuple[Field, ...] = (
    Field("CP-ID", offset=0, width=16, numeric=False),
    Field("CP-PRINCIPAL", offset=16, width=12, numeric=True, decimal_scale=2,
          signed=True, trailing_separate_sign=True),
    Field("CP-FILLER", offset=28, width=2, numeric=False),
)

REPORT_LAYOUT: tuple[Field, ...] = (
    Field("DL-ID", offset=0, width=16, numeric=False),
    Field("DL-PRINCIPAL", offset=16, width=13, numeric=True, decimal_scale=2, signed=True),
    Field("DL-RESULT", offset=29, width=11, numeric=True, decimal_scale=2, signed=True),
)

TOTALS_LAYOUT: tuple[Field, ...] = (
    Field("TL-LABEL", offset=0, width=30, numeric=False),
    Field("TL-TOTAL", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
    Field("TL-FILLER", offset=41, width=1, numeric=False),
)

__all__ = ["Field", "INPUT_LAYOUT", "REPORT_LAYOUT", "TOTALS_LAYOUT", "record_width"]
