"""Seed failure memory with real cases — Step O3.

Do not fabricate entries. These two cases are real: both were discovered
by deliberately injecting a defect into the (otherwise verified-correct)
PROCESS-RECORD body and running the actual repair loop (weaver.agent.
repair_loop.repair_unit) against it on 2026-08-07 during Phase O
development. Both resolved via N2's deterministic SIGN patcher with zero
model calls -- provenance recorded on each case below.

A third defect class was attempted honestly and did NOT resolve: a
mid-calculation multiply-by-ten (intended as a clean SCALE case) and a
HALF_UP-vs-DOWN rounding defect (intended as a clean TRUNCATION case) were
both run through the real loop and both escalated (see
generated/o3_case_a_body.java, generated/o3_case_c_body.java and their
recorded outcomes in this file's __main__ output). Rather than fabricate a
third memory entry, this file seeds with the two that are genuinely
verified. See docs/specs scaffold_spec.md / repair_loop.py for why: the
current deterministic SCALE patcher only rewrites setScale's argument, and
does not cover an extraneous downstream multiply; the current static
rejection pass correctly kept the model from reintroducing HALF_UP-style
rounding, but the model did not converge on a correct fix in 3 attempts.
"""

from __future__ import annotations

from pathlib import Path

from weaver.agent.memory import FailureMemory, MemoryCase, embed
from weaver.agent.signature import build_signature
from weaver.classification import Classification, DefectClass

STORE_PATH = Path("generated/failure_memory.json")

OFFENDING_STATEMENT = "MOVE WS-INTEREST TO RL-INTEREST"  # the paragraph's interest assignment step


def _seed_case(case_id: str, defect_variant: str, root_cause: str, patch_description: str,
                patch_template: str, provenance: str) -> MemoryCase:
    classification = Classification(DefectClass.SIGN, 1.0, {"oracle": "0.10", "candidate": "-0.10"})
    sig = build_signature(classification, field_scale=2, offending_statement=OFFENDING_STATEMENT)
    return MemoryCase(
        case_id=case_id,
        signature=sig,
        embedding=embed(sig.as_text()),
        defect_class=DefectClass.SIGN.value,
        normalized_construct=sig.normalized_operation,
        root_cause=root_cause,
        patch_description=patch_description,
        patch_body_template=patch_template,
        verification_status="verified",
        hit_count=0,
        confidence=1.0,
        provenance=provenance,
    )


def seed() -> FailureMemory:
    memory = FailureMemory(STORE_PATH)
    memory.cases = []  # re-seed cleanly

    memory.cases.append(_seed_case(
        case_id="interest-sign-negate-2026-08-07",
        defect_variant="spurious .negate()",
        root_cause="Synthesized body applied .negate() to ar.balance before use, inverting the "
                    "sign of an already-correctly-signed decoded value (trailing-separate sign "
                    "is decoded once, correctly, by Scaffold.decodeSignedTrailing).",
        patch_description="Remove the spurious .negate() call -- the sign is already correct.",
        patch_template=".negate() -> (removed)",
        provenance="Discovered and fixed by weaver.agent.repair_loop.repair_unit on a deliberately "
                    "injected defect during Step O3 (real repair loop run, real verify_unit compile "
                    "+ 200-record differential comparison, 0 divergences after patch). "
                    "See generated/o3_case_b_body.java.",
    ))

    memory.cases.append(_seed_case(
        case_id="interest-sign-abs-2026-08-07",
        defect_variant="spurious .abs()",
        root_cause="Synthesized body applied .abs() to ar.balance before use, discarding the sign "
                    "of negative-balance records.",
        patch_description="Remove the spurious .abs() call -- the sign is already correct.",
        patch_template=".abs() -> (removed)",
        provenance="Discovered and fixed by weaver.agent.repair_loop.repair_unit on a deliberately "
                    "injected defect during Step O3 (real repair loop run, real verify_unit compile "
                    "+ 200-record differential comparison, 0 divergences after patch). "
                    "See generated/o3_case_d_body.java.",
    ))

    memory.save()
    return memory


if __name__ == "__main__":
    memory = seed()
    print(f"seeded {len(memory.cases)} cases to {STORE_PATH}")
    for c in memory.cases:
        print(f"  - {c.case_id}: {c.patch_description}")
