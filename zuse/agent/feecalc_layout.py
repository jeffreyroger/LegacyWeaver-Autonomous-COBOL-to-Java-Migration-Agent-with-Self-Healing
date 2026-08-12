"""Declared field layouts for FEECALC — Step S1's second program.

Mirrors zuse.layout's shape (Field/INPUT_LAYOUT/REPORT_LAYOUT/
TOTALS_LAYOUT) but is deliberately its own module: zuse.layout is scoped
to the MVP harness's one oracle fixture (interest.cob) per NFR-14, and
FEECALC is Phase-2-only scaffolding for the cross-program failure-memory
demo, not a second MVP oracle fixture.

Derived from zuse/examples/input/copybooks/FEE-REC.cpy and
zuse/examples/input/feecalc.cob's FEE-REPORT-LINE/FEE-TOTALS-LINE,
cross-checked against zuse/examples/reference_feecalc/fee.out
(a real GnuCOBOL 3.x run via WSL, Step S1) -- line widths (41 bytes detail,
41 bytes totals after GnuCOBOL's trailing-space strip) confirmed against
that file, same as interest.cob's REPORT_LAYOUT/TOTALS_LAYOUT derivation.
"""

from __future__ import annotations

from zuse.layout import Field, record_width  # reuse the same Field dataclass

INPUT_LAYOUT: tuple[Field, ...] = (
    Field("FR-ID", offset=0, width=16, numeric=False),
    Field("FR-BALANCE", offset=16, width=12, numeric=True, decimal_scale=2,
          signed=True, trailing_separate_sign=True),
    Field("FR-TIER", offset=28, width=1, numeric=False),
    Field("FR-ACTIVE", offset=29, width=1, numeric=False),
)

REPORT_LAYOUT: tuple[Field, ...] = (
    Field("FL-ID", offset=0, width=16, numeric=False),
    Field("FL-TIER", offset=16, width=1, numeric=False),
    Field("FL-BALANCE", offset=17, width=13, numeric=True, decimal_scale=2, signed=True),
    Field("FL-FEE", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
)

TOTALS_LAYOUT: tuple[Field, ...] = (
    Field("TL-LABEL", offset=0, width=30, numeric=False),
    Field("TL-TOTAL", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
    Field("TL-FILLER", offset=41, width=1, numeric=False),
)

__all__ = ["Field", "INPUT_LAYOUT", "REPORT_LAYOUT", "TOTALS_LAYOUT", "record_width"]
