"""Step C4 throwaway script: predict the oracle-vs-baseline divergence
count independently of the differential runner (Phase D), so Phase D can
be validated against a number established beforehand rather than the
other way around.

Applies COBOL semantics (exact decimal, truncate toward zero) and the
baseline's naive semantics (binary float, round half-up, sign-blind
balance parsing, whole-string dormant comparison) to each of the 200
records in fixtures/data/accounts.dat, and counts how many produce a
different displayed balance and/or interest value.

This is NOT part of the weaver package -- it is deliberately a one-off,
disposable prediction script per the runbook (Step C4), kept only so the
number it produces is reproducible and auditable.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from weaver.layout import INPUT_LAYOUT


def slice_fields(line: str) -> dict:
    return {f.name: line[f.offset: f.offset + f.width] for f in INPUT_LAYOUT}


def cobol_semantics(fields: dict) -> tuple[Decimal, Decimal]:
    balance_digits, sign = fields["AR-BALANCE"][:-1], fields["AR-BALANCE"][-1]
    balance = Decimal(balance_digits) / 100
    if sign == "-":
        balance = -balance

    rate = Decimal(fields["AR-RATE"]) / 100_000
    premium = fields["AR-TYPE"] == "P"
    dormant = fields["AR-DORMANT"] == "Y"

    applied_rate = (rate * Decimal("1.15")).quantize(Decimal("0.00000"), rounding=ROUND_DOWN) if premium else rate

    if dormant:
        interest = Decimal("0.00")
    else:
        interest = (balance * applied_rate / 365).quantize(Decimal("0.00"), rounding=ROUND_DOWN)

    return balance, interest


def baseline_semantics(fields: dict) -> tuple[Decimal, Decimal]:
    balance_digits = fields["AR-BALANCE"][:-1]  # sign byte never read (T6)
    balance = float(Decimal(balance_digits) / 100)  # always non-negative

    rate = float(Decimal(fields["AR-RATE"]) / 100_000)
    premium = fields["AR-TYPE"] == "P"
    # whole 4-byte flags field compared against "Y" -- can never be true (T3)
    treated_as_dormant = False

    applied_rate = rate * 1.15 if premium else rate

    if treated_as_dormant:
        interest = 0.0
    else:
        raw = balance * applied_rate / 365
        interest = float(Decimal(raw).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP))

    return Decimal(str(round(balance, 2))), Decimal(str(interest))


def main() -> None:
    with open("fixtures/data/accounts.dat") as f:
        lines = [line for line in f.read().splitlines() if line]

    total = 0
    balance_mismatch = 0
    interest_mismatch = 0
    divergent = 0

    for line in lines:
        fields = slice_fields(line)
        total += 1
        cobol_balance, cobol_interest = cobol_semantics(fields)
        naive_balance, naive_interest = baseline_semantics(fields)

        b_diff = cobol_balance != naive_balance
        i_diff = cobol_interest != naive_interest
        if b_diff:
            balance_mismatch += 1
        if i_diff:
            interest_mismatch += 1
        if b_diff or i_diff:
            divergent += 1

    print(f"records examined        : {total}")
    print(f"balance value mismatches: {balance_mismatch}  (T6 -- sign byte ignored)")
    print(f"interest value mismatches: {interest_mismatch}  (T1 rounding + T3/T4 combined)")
    print(f"predicted divergent recs: {divergent} / {total}")


if __name__ == "__main__":
    main()
