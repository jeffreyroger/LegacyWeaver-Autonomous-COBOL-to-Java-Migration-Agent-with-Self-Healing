"""Declared field layouts for TIERACCUM — Step U2's in-paragraph-loop program.

Mirrors zuse.agent.feecalc_layout/taxcalc_layout's shape/rationale (own
module per NFR-14, not a second MVP oracle). Offsets/widths confirmed
against a real GnuCOBOL 3.2.0 run via WSL against
zuse/examples/input/data/tieraccum.dat, producing
zuse/examples/input/data/expected/golden_tieraccum.out (detail line 40
bytes, totals line 41 bytes after GnuCOBOL's trailing-space strip).

UR-UNITS is read by ACCUMULATE-TIERS (it drives the loop bound) but is not
carried through to the report line. Originally this was a genuine gap --
PIC 99's plain zero-padded unsigned edit was a different mask style
`CobolEdit.floatingSign` couldn't produce -- but `Field.edit_style` and
`CobolEdit.zeroPadded` (added 2026-08-12) now support it. Still left off
this report line: this fixture exists to exercise the in-paragraph-loop
control-flow shape (Step U2), and adding a column here would be scope
creep on an already-verified, byte-identical golden fixture for no
signal U2 needs -- see zuse/layout.py's Field.edit_style docstring for
the general capability, exercised instead by any future fixture that
actually needs it.
"""

from __future__ import annotations

from zuse.layout import Field, record_width  # reuse the same Field dataclass

INPUT_LAYOUT: tuple[Field, ...] = (
    Field("UR-ID", offset=0, width=16, numeric=False),
    Field("UR-BASE", offset=16, width=12, numeric=True, decimal_scale=2,
          signed=True, trailing_separate_sign=True),
    Field("UR-UNITS", offset=28, width=2, numeric=True, decimal_scale=0, signed=False),
)

REPORT_LAYOUT: tuple[Field, ...] = (
    Field("YL-ID", offset=0, width=16, numeric=False),
    Field("YL-BASE", offset=16, width=13, numeric=True, decimal_scale=2, signed=True),
    Field("YL-ACCUM", offset=29, width=11, numeric=True, decimal_scale=2, signed=True),
)

TOTALS_LAYOUT: tuple[Field, ...] = (
    Field("TL-LABEL", offset=0, width=30, numeric=False),
    Field("TL-TOTAL", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
    Field("TL-FILLER", offset=41, width=1, numeric=False),
)

__all__ = ["Field", "INPUT_LAYOUT", "REPORT_LAYOUT", "TOTALS_LAYOUT", "record_width"]
