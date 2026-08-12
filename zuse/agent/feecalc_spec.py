"""FEECALC's ScaffoldSpec — Step S1.

Reuses zuse.agent.scaffold's generic generator (K2, generalized) with
FEECALC's own field tables (zuse.agent.feecalc_layout) instead of
interest.cob's. No condition names: FEECALC's tier lookup is a plain
EVALUATE, not an 88-level (deliberately different shape from interest.cob's
condition-name-driven branching, per S1's "different arithmetic" note).
"""

from __future__ import annotations

from zuse.agent import feecalc_layout as layout
from zuse.agent.scaffold import ScaffoldSpec, WorkingStorageField

FEECALC_SPEC = ScaffoldSpec(
    input_file="fees.dat",
    output_file="fee.out",
    input_layout=layout.INPUT_LAYOUT,
    report_layout=layout.REPORT_LAYOUT,
    totals_layout=layout.TOTALS_LAYOUT,
    condition_names=(),
    paragraph_id="COMPUTE-FEE",
    paragraph_method="computeFee",
    ws_fields=(
        WorkingStorageField("rate", 5),
        WorkingStorageField("fee", 2),
        WorkingStorageField("totalFee", 2),
    ),
    accumulator_field="totalFee",
    per_record_field="fee",
    report_ctor_map={
        "FL-ID": "ar.id", "FL-TIER": "ar.tier", "FL-BALANCE": "ar.balance", "FL-FEE": "ws.fee",
    },
    totals_ctor_map={
        "TL-LABEL": 'Scaffold.pad("TOTAL FEE:", 30)',
        "TL-TOTAL": "ws.totalFee", "TL-FILLER": '" "',
    },
)
