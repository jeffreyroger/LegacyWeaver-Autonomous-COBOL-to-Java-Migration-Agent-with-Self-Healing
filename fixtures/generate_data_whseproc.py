"""Deterministic input generator for WHSEPROC (fixtures/cobol/asdf.cob).

Mirrors fixtures/generate_data.py's approach for interest.cob: same seed,
same output, always -- no timestamp, no randomness left unseeded.

Record encoding, per fixtures/cobol/asdf.cob's ORDER-RECORD (33 bytes):
    OR-ORDER-ID    offset 0,  width 10  "ORD" + 7-digit sequence number
    OR-PRODUCT-ID  offset 10, width 10  "PROD" + letter, space-padded
    OR-QUANTITY    offset 20, width 5   zero-padded integer, no decimal
    OR-UNIT-PRICE  offset 25, width 7   zero-padded, implied 2 decimals
    OR-PRIORITY    offset 32, width 1   H / M / L
"""

from __future__ import annotations

import random
from pathlib import Path

SEED = 42
RECORD_COUNT = 60
OUTPUT_PATH = Path(__file__).parent / "data_whseproc" / "orders.dat"

PRODUCTS = ["PRODA", "PRODB", "PRODC", "PRODD", "PRODE"]
PRIORITIES = ["H", "M", "L"]


def _record(seq: int, rng: random.Random) -> str:
    order_id = f"ORD{seq:07d}"
    product_id = rng.choice(PRODUCTS).ljust(10)
    quantity = rng.randint(1, 500)
    # Cents, so the truncation trap (COMPUTE without ROUNDED) has digits to bite on.
    unit_price_cents = rng.randint(1, 99999)
    priority = rng.choice(PRIORITIES)
    return f"{order_id}{product_id}{quantity:05d}{unit_price_cents:07d}{priority}"


def generate() -> list[str]:
    rng = random.Random(SEED)
    return [_record(i + 1, rng) for i in range(RECORD_COUNT)]


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = generate()
    OUTPUT_PATH.write_text("\n".join(records) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
