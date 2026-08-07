"""Deterministic input generator (Step B3; FR-4).

Two invocations with the same seed must produce byte-identical output.
200 fixed-width (39-byte) records covering every planted trap:

    Truncation-boundary balances   40   T1
    Ordinary savings               50   baseline
    Negative balances              25   T6 (trailing separate sign)
    Dormant accounts               25   T3 (REDEFINES overlay)
    Premium accounts               30   T4 (88-level tier)
    Hold flag                      15   T3 (second overlay byte)
    Boundary values                15   zero / max / min / zero-rate

TODO(Step B3): implement record encoding per weaver.layout.INPUT_LAYOUT
once that layout is filled in from the Step B1 offset table:
  - Balance: 11-digit zero-padded paise + separate '+'/'-' sign, no '.'.
  - Rate: 6-digit integer scaled by 100000, no '.'.
  - Flags: 4 bytes; byte 1 is the dormant indicator (REDEFINES overlay).
"""

from __future__ import annotations

import random
from pathlib import Path

SEED = 20260807
RECORD_COUNT = 200
RECORD_WIDTH = 39

GROUP_COUNTS = {
    "truncation_boundary": 40,
    "ordinary_savings": 50,
    "negative_balance": 25,
    "dormant": 25,
    "premium": 30,
    "hold_flag": 15,
    "boundary": 15,
}


def generate_records(seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    records: list[str] = []
    # TODO: build one record per GROUP_COUNTS entry, encoded per layout.
    del rng
    return records


def main(output_path: Path) -> None:
    records = generate_records()
    output_path.write_text("\n".join(records) + ("\n" if records else ""))


if __name__ == "__main__":
    import sys

    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/data/accounts.dat"))
