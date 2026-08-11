"""COMPOUND's ScaffoldSpec — Step U3.

Reuses weaver.agent.scaffold's generic generator (K2, generalized S1) with
COMPOUND's own field tables (weaver.agent.compound_layout). No condition
names: COMPUTE-COMPOUND has no branching at all -- ws_fields lists only the
per-record result and the running accumulator; the four intermediate steps
(WS-STEP1..4) are local Java variables in the synthesized body, the same
treatment tieraccum.cob's loop-only WS-IDX/WS-STEP get (Step U2), since
neither is read by the scaffold's main loop or the report/totals ctor maps.
"""

from __future__ import annotations

from weaver.agent import compound_layout as layout
from weaver.agent.scaffold import ScaffoldSpec, WorkingStorageField

COMPOUND_SPEC = ScaffoldSpec(
    input_file="compound.dat",
    output_file="compound.out",
    input_layout=layout.INPUT_LAYOUT,
    report_layout=layout.REPORT_LAYOUT,
    totals_layout=layout.TOTALS_LAYOUT,
    condition_names=(),
    paragraph_id="COMPUTE-COMPOUND",
    paragraph_method="computeCompound",
    ws_fields=(
        WorkingStorageField("result", 2),
        WorkingStorageField("totalResult", 2),
    ),
    accumulator_field="totalResult",
    per_record_field="result",
    report_ctor_map={
        "DL-ID": "ar.id", "DL-PRINCIPAL": "ar.principal", "DL-RESULT": "ws.result",
    },
    totals_ctor_map={
        "TL-LABEL": 'Scaffold.pad("TOTAL RESULT:", 30)',
        "TL-TOTAL": "ws.totalResult", "TL-FILLER": '" "',
    },
)
