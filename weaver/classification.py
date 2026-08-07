"""Deterministic defect classification (Step E1/E2; FR-13).

Rules are evaluated in this fixed order -- more specific before more
general -- and use exact decimal arithmetic only (DC-3). No language model
participates in classification (Step E1 rationale).

    1. PADDING       -- equal after whitespace strip, unequal raw
    2. SIGN          -- equal magnitude, opposite sign
    3. SCALE         -- ratio approximates a power of ten
    4. TRUNCATION    -- both numeric; |delta| < 1 ULP at field scale
    5. CONTROL_FLOW  -- record counts differ, or a field is absent
    6. UNKNOWN       -- nothing above matched
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


def _is_power_of_ten_ratio(a: Decimal, b: Decimal) -> bool:
    if a == 0 or b == 0:
        return False
    ratio = abs(a / b)
    if ratio < 1:
        ratio = 1 / ratio
    # Check ratio is close to 10, 100, 1000 ...
    power = ratio.log10()
    return abs(power - round(power)) < Decimal("0.001") and round(power) != 0


def classify(div: Divergence, field_decimal_scale: int = 2) -> Classification:
    o_stripped, c_stripped = div.oracle_value.strip(), div.candidate_value.strip()

    if o_stripped == c_stripped and div.oracle_value != div.candidate_value:
        return Classification(DefectClass.PADDING, 1.0, {"oracle": div.oracle_value, "candidate": div.candidate_value})

    if div.oracle_value == "" or div.candidate_value == "":
        return Classification(DefectClass.CONTROL_FLOW, 1.0, {"oracle": div.oracle_value, "candidate": div.candidate_value})

    try:
        o_num, c_num = Decimal(o_stripped), Decimal(c_stripped)
    except Exception:
        return Classification(DefectClass.UNKNOWN, 0.0, {"oracle": div.oracle_value, "candidate": div.candidate_value})

    if abs(o_num) == abs(c_num) and o_num != c_num:
        return Classification(DefectClass.SIGN, 1.0, {"oracle": str(o_num), "candidate": str(c_num)})

    if _is_power_of_ten_ratio(o_num, c_num):
        return Classification(DefectClass.SCALE, 0.9, {"oracle": str(o_num), "candidate": str(c_num)})

    ulp = Decimal(1).scaleb(-field_decimal_scale)
    if div.numeric_delta is not None and abs(div.numeric_delta) < ulp:
        return Classification(DefectClass.TRUNCATION, 0.9, {"delta": str(div.numeric_delta)})

    return Classification(DefectClass.UNKNOWN, 0.0, {"oracle": str(o_num), "candidate": str(c_num)})


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
