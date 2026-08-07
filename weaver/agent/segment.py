"""Segment the PROCEDURE DIVISION into paragraphs — Step L1.

A paragraph header is a non-comment line whose label starts in Area A
(COBOL fixed-format columns 8-11, i.e. 0-based columns 7-10) and is
terminated by a period. Each paragraph runs from its header line to the
line before the next header (or end of PROCEDURE DIVISION).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_AREA_A_START = 7  # 0-based column 8
_AREA_A_END = 11    # 0-based column 11 inclusive -> slice end 11 (cols 8-11)

_HEADER_RE = re.compile(r"^([A-Z0-9][A-Z0-9-]*)\.\s*$")


@dataclass(frozen=True)
class Paragraph:
    identifier: str
    start_line: int  # 1-based, inclusive, header line
    end_line: int     # 1-based, inclusive, last line of paragraph body
    source: str       # verbatim text, header through last body line


def _is_comment(line: str) -> bool:
    return len(line) > 6 and line[6] == "*"


def _procedure_division_start(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if "PROCEDURE DIVISION" in line.upper():
            return i
    raise ValueError("no PROCEDURE DIVISION found")


def segment(source: str) -> list[Paragraph]:
    lines = source.splitlines()
    proc_start = _procedure_division_start(lines)

    headers: list[tuple[int, str]] = []  # (0-based line index, identifier)
    for i in range(proc_start + 1, len(lines)):
        line = lines[i]
        if _is_comment(line) or not line.strip():
            continue
        area_a_and_beyond = line[_AREA_A_START:].rstrip()
        # A header's label starts exactly at Area A (col 8, 0-based idx 7)
        # and the preceding columns (margin + Area A start) must be blank.
        if line[:_AREA_A_START].strip():
            continue
        m = _HEADER_RE.match(area_a_and_beyond)
        if m:
            headers.append((i, m.group(1)))

    paragraphs = []
    for idx, (line_idx, identifier) in enumerate(headers):
        start = line_idx
        end = (headers[idx + 1][0] - 1) if idx + 1 < len(headers) else len(lines) - 1
        # Trim trailing blank lines from the body.
        while end > start and not lines[end].strip():
            end -= 1
        text = "\n".join(lines[start:end + 1])
        paragraphs.append(Paragraph(identifier, start + 1, end + 1, text))

    return paragraphs


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1]).read_text()
    for p in segment(src):
        print(f"{p.identifier}: lines {p.start_line}-{p.end_line}")
