"""Delta debugging / input minimization -- migration-framework-spec.md
Section 2.2: "When a test fails due to complex inputs, a delta debugging
algorithm partitions and minimizes the input to isolate the exact, minimal
failure-inducing counterexample. This provides highly focused context for
the LLM to patch the candidate code."

`ddmin` is Zeller's classic delta-debugging algorithm (Zeller & Hildebrandt,
2002), generic over any list of elements and any `is_failing` oracle --
knows nothing about COBOL, records, or fields. `weaver/agent/input_minimize.py`
supplies the COBOL-specific oracle (a real candidate re-run over a reduced
input file) that plugs into this.
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")
IsFailing = Callable[[list[T]], bool]


def ddmin(elements: list[T], is_failing: IsFailing) -> list[T]:
    """Returns a 1-minimal subset of `elements` for which `is_failing`
    still holds -- i.e. no single remaining element can be removed without
    `is_failing` turning false. Assumes `is_failing(elements)` is True
    (the caller's job to establish before calling); returns `elements`
    unchanged if it's already empty or a single element.

    Standard ddmin: alternates between splitting the current failing set
    into `n` roughly-equal chunks and testing (a) each chunk alone and
    (b) each chunk's complement, keeping whichever failing subset is
    found; doubles granularity when neither reduces the set, until every
    single element has been tried for removal.
    """
    if not elements:
        return []

    current = list(elements)
    n = 2
    while len(current) >= 1:
        chunk_size = max(1, len(current) // n)
        chunks = [current[i : i + chunk_size] for i in range(0, len(current), chunk_size)]
        if len(chunks) < 2:
            break

        reduced = False
        for chunk in chunks:
            if len(chunk) < len(current) and is_failing(chunk):
                current = chunk
                n = 2
                reduced = True
                break
        if reduced:
            continue

        for chunk in chunks:
            complement = [e for e in current if e not in chunk]
            if complement and len(complement) < len(current) and is_failing(complement):
                current = complement
                n = max(n - 1, 2)
                reduced = True
                break
        if reduced:
            continue

        if n >= len(current):
            break
        n = min(n * 2, len(current))

    return current


__all__ = ["ddmin", "IsFailing"]
