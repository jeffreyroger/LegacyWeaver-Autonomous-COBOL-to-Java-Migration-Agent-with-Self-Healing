"""Deterministic input generator for BANKPROC (fixtures/cobol/test3.cob).

Mirrors fixtures/generate_data.py's approach for interest.cob: same seed,
same output, always.

Record encoding, per fixtures/cobol/test3.cob's TRANSACTION-RECORD (20 bytes):
    TX-ACCOUNT-ID  offset 0,  width 10  "ACCT" + 6-digit account number
    TX-TYPE        offset 10, width 1   D (deposit) / W (withdrawal)
    TX-AMOUNT      offset 11, width 9   zero-padded, implied 2 decimals

Deliberately biases early withdrawals toward exceeding a near-zero opening
balance, so the NSF (insufficient funds) branch is actually exercised
rather than only ever taking the happy path.
"""

from __future__ import annotations

import random
from pathlib import Path

SEED = 42
RECORD_COUNT = 60
OUTPUT_PATH = Path(__file__).parent / "data_bankproc" / "transactions.dat"

ACCOUNTS = [f"ACCT{n:06d}" for n in range(1, 6)]


def _record(rng: random.Random) -> str:
    account_id = rng.choice(ACCOUNTS)
    tx_type = rng.choice(["D", "W"])
    amount_cents = rng.randint(1, 999999)
    return f"{account_id}{tx_type}{amount_cents:09d}"


def generate() -> list[str]:
    rng = random.Random(SEED)
    return [_record(rng) for _ in range(RECORD_COUNT)]


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = generate()
    OUTPUT_PATH.write_text("\n".join(records) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
