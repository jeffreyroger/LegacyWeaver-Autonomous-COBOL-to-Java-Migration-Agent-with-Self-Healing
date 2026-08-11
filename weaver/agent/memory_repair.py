"""Query-before-inference repair path — Step O2, item 3.

On a memory hit (similarity >= threshold), apply the matched case's known
patch and verify -- zero model calls. On verification failure after a
memory hit, the case's confidence is decremented and the caller falls
through to normal (N2/N3) repair.
"""

from __future__ import annotations

from pathlib import Path

from weaver.agent.attribution import AttributionResult, verify_unit
from weaver.agent.memory import FailureMemory
from weaver.agent.repair_deterministic import patch_sign
from weaver.agent.runspec import RunSpec
from weaver.agent.signature import build_signature
from weaver.classification import Classification

# The only patch we can currently apply purely from a memory hit's
# "defect_class" without a model call is the deterministic SIGN patcher --
# memory tells us *which* deterministic strategy applies without spending
# a classification+dispatch cycle rediscovering it.
_APPLICABLE_PATCHERS = {"SIGN": patch_sign}


def try_memory_repair(
    memory: FailureMemory,
    unit_id: str,
    body: str,
    classification: Classification,
    field_scale: int,
    offending_statement: str,
    work_dir: Path,
    *,
    spec: RunSpec | None = None,
) -> tuple[AttributionResult | None, str | None]:
    """Returns (result, case_id) on a verified memory-hit repair, else (None, None)."""
    spec = spec or RunSpec.default()
    signature = build_signature(classification, field_scale, offending_statement)
    hit = memory.query(signature)
    if hit is None:
        return None, None
    case, similarity = hit

    patcher = _APPLICABLE_PATCHERS.get(case.defect_class)
    if patcher is None:
        return None, None
    try:
        patch = patcher(body)
    except Exception:
        memory.record_hit(case.case_id, verified=False)
        return None, None

    result = verify_unit(unit_id, patch.patched_body, work_dir, spec=spec)
    verified = result.compiled and result.report.divergence_count == 0
    memory.record_hit(case.case_id, verified=verified)
    if verified:
        return result, case.case_id
    return None, None


if __name__ == "__main__":
    import time
    from weaver.classification import DefectClass
    from weaver.agent.seed_memory import STORE_PATH as SEED_STORE_PATH

    # O2 acceptance test: a repair verified in "run one" (the seeding runs
    # in Step O3, which really did call verify_unit + compile) is retrieved
    # and applied here in "run two" against a FRESH instance of the same
    # defect class, with zero model/inference calls in this repair step.
    memory = FailureMemory(SEED_STORE_PATH)
    fresh_body = Path("generated/o3_case_b_body.java").read_text(encoding="utf-8")  # same .negate() defect, fresh instance
    classification = Classification(DefectClass.SIGN, 1.0, {"oracle": "0.10", "candidate": "-0.10"})

    t0 = time.monotonic()
    result, case_id = try_memory_repair(
        memory, "PROCESS-RECORD", fresh_body, classification, 2,
        "MOVE WS-INTEREST TO RL-INTEREST", Path("generated/o2_memory_repair_test"),
    )
    elapsed = time.monotonic() - t0

    print(f"memory hit case: {case_id}")
    print(f"verified: {result is not None and result.report.divergence_count == 0 if result else False}")
    print(f"elapsed: {elapsed:.2f}s, model calls for repair: 0 (deterministic patch applied from memory)")
    assert case_id is not None, "O2 acceptance test FAILED: no memory hit"
    assert result is not None and result.report.divergence_count == 0
    print("O2 acceptance test: PASS")
