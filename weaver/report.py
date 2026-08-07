"""Serialisable comparison report (Step D4; FR-17, SRS §5.4).

The stored divergence list may be capped at 50 entries; the total count
always remains accurate and the cap is indicated (FR-17).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from weaver.comparison import Divergence

DIVERGENCE_CAP = 50


@dataclass
class Report:
    unit_id: str
    total_records: int
    divergences: list[Divergence] = field(default_factory=list)
    divergence_count: int = 0
    exit_codes_match: bool = True
    divergence_list_capped: bool = False

    @property
    def verified(self) -> bool:
        """FR-10 rule 5: verified iff zero divergences AND exit statuses match."""
        return self.divergence_count == 0 and self.exit_codes_match

    def add_divergence(self, div: Divergence) -> None:
        self.divergence_count += 1
        if len(self.divergences) < DIVERGENCE_CAP:
            self.divergences.append(div)
        else:
            self.divergence_list_capped = True

    def to_json(self) -> str:
        def _default(o):
            if isinstance(o, Decimal):
                return str(o)
            return asdict(o)

        payload = {
            "unit_id": self.unit_id,
            "total_records": self.total_records,
            "divergence_count": self.divergence_count,
            "exit_codes_match": self.exit_codes_match,
            "verified": self.verified,
            "divergence_list_capped": self.divergence_list_capped,
            "divergences": [asdict(d) for d in self.divergences],
        }
        return json.dumps(payload, default=_default, indent=2)
