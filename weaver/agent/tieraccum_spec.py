"""TIERACCUM's ScaffoldSpec — Step U2.

Reuses weaver.agent.scaffold's generic generator (K2, generalized S1) with
TIERACCUM's own field tables (weaver.agent.tieraccum_layout). No condition
names: ACCUMULATE-TIERS' control flow is an in-paragraph PERFORM VARYING
loop, not a branch -- deliberately a different shape from every other
fixture (interest.cob's 88-level, feecalc.cob's flat EVALUATE, taxcalc.cob's
nested IF/ELSE), none of which loop inside the synthesis unit itself.
"""

from __future__ import annotations

from weaver.agent import tieraccum_layout as layout
from weaver.agent.scaffold import ScaffoldSpec, WorkingStorageField

TIERACCUM_SPEC = ScaffoldSpec(
    input_file="tieraccum.dat",
    output_file="tieraccum.out",
    input_layout=layout.INPUT_LAYOUT,
    report_layout=layout.REPORT_LAYOUT,
    totals_layout=layout.TOTALS_LAYOUT,
    condition_names=(),
    paragraph_id="ACCUMULATE-TIERS",
    paragraph_method="accumulateTiers",
    ws_fields=(
        WorkingStorageField("accum", 2),
        WorkingStorageField("totalAccum", 2),
    ),
    accumulator_field="totalAccum",
    per_record_field="accum",
    report_ctor_map={
        "YL-ID": "ar.id", "YL-BASE": "ar.base", "YL-ACCUM": "ws.accum",
    },
    totals_ctor_map={
        "TL-LABEL": 'Scaffold.pad("TOTAL ACCUM:", 30)',
        "TL-TOTAL": "ws.totalAccum", "TL-FILLER": '" "',
    },
)
