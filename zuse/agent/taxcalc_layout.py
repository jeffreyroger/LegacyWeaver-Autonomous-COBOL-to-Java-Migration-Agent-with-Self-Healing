"""Declared field layouts for TAXCALC — Step U1's nested-conditional program.

Mirrors zuse.agent.feecalc_layout's shape/rationale: its own module
(NFR-14 scopes zuse.layout to the MVP harness's one oracle fixture),
not a second MVP oracle. Offsets/widths confirmed against a real
GnuCOBOL 3.2.0 run via WSL against zuse/examples/input/data/tax.dat,
producing zuse/examples/input/data/expected/golden_taxcalc.out (detail line
40 bytes, totals line 41 bytes after GnuCOBOL's trailing-space strip).
"""

from __future__ import annotations

from zuse.layout import Field, record_width  # reuse the same Field dataclass

INPUT_LAYOUT: tuple[Field, ...] = (
    Field("TR-ID", offset=0, width=16, numeric=False),
    Field("TR-INCOME", offset=16, width=12, numeric=True, decimal_scale=2,
          signed=True, trailing_separate_sign=True),
    Field("TR-BRACKET", offset=28, width=1, numeric=False),
    Field("TR-ACTIVE", offset=29, width=1, numeric=False),
)

REPORT_LAYOUT: tuple[Field, ...] = (
    Field("XL-ID", offset=0, width=16, numeric=False),
    Field("XL-INCOME", offset=16, width=13, numeric=True, decimal_scale=2, signed=True),
    Field("XL-TAX", offset=29, width=11, numeric=True, decimal_scale=2, signed=True),
)

TOTALS_LAYOUT: tuple[Field, ...] = (
    Field("TL-LABEL", offset=0, width=30, numeric=False),
    Field("TL-TOTAL", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
    Field("TL-FILLER", offset=41, width=1, numeric=False),
)

__all__ = ["Field", "INPUT_LAYOUT", "REPORT_LAYOUT", "TOTALS_LAYOUT", "record_width"]
