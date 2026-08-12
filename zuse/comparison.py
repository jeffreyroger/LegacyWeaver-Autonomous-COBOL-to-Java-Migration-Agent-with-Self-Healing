"""Byte-for-byte comparison and field resolution (Step D1, D3; FR-10, FR-11).

Comparison contract (must not be relaxed — see MVP SRS FR-10):
  1. Comparison is byte-for-byte.
  2. The only permitted normalisation is line-ending conversion (CRLF -> LF).
  3. Trailing whitespace differences are genuine divergences.
  4. Exit statuses are compared.
  5. Verified iff divergence count is zero AND exit statuses match.
  6. No tolerance, threshold, heuristic, or model participates.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from zuse.layout import Field, REPORT_LAYOUT


@dataclass
class Divergence:
    record_index: int
    byte_offset: int
    field_name: str
    oracle_value: str
    candidate_value: str
    numeric_delta: Decimal | None
    causing_input_record: str | None


def normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n")


def _parse_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, ValueError):
        return None


def resolve_field(oracle_line: str, candidate_line: str, layout: tuple[Field, ...] = REPORT_LAYOUT
                   ) -> Field | None:
    """Return the first field (in layout order) whose slice differs, or None."""
    for field in layout:
        o = oracle_line[field.offset: field.offset + field.width]
        c = candidate_line[field.offset: field.offset + field.width]
        if o != c:
            return field
    return None


def compare_lines(record_index: int, oracle_line: str, candidate_line: str,
                   input_record: str | None, layout: tuple[Field, ...] = REPORT_LAYOUT
                   ) -> Divergence | None:
    if oracle_line == candidate_line:
        return None

    field = resolve_field(oracle_line, candidate_line, layout)
    if field is None:
        # Lines differ but no declared field slice differs (e.g. layout gap).
        field_name, offset = "UNDECLARED", 0
        o_val, c_val = oracle_line, candidate_line
    else:
        field_name, offset = field.name, field.offset
        o_val = oracle_line[field.offset: field.offset + field.width]
        c_val = candidate_line[field.offset: field.offset + field.width]

    o_num, c_num = _parse_decimal(o_val), _parse_decimal(c_val)
    delta = (o_num - c_num) if (o_num is not None and c_num is not None) else None

    return Divergence(record_index, offset, field_name, o_val, c_val, delta, input_record)
