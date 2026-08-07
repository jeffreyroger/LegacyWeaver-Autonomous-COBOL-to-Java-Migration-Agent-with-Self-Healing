# Oracle hand verification (Step B5, AC-3)

Five records, spanning the distinct logic paths of `INTEREST.CBL`, decoded
by hand from `fixtures/data/accounts.dat` against the Step B1 offset table
and computed against the program's stated semantics (no ROUNDED clause
anywhere — COBOL's default `COMPUTE` truncates toward zero):

- **premium**: `applied_rate = TRUNC(rate * 1.15, 5 decimals)`
- **dormant**: `interest = 0`, unconditionally
- **otherwise**: `interest = TRUNC(balance * applied_rate / 365, 2 decimals)`

Verified against `fixtures/data/expected/golden_interest.out`
(sha256 `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`,
201 lines, 10/10 identical runs — see Step B4).

> **Note:** this checksum was regenerated after fixing an edit-mask overflow
> bug found during this review: `RL-BALANCE`/`RL-INTEREST` originally used
> `PIC -(8)9.99` / `-(6)9.99`, one print position too narrow to hold a
> maximum-magnitude value (9 / 7 digits) together with its sign, so the
> boundary records with balance ±999,999,999.99 silently lost their
> leading digit on output (displaying as ±99,999,999.99). Widened to
> `-(9)9.99` / `-(7)9.99`. See `weaver/layout.py` REPORT_LAYOUT for the
> corrected 42-byte report-line offsets.

## Record 41 — ordinary savings

Input: `AR-BALANCE=+55788.69`, `AR-RATE=0.14671`, `AR-TYPE=S` (not premium, not dormant).

```
balance * rate = 55788.69 * 0.14671 = 8184.7587099
                 8184.7587099 / 365  = 22.4239964...
truncate to 2 decimals              = 22.42
```

Golden output: `ACCT000000000041S     55788.69      22.42N` → **22.42, matches.**

## Record 141 — premium

Input: `AR-BALANCE=+238884.00`, `AR-RATE=0.07028`, `AR-TYPE=P` (premium, 88-level `AR-PREMIUM`).

```
applied_rate = TRUNC(0.07028 * 1.15, 5 decimals)
             = TRUNC(0.080822, 5 decimals) = 0.08082   <- second truncation, T4/T1
balance * applied_rate = 238884.00 * 0.08082 = 19306.60488
                          19306.60488 / 365  = 52.894808...
truncate to 2 decimals                       = 52.89
```

Golden output: `ACCT000000000141P    238884.00      52.89N` → **52.89, matches.**

Note the two distinct truncations in the premium path (rate to 5 decimals,
then interest to 2 decimals) — this is the failure mode the runbook
specifically warns is easy to under-count.

## Record 116 — dormant

Input: `AR-BALANCE=+240493.00`, `AR-RATE=0.10315`, `AR-DORMANT=Y`.

```
dormant => interest = 0.00, regardless of balance or rate
```

Golden output: `ACCT000000000116S    240493.00       0.00Y` → **0.00, matches.**

## Record 91 — negative balance (trailing separate sign, T6)

Input: `AR-BALANCE=-86452.37`, `AR-RATE=0.03466`, `AR-TYPE=S`.

```
balance * rate = -86452.37 * 0.03466 = -2996.4391442
                 -2996.4391442 / 365  = -8.209421...
truncate toward zero to 2 decimals   = -8.20   (NOT -8.21 — truncation
                                                  toward zero drops
                                                  magnitude, not rounds)
```

Golden output: `ACCT000000000091S    -86452.37      -8.20N` → **-8.20, matches.**

## Record 186 — boundary (zero balance)

Input: `AR-BALANCE=0.00`, `AR-RATE=0.05000`, `AR-TYPE=S`.

```
0.00 * 0.05000 / 365 = 0.00
```

Golden output: `ACCT000000000186S         0.00       0.00N` → **0.00, matches.**

## Result

**All 5/5 hand calculations match the golden output exactly.** AC-3 satisfied.
