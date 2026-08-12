"""COBOL frontend — Phase U.

Derives what was previously hand-declared per program (byte layouts,
condition names, working-storage fields, file names, paragraph identity,
and the main-loop field mapping) from the COBOL source and its copybooks.

Layering: this package parses *once*, upstream, and emits data. Nothing in
`zuse/agent/scaffold.py` reads COBOL text — it still consumes only a
`ScaffoldSpec`, exactly as AGENT_LAYER_PLAN.md Step K2 requires ("generate
from the parsed field table -- never from the COBOL source text"). This
package is the thing that produces that parsed, validated table.

The hand-written tables (`zuse/layout.py`, `zuse/agent/feecalc_layout.py`,
`INTEREST_SPEC`, `FEECALC_SPEC`) are retained as the regression oracle for
this parser, not as the live source of truth.
"""
