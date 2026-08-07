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


# Populated per Step B1 -- see fixtures/cobol/copybooks/ACCOUNT-REC.cpy for
# the byte-offset derivation this must match exactly. Total width 39 bytes.
INPUT_LAYOUT: tuple[Field, ...] = (
    Field("AR-ID", offset=0, width=16, numeric=False),
    Field("AR-BALANCE", offset=16, width=12, numeric=True, decimal_scale=2,
          signed=True, trailing_separate_sign=True),
    Field("AR-RATE", offset=28, width=6, numeric=True, decimal_scale=5),
    Field("AR-TYPE", offset=34, width=1, numeric=False),
    Field("AR-FLAGS", offset=35, width=4, numeric=False),
    Field("AR-DORMANT", offset=35, width=1, numeric=False, redefines="AR-FLAGS"),
    Field("AR-HOLD", offset=36, width=1, numeric=False, redefines="AR-FLAGS"),
)

# Populated per Step D3, derived from the REPORT-LINE declaration in
# fixtures/cobol/interest.cob. Total width 42 bytes (200 detail lines +
# 1 totals line of the same width).
#
# RL-BALANCE / RL-INTEREST use PIC -(9)9.99 / -(7)9.99: the floating-sign
# width is one position wider than the maximum digit count so a
# maximum-magnitude negative value never has to compete with its own
# sign for a print position (a real overflow bug caught during Step B4/B5
# review -- the original -(8)9.99 / -(6)9.99 pictures silently dropped
# the leading digit of the max-magnitude boundary records).
REPORT_LAYOUT: tuple[Field, ...] = (
    Field("RL-ID", offset=0, width=16, numeric=False),
    Field("RL-TYPE", offset=16, width=1, numeric=False),
    Field("RL-BALANCE", offset=17, width=13, numeric=True, decimal_scale=2, signed=True),
    Field("RL-INTEREST", offset=30, width=11, numeric=True, decimal_scale=2, signed=True),
    Field("RL-DORMANT", offset=41, width=1, numeric=False),
)


def record_width(layout: tuple[Field, ...]) -> int:
    """Sum of non-REDEFINES field widths -- the declared record length."""
    return sum(f.width for f in layout if f.redefines is None)
