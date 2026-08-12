"""Symptom signature — Step O1.

Composed from structural properties only -- never specific values or field
names, or nothing will ever match across programs (the plan's stated
common failure). The four components:
  - value kind (numeric or alphanumeric)
  - delta magnitude bucket (sub-ULP, power-of-ten, sign-inversion, other)
  - field scale
  - the normalised COBOL operation -- offending statement with identifiers
    replaced by placeholders and whitespace collapsed
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from zuse.classification import Classification, DefectClass

_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9-]*\b")
_NUMBER_RE = re.compile(r"\b\d+(\.\d+)?\b")
_COBOL_KEYWORDS = {
    "COMPUTE", "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "TO", "FROM",
    "BY", "GIVING", "IF", "ELSE", "END-IF", "ROUNDED", "ZERO", "TRUE", "FALSE",
}


@dataclass(frozen=True)
class SymptomSignature:
    value_kind: str          # "numeric" | "alphanumeric"
    delta_bucket: str        # "sub-ulp" | "power-of-ten" | "sign-inversion" | "other" | "n/a"
    field_scale: int
    normalized_operation: str

    def as_text(self) -> str:
        """Flattened form fed to the embedding model (O2).

        Phrased as prose rather than key=value pairs: nomic-embed-text is a
        semantic text embedding model, and a shared "value_kind=... delta_
        bucket=..." prefix on every signature dominated cosine similarity
        with boilerplate rather than the distinguishing content (discovered
        during O1's own acceptance check -- a PADDING/TRUNCATION pair
        scored 0.90, not "well below" a same-class pair's 1.0). Prose
        puts the distinguishing words in different sentence positions
        instead of behind an identical label every time.
        """
        return (
            f"A {self.delta_bucket} defect on a {self.value_kind} field "
            f"at scale {self.field_scale}, arising from: {self.normalized_operation}"
        )


def normalize_operation(cobol_statement: str) -> str:
    """Replace identifiers with <ID>, numeric literals with <NUM>, collapse
    whitespace. COBOL keywords are preserved -- they carry the operation's
    shape (COMPUTE vs MOVE vs ADD ... TO ...), which is exactly what should
    match across programs with different field names.
    """
    collapsed = " ".join(cobol_statement.split())

    def _sub_identifier(m: re.Match[str]) -> str:
        word = m.group(0)
        return word if word in _COBOL_KEYWORDS else "<ID>"

    normalized = _IDENTIFIER_RE.sub(_sub_identifier, collapsed)
    normalized = _NUMBER_RE.sub("<NUM>", normalized)
    return normalized


def _delta_bucket(classification: Classification, field_scale: int) -> str:
    if classification.defect_class == DefectClass.SIGN:
        return "sign-inversion"
    if classification.defect_class == DefectClass.SCALE:
        return "power-of-ten"
    if classification.defect_class == DefectClass.TRUNCATION:
        return "sub-ulp"
    delta_str = classification.evidence.get("delta")
    if delta_str is not None:
        try:
            ulp = Decimal(1).scaleb(-field_scale)
            if abs(Decimal(delta_str)) <= ulp:
                return "sub-ulp"
        except Exception:
            pass
    return "other"


def build_signature(
    classification: Classification,
    field_scale: int,
    offending_statement: str,
    numeric_field: bool = True,
) -> SymptomSignature:
    return SymptomSignature(
        value_kind="numeric" if numeric_field else "alphanumeric",
        delta_bucket=_delta_bucket(classification, field_scale),
        field_scale=field_scale,
        normalized_operation=normalize_operation(offending_statement),
    )


if __name__ == "__main__":
    from zuse.classification import Classification, DefectClass

    interest_stmt = "COMPUTE WS-INTEREST = AR-BALANCE * WS-APPLIED-RATE / 365"
    fee_stmt = "COMPUTE WS-FEE = FC-AMOUNT * FC-RATE / 100"
    padding_stmt = "MOVE WS-INTEREST TO RL-INTEREST"

    truncation = Classification(DefectClass.TRUNCATION, 0.9, {"delta": "0.01"})
    padding = Classification(DefectClass.PADDING, 1.0, {})

    sig_interest = build_signature(truncation, 2, interest_stmt)
    sig_fee = build_signature(truncation, 2, fee_stmt)
    sig_padding = build_signature(padding, 2, padding_stmt)

    print("interest:", sig_interest.as_text())
    print("fee:     ", sig_fee.as_text())
    print("padding: ", sig_padding.as_text())
    print()
    print("interest normalized op == fee normalized op:",
          sig_interest.normalized_operation == sig_fee.normalized_operation)
    assert sig_interest.normalized_operation == "COMPUTE <ID> = <ID> * <ID> / <NUM>"
    assert sig_fee.normalized_operation == "COMPUTE <ID> = <ID> * <ID> / <NUM>"
    assert sig_interest.delta_bucket == sig_fee.delta_bucket == "sub-ulp"
    assert sig_padding.delta_bucket != sig_interest.delta_bucket
    print("O1 structural check: PASS (exact match on structure; O2 verifies embedding similarity)")
