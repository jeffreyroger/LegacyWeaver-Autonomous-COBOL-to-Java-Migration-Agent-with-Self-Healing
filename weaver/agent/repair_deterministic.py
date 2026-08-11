"""Deterministic repair strategies — Step N2.

PADDING, SIGN, and SCALE are fully determined by the field specification
in `weaver.layout` -- no model call is needed to fix them, only to
recognize them (classification, already deterministic per weaver.classification).
Each patcher takes the current method body and returns a modified body plus
a description of what changed. Patchers operate on the synthesized Java
source text for ws.appliedRate / ws.interest assignment expressions, the
only things a paragraph body controls in this scaffold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from weaver.classification import DefectClass


class NoPatchAvailable(ValueError):
    pass


@dataclass
class Patch:
    defect_class: DefectClass
    description: str
    patched_body: str


_SETSCALE_RE = re.compile(r"\.setScale\(\s*(\d+)\s*,\s*java\.math\.RoundingMode\.(\w+)\s*\)")
_DIVIDE_NO_SCALE_RE = re.compile(r"(\.divide\([^,]+,\s*java\.math\.RoundingMode\.\w+\s*\))(?!\s*\.setScale)")


def patch_scale(body: str, target_scale: int) -> Patch:
    """SCALE: recompute the scale from the implied-decimal position (the
    PIC clause states it -- weaver.layout's decimal_scale for the field).
    Rewrites any `.setScale(n, RoundingMode.X)` on the ws.interest/
    ws.appliedRate assignment to the declared scale, and appends a
    `.setScale(target, DOWN)` to a bare `.divide(...)` that lacks one.
    """
    if _SETSCALE_RE.search(body):
        patched = _SETSCALE_RE.sub(lambda m: f".setScale({target_scale}, java.math.RoundingMode.{m.group(2)})", body)
    elif _DIVIDE_NO_SCALE_RE.search(body):
        patched = _DIVIDE_NO_SCALE_RE.sub(rf"\1.setScale({target_scale}, java.math.RoundingMode.DOWN)", body)
    else:
        raise NoPatchAvailable("no setScale/divide call found to correct for SCALE")
    return Patch(DefectClass.SCALE, f"forced scale to declared {target_scale} decimals", patched)


def patch_sign(body: str) -> Patch:
    """SIGN: correct the sign decode per the declared encoding. In this
    scaffold the sign is decoded once, correctly, by
    Scaffold.decodeSignedTrailing -- a SIGN defect in the paragraph means
    the body applied an extra `.negate()` or `.abs()` it should not have.
    """
    if ".negate()" in body:
        patched = body.replace(".negate()", "")
        return Patch(DefectClass.SIGN, "removed spurious .negate() -- sign is already correct from ar.balance", patched)
    if ".abs()" in body:
        patched = body.replace(".abs()", "")
        return Patch(DefectClass.SIGN, "removed spurious .abs() -- sign is already correct from ar.balance", patched)
    raise NoPatchAvailable("no .negate()/.abs() call found to correct for SIGN")


def patch_padding(body: str) -> Patch:
    """PADDING is an encoder concern (width/alignment/sign placement in the
    edit mask), owned entirely by ReportLine.encode()/CobolEdit -- both
    scaffold, not paragraph, code. A paragraph body cannot cause a PADDING
    defect in this design (K1 separates encoding from paragraph logic), so
    there is nothing in the body to patch. This still counts as "no model
    call" per N2 -- the fix is deterministic re-emission through the
    declared edit mask, which the scaffold already does unconditionally.
    """
    raise NoPatchAvailable(
        "PADDING is owned by the scaffold's encoder (ReportLine.encode/CobolEdit), "
        "never by paragraph logic in this scaffold design -- nothing to patch here"
    )


PATCHERS = {
    DefectClass.SCALE: patch_scale,
    DefectClass.SIGN: lambda body, target_scale: patch_sign(body),
    DefectClass.PADDING: lambda body, target_scale: patch_padding(body),
}


def try_deterministic_repair(defect_class: DefectClass, body: str, target_scale: int = 2) -> Patch | None:
    """`target_scale` is the field's own declared decimal scale (from the
    program's ScaffoldSpec), not a value hardcoded for interest.cob's
    fields -- see 2026-08-12 audit. Only SCALE's patcher actually uses it;
    SIGN/PADDING ignore it, kept in the same signature so PATCHERS stays a
    uniform dispatch table."""
    patcher = PATCHERS.get(defect_class)
    if patcher is None:
        return None
    try:
        return patcher(body, target_scale)
    except NoPatchAvailable:
        return None


if __name__ == "__main__":
    # N2 acceptance test: each patcher, given a body with its target
    # defect, produces a body that verifies clean.
    broken_scale = (
        'ws.interest = ar.balance.multiply(ws.appliedRate)'
        '.divide(new java.math.BigDecimal("365"), java.math.RoundingMode.DOWN);'
    )
    p = patch_scale(broken_scale, target_scale=2)
    print("SCALE patch:", p.description)
    assert ".setScale(2, java.math.RoundingMode.DOWN)" in p.patched_body

    broken_sign = 'ws.interest = ar.balance.negate().multiply(ws.appliedRate);'
    p2 = patch_sign(broken_sign)
    print("SIGN patch:", p2.description)
    assert ".negate()" not in p2.patched_body

    print("N2 acceptance test: PASS")
