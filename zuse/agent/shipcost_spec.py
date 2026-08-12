"""SHIPCOST's ScaffoldSpec — Step U4.

Reuses zuse.agent.scaffold's generic generator (K2, generalized S1) with
SHIPCOST's own field tables (zuse.agent.shipcost_layout). No condition
names: the compound conditions live directly in COMPUTE-SHIPCOST's
EVALUATE TRUE WHEN clauses (SR-WEIGHT and SR-ZONE combined with AND), not
in 88-levels -- deliberately a different shape from every prior fixture.
"""

from __future__ import annotations

from zuse.agent import shipcost_layout as layout
from zuse.agent.scaffold import ScaffoldSpec, WorkingStorageField

SHIPCOST_SPEC = ScaffoldSpec(
    input_file="shipcost.dat",
    output_file="shipcost.out",
    input_layout=layout.INPUT_LAYOUT,
    report_layout=layout.REPORT_LAYOUT,
    totals_layout=layout.TOTALS_LAYOUT,
    condition_names=(),
    paragraph_id="COMPUTE-SHIPCOST",
    paragraph_method="computeShipcost",
    ws_fields=(
        WorkingStorageField("cost", 2),
        WorkingStorageField("totalCost", 2),
    ),
    accumulator_field="totalCost",
    per_record_field="cost",
    report_ctor_map={
        "EL-ID": "ar.id", "EL-WEIGHT": "ar.weight", "EL-COST": "ws.cost",
    },
    totals_ctor_map={
        "TL-LABEL": 'Scaffold.pad("TOTAL COST:", 30)',
        "TL-TOTAL": "ws.totalCost", "TL-FILLER": '" "',
    },
)
