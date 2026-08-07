"""LegacyWeaver MVP — differential verification harness.

Modules are kept separable per SRS NFR-13 (no circular dependency):
    layout          -- declared field tables (input + report), data not code (NFR-14)
    execution       -- dual execution of oracle and candidate (Step D2)
    comparison      -- byte-for-byte comparison + field resolution (Step D1, D3)
    classification  -- deterministic defect classification (Step E2)
    report          -- serialisable report structure (Step D4)
    cli             -- the single `verify` command (Step F2)
"""
