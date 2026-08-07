"""Deterministic input generator (Step B3; FR-4).

Two invocations with the same seed produce byte-identical output. 200
fixed-width (39-byte) records covering every planted trap (SRS FR-2):

    Group                          Count   Trap
    truncation_boundary            40      T1  (interest lands near a
                                                 non-terminating decimal,
                                                 so truncation vs. naive
                                                 rounding disagree)
    ordinary_savings                50      baseline correctness
    negative_balance                25      T6  (trailing separate sign)
    dormant                         25      T3  (REDEFINES overlay, byte 1)
    premium                         30      T4  (88-level tier)
    hold_flag                       15      T3  (REDEFINES overlay, byte 2)
    boundary                        15      zero / max / min / zero-rate

Record encoding, per weaver.layout.INPUT_LAYOUT (must match exactly):
    AR-ID        offset 0,  width 16  "ACCT" + 12-digit sequence number
    AR-BALANCE   offset 16, width 12  11-digit zero-padded paise, no '.',
                                       followed by a separate '+'/'-' sign
    AR-RATE      offset 28, width 6   6-digit integer scaled by 100000,
                                       no '.'
    AR-TYPE      offset 34, width 1   'P' premium, 'S' standard savings
    AR-FLAGS     offset 35, width 4   byte1 dormant Y/N, byte2 hold Y/N,
                                       bytes 3-4 filler spaces
"""

from __future__ import annotations

import random
from dataclasses import dataclass
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
assert sum(GROUP_COUNTS.values()) == RECORD_COUNT


@dataclass
class AccountRecord:
    account_id: str
    balance_paise: int      # signed, magnitude <= 99_999_999_999 (11 digits)
    rate_scaled: int        # unsigned, 0..999_999 (6 digits, i.e. rate * 1e5)
    account_type: str       # 'P' or 'S'
    dormant: str             # 'Y' or 'N'
    hold: str                # 'Y' or 'N'

    def encode(self) -> str:
        balance_digits = f"{abs(self.balance_paise):011d}"
        balance_sign = "-" if self.balance_paise < 0 else "+"
        rate_field = f"{self.rate_scaled:06d}"
        flags = f"{self.dormant}{self.hold}  "
        line = (
            f"{self.account_id:<16}"
            f"{balance_digits}{balance_sign}"
            f"{rate_field}"
            f"{self.account_type}"
            f"{flags}"
        )
        assert len(line) == RECORD_WIDTH, f"record width {len(line)} != {RECORD_WIDTH}"
        return line


def _account_id(seq: int) -> str:
    return f"ACCT{seq:012d}"


def _truncation_boundary_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    """Engineer balance/rate pairs whose interest lands near a
    non-terminating decimal (division by 365), so COBOL truncation and a
    naive round-half-up baseline disagree on the last cent (T1)."""
    records = []
    for i in range(count):
        seq = start_seq + i
        # Vary balance so balance/365 rarely terminates cleanly at 2 decimals.
        balance_rupees = 1000 + seq * 137 + rng.randint(1, 99)
        rate_scaled = 3000 + (seq * 251) % 17000  # 3.000%..20.000%
        records.append(AccountRecord(
            account_id=_account_id(seq),
            balance_paise=balance_rupees * 100,
            rate_scaled=rate_scaled,
            account_type="S",
            dormant="N",
            hold="N",
        ))
    return records


def _ordinary_savings_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    records = []
    for i in range(count):
        seq = start_seq + i
        balance_paise = rng.randint(100, 500_000) * 100 + rng.randint(0, 99)
        rate_scaled = rng.randint(500, 15000)
        records.append(AccountRecord(
            account_id=_account_id(seq),
            balance_paise=balance_paise,
            rate_scaled=rate_scaled,
            account_type="S",
            dormant="N",
            hold="N",
        ))
    return records


def _negative_balance_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    records = []
    for i in range(count):
        seq = start_seq + i
        balance_paise = -(rng.randint(100, 200_000) * 100 + rng.randint(0, 99))
        rate_scaled = rng.randint(500, 15000)
        records.append(AccountRecord(
            account_id=_account_id(seq),
            balance_paise=balance_paise,
            rate_scaled=rate_scaled,
            account_type="S",
            dormant="N",
            hold="N",
        ))
    return records


def _dormant_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    records = []
    for i in range(count):
        seq = start_seq + i
        balance_paise = rng.randint(1000, 300_000) * 100
        rate_scaled = rng.randint(500, 15000)
        records.append(AccountRecord(
            account_id=_account_id(seq),
            balance_paise=balance_paise,
            rate_scaled=rate_scaled,
            account_type="S",
            dormant="Y",
            hold="N",
        ))
    return records


def _premium_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    records = []
    for i in range(count):
        seq = start_seq + i
        balance_paise = rng.randint(10_000, 1_000_000) * 100
        rate_scaled = rng.randint(1000, 20000)
        records.append(AccountRecord(
            account_id=_account_id(seq),
            balance_paise=balance_paise,
            rate_scaled=rate_scaled,
            account_type="P",
            dormant="N",
            hold="N",
        ))
    return records


def _hold_flag_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    records = []
    for i in range(count):
        seq = start_seq + i
        balance_paise = rng.randint(1000, 300_000) * 100
        rate_scaled = rng.randint(500, 15000)
        records.append(AccountRecord(
            account_id=_account_id(seq),
            balance_paise=balance_paise,
            rate_scaled=rate_scaled,
            account_type="S",
            dormant="N",
            hold="Y",
        ))
    return records


def _boundary_records(rng: random.Random, start_seq: int, count: int) -> list[AccountRecord]:
    """Zero, maximum, minimum, and zero-rate edge cases (15 records)."""
    templates = [
        dict(balance_paise=0, rate_scaled=5000),                # zero balance
        dict(balance_paise=99_999_999_999, rate_scaled=99999),  # maximum balance/rate
        dict(balance_paise=1, rate_scaled=1),                   # minimum non-zero
        dict(balance_paise=-99_999_999_999, rate_scaled=5000),  # maximum negative
        dict(balance_paise=50_000_00, rate_scaled=0),           # zero rate
    ]
    del rng  # boundary values are fixed edge cases, not randomised
    records = []
    for i in range(count):
        seq = start_seq + i
        template = templates[i % len(templates)]
        records.append(AccountRecord(
            account_id=_account_id(seq),
            account_type="S",
            dormant="N",
            hold="N",
            **template,
        ))
    return records


_GENERATORS = {
    "truncation_boundary": _truncation_boundary_records,
    "ordinary_savings": _ordinary_savings_records,
    "negative_balance": _negative_balance_records,
    "dormant": _dormant_records,
    "premium": _premium_records,
    "hold_flag": _hold_flag_records,
    "boundary": _boundary_records,
}


def generate_records(seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    records: list[AccountRecord] = []
    seq = 1
    for group, count in GROUP_COUNTS.items():
        group_records = _GENERATORS[group](rng, seq, count)
        records.extend(group_records)
        seq += count
    return [r.encode() for r in records]


def main(output_path: Path) -> None:
    lines = generate_records()
    output_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    import sys

    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/data/accounts.dat"))
