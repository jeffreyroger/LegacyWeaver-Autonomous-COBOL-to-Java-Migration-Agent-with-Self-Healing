"""COBOL identifier -> Java identifier rules — Step U1.

One definition, shared by the scaffold generator and the frontend, so a
name derived by the parser and a name written by the generator can never
drift apart.
"""

from __future__ import annotations


def _segments(cobol_name: str) -> list[str]:
    """AR-BALANCE -> ['BALANCE'] (the record prefix is dropped)."""
    parts = cobol_name.split("-")[1:]
    return parts or cobol_name.split("-")


def java_field_name(cobol_name: str) -> str:
    """AR-BALANCE -> balance, RL-INTEREST -> interest, TL-TOTAL -> total."""
    head, *rest = _segments(cobol_name)
    return head.lower() + "".join(p.capitalize() for p in rest)


def java_method_name(paragraph_id: str) -> str:
    """PROCESS-RECORD -> processRecord, COMPUTE-FEE -> computeFee.

    Unlike field names no prefix segment is dropped: a paragraph label is a
    whole name, not a prefixed record member.
    """
    head, *rest = paragraph_id.split("-")
    return head.lower() + "".join(p.capitalize() for p in rest)


def java_condition_name(condition_name: str) -> str:
    """AR-PREMIUM -> isPremium, AR-IS-DORMANT -> isDormant.

    The record prefix is dropped as for a field; the result is then forced
    into predicate form. A COBOL 88-level often already spells the
    predicate ("AR-IS-DORMANT"), in which case `is` is not doubled.
    """
    name = java_field_name(condition_name)
    if name.startswith("is") and len(name) > 2 and name[2].isupper():
        return name
    return "is" + name[0].upper() + name[1:]
