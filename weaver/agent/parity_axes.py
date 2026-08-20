"""Two new deterministic parity axes -- migration-framework-spec.md
Section 2.2's "Parity Gate": legacy outputs are verified against Java
target execution outcomes across three axes. `weaver/comparison.py`
already is (and remains, untouched -- CLAUDE.md rule 3) the harness's
one Terminal State axis. This module adds the other two, kept in a
separate file precisely so nothing here can be mistaken for a change to
the frozen byte-for-byte comparison contract:

1. **Paragraphs Hit**: set-wise equivalence of executed control paths,
   read from `PARA:<name>` trace lines both the oracle (rewritten COBOL,
   `weaver/agent/mock_generator.py`) and the candidate emit on stdout.
2. **External Stub Log**: chronologically ordered sequence of external
   middleware calls, read from `STUB:<signature>` trace lines the same
   way.

Both axes are pure functions over two lists of trace lines -- they know
nothing about how the lines were produced (real cobc run vs real java
run), so they are equally usable by the subprogram harness this phase
wires them into and by anything else that emits the same two trace-line
conventions later.
"""

from __future__ import annotations

from dataclasses import dataclass

_PARA_PREFIX = "PARA:"
_STUB_PREFIX = "STUB:"


@dataclass(frozen=True)
class ParagraphsHitDivergence:
    only_in_oracle: tuple[str, ...]
    only_in_candidate: tuple[str, ...]


@dataclass(frozen=True)
class StubLogDivergence:
    index: int
    oracle_call: str | None
    candidate_call: str | None


def extract_trace(prefix: str, lines: list[str]) -> list[str]:
    return [line[len(prefix):].strip() for line in lines if line.strip().startswith(prefix)]

def paragraphs_hit(lines: list[str]) -> list[str]:
    return extract_trace(_PARA_PREFIX, lines)


def stub_log(lines: list[str]) -> list[str]:
    return extract_trace(_STUB_PREFIX, lines)


def compare_paragraphs_hit(oracle_lines: list[str], candidate_lines: list[str]
                            ) -> ParagraphsHitDivergence | None:
    oracle_set = set(paragraphs_hit(oracle_lines))
    candidate_set = set(paragraphs_hit(candidate_lines))
    if oracle_set == candidate_set:
        return None
    return ParagraphsHitDivergence(
        only_in_oracle=tuple(sorted(oracle_set - candidate_set)),
        only_in_candidate=tuple(sorted(candidate_set - oracle_set)),
    )


def compare_stub_log(oracle_lines: list[str], candidate_lines: list[str]) -> StubLogDivergence | None:
    oracle_calls = stub_log(oracle_lines)
    candidate_calls = stub_log(candidate_lines)
    for i in range(max(len(oracle_calls), len(candidate_calls))):
        o = oracle_calls[i] if i < len(oracle_calls) else None
        c = candidate_calls[i] if i < len(candidate_calls) else None
        if o != c:
            return StubLogDivergence(index=i, oracle_call=o, candidate_call=c)
    return None


__all__ = [
    "ParagraphsHitDivergence", "StubLogDivergence",
    "paragraphs_hit", "stub_log", "compare_paragraphs_hit", "compare_stub_log",
]
