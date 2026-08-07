"""Deterministic defect classification (Step E1/E2; FR-13).

Rules are evaluated in this fixed order -- more specific before more
general -- and use exact decimal arithmetic only (DC-3). No language model
participates in classification (Step E1 rationale).

    1. PADDING       -- equal after whitespace strip, unequal raw
    2. SIGN          -- equal magnitude, opposite sign
    3. SCALE         -- ratio approximates a power of ten
    4. TRUNCATION    -- both numeric; |delta| <= 1 ULP at field scale
    5. CONTROL_FLOW  -- record counts differ, a field is absent, or one
                        side is exactly zero and the other is not (a
                        branch, e.g. the dormant-account check, took a
                        different path -- SRS Open Issue OI-1)
    6. UNKNOWN       -- nothing above matched

Note on rule 4 (TRUNCATION threshold): SRS FR-13 states the test as
"strictly less than one ULP". In practice, two values that are each
already rounded/truncated to the field's declared scale can only ever
differ by a whole multiple of that scale's ULP -- a round-half-up-vs-
truncate defect (T1) therefore always produces a delta of *exactly* one
ULP when it manifests, never a fractional one. A strict "<" would make
this rule unable to ever match the defect it exists to catch. This
implementation uses "<=" (inclusive) so the rule is actually reachable;
this is a considered resolution of that wording, not a silent
loosening -- see CLAUDE.md and the Step D5/E2 acceptance run for the
measured effect (AC-10: UNKNOWN <= 15%).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from weaver.comparison import Divergence


class DefectClass(str, Enum):
    PADDING = "PADDING"
    SIGN = "SIGN"
    SCALE = "SCALE"
    TRUNCATION = "TRUNCATION"
    CONTROL_FLOW = "CONTROL_FLOW"
    UNKNOWN = "UNKNOWN"


@dataclass
class Classification:
    defect_class: DefectClass
    confidence: float
    evidence: dict


def _parse_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw)
    except Exception:
        return None


def _is_power_of_ten_ratio(a: Decimal, b: Decimal) -> bool:
    if a == 0 or b == 0:
        return False
    ratio = abs(a / b)
    if ratio < 1:
        ratio = 1 / ratio
    power = ratio.log10()
    return abs(power - round(power)) < Decimal("0.001") and round(power) != 0


def classify(div: Divergence, field_decimal_scale: int = 2) -> Classification:
    o_raw, c_raw = div.oracle_value, div.candidate_value
    o_stripped, c_stripped = o_raw.strip(), c_raw.strip()

    # 1. PADDING
    if o_stripped == c_stripped and o_raw != c_raw:
        return Classification(DefectClass.PADDING, 1.0, {"oracle": o_raw, "candidate": c_raw})

    o_num, c_num = _parse_decimal(o_stripped), _parse_decimal(c_stripped)

    # 2. SIGN
    if o_num is not None and c_num is not None and o_num != c_num and abs(o_num) == abs(c_num):
        return Classification(DefectClass.SIGN, 1.0, {"oracle": str(o_num), "candidate": str(c_num)})

    # 3. SCALE
    if o_num is not None and c_num is not None and _is_power_of_ten_ratio(o_num, c_num):
        return Classification(DefectClass.SCALE, 0.9, {"oracle": str(o_num), "candidate": str(c_num)})

    # 4. TRUNCATION (see module docstring for the "<=" rationale)
    if o_num is not None and c_num is not None and div.numeric_delta is not None:
        ulp = Decimal(1).scaleb(-field_decimal_scale)
        if abs(div.numeric_delta) <= ulp:
            return Classification(DefectClass.TRUNCATION, 0.9, {"delta": str(div.numeric_delta)})

    # 5. CONTROL_FLOW
    if o_raw == "" or c_raw == "":
        return Classification(DefectClass.CONTROL_FLOW, 1.0, {"oracle": o_raw, "candidate": c_raw})
    if o_num is not None and c_num is not None and (o_num == 0) != (c_num == 0):
        return Classification(DefectClass.CONTROL_FLOW, 0.8, {"oracle": str(o_num), "candidate": str(c_num)})

    # 6. UNKNOWN
    return Classification(DefectClass.UNKNOWN, 0.0, {"oracle": o_raw, "candidate": c_raw})


def summarize(classifications: list[Classification]) -> dict:
    """Aggregate by class: counts, percentages, one representative example."""
    total = len(classifications)
    summary: dict[str, dict] = {}
    for c in classifications:
        entry = summary.setdefault(c.defect_class.value, {"count": 0, "example": None})
        entry["count"] += 1
        if entry["example"] is None:
            entry["example"] = c.evidence
    for entry in summary.values():
        entry["percentage"] = round(100 * entry["count"] / total, 1) if total else 0.0
    return summary
