"""Fixed-format COBOL source handling — Step U2 support.

Comment stripping and statement assembly. A DATA DIVISION statement can
span lines (`PIC S9(9)V99` / `SIGN IS TRAILING SEPARATE.`), so the unit of
parsing is the statement, not the line.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_INDICATOR_COLUMN = 6  # 0-based; '*' here marks a comment line


@dataclass(frozen=True)
class Statement:
    text: str  # whitespace-normalised, terminating period removed
    line_number: int  # 1-based line the statement starts on


def is_comment(line: str) -> bool:
    return len(line) > _INDICATOR_COLUMN and line[_INDICATOR_COLUMN] in "*/"


def _terminates(line: str) -> bool:
    """True if the line ends a statement.

    The terminator is a trailing period outside a quoted literal. Checking
    only the trailing period (rather than splitting on every '.') is what
    keeps `PIC -(9)9.99.` intact — its first two periods are part of the
    picture, its last is the terminator.
    """
    stripped = line.rstrip()
    if not stripped.endswith("."):
        return False
    in_quote: str | None = None
    for ch in stripped:
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
        elif ch in "\"'":
            in_quote = ch
    return in_quote is None


def statements(source: str) -> list[Statement]:
    """Split source into period-terminated statements, comments removed."""
    out: list[Statement] = []
    pending: list[str] = []
    start_line = 0

    for lineno, raw in enumerate(source.splitlines(), start=1):
        if is_comment(raw) or not raw.strip():
            continue
        # Drop the sequence-number area (cols 1-6); the indicator column is
        # blank on any line that reached here.
        text = (
            raw[_INDICATOR_COLUMN:].strip()
            if len(raw) > _INDICATOR_COLUMN
            else raw.strip()
        )
        if not text:
            continue
        if not pending:
            start_line = lineno
        terminated = _terminates(raw)
        if terminated:
            text = text.rstrip()[:-1].rstrip()
        pending.append(text)
        if terminated:
            joined = " ".join(part for part in pending if part)
            out.append(Statement(" ".join(joined.split()), start_line))
            pending = []

    if pending:
        joined = " ".join(pending)
        out.append(Statement(" ".join(joined.split()), start_line))
    return out


def expand_copy(source: str, copybook_dir: Path | None) -> str:
    """Splice `COPY "name"` directives inline.

    Only the bare form is supported; `COPY ... REPLACING` changes the text
    being copied and is out of Phase U's declared scope.
    """
    lines = source.splitlines()
    out: list[str] = []
    for raw in lines:
        if is_comment(raw):
            out.append(raw)
            continue
        stripped = raw.strip().rstrip(".").strip()
        upper = stripped.upper()
        if not upper.startswith("COPY "):
            out.append(raw)
            continue
        if "REPLACING" in upper:
            raise NotImplementedError(
                f"COPY ... REPLACING is outside Phase U's scope: {stripped!r}"
            )
        name = stripped[5:].strip().strip("\"'")
        if copybook_dir is None:
            raise FileNotFoundError(
                f"{stripped!r} requires a copybook directory but none was supplied "
                "(pass --copybook / RunSpec.copybook_dir)"
            )
        path = copybook_dir / name
        if not path.exists():
            raise FileNotFoundError(f"copybook {name!r} not found in {copybook_dir}")
        out.extend(expand_copy(path.read_text(), copybook_dir).splitlines())
    return "\n".join(out)
