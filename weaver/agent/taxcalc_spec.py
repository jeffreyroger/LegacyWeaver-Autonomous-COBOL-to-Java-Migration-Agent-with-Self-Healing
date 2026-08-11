"""TAXCALC's ScaffoldSpec — Step U1.

Reuses weaver.agent.scaffold's generic generator (K2, generalized S1) with
TAXCALC's own field tables (weaver.agent.taxcalc_layout). No condition
names: the bracket selection is a nested IF/ELSE ladder in COMPUTE-TAX's
body, not an 88-level -- deliberately a different control-flow shape from
both interest.cob (single 88-level branch) and feecalc.cob (flat EVALUATE).
"""

from __future__ import annotations

from weaver.agent import taxcalc_layout as layout
from weaver.agent.scaffold import ScaffoldSpec, WorkingStorageField

TAXCALC_SPEC = ScaffoldSpec(
    input_file="tax.dat",
    output_file="tax.out",
    input_layout=layout.INPUT_LAYOUT,
    report_layout=layout.REPORT_LAYOUT,
    totals_layout=layout.TOTALS_LAYOUT,
    condition_names=(),
    paragraph_id="COMPUTE-TAX",
    paragraph_method="computeTax",
    ws_fields=(
        WorkingStorageField("tax", 2),
        WorkingStorageField("totalTax", 2),
    ),
    accumulator_field="totalTax",
    per_record_field="tax",
    report_ctor_map={
        "XL-ID": "ar.id", "XL-INCOME": "ar.income", "XL-TAX": "ws.tax",
    },
    totals_ctor_map={
        "TL-LABEL": 'Scaffold.pad("TOTAL TAX:", 30)',
        "TL-TOTAL": "ws.totalTax", "TL-FILLER": '" "',
    },
)
