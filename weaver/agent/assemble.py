"""Substitute paragraph bodies into the scaffold — Step M3 (also used by K3).

Never sends raw text past what's between a paragraph's markers: everything
outside `// PARAGRAPH:<id>:BEGIN` / `:END` is untouched scaffold.
"""

from __future__ import annotations

import re
from pathlib import Path


class UnknownParagraphError(ValueError):
    pass


def _marker_pattern(paragraph_id: str) -> re.Pattern[str]:
    begin = re.escape(f"// PARAGRAPH:{paragraph_id}:BEGIN")
    end = re.escape(f"// PARAGRAPH:{paragraph_id}:END")
    return re.compile(rf"{begin}\n.*?\n(\s*){end}", re.DOTALL)


def assemble(scaffold_source: str, bodies: dict[str, str]) -> str:
    """Replace each paragraph's stub with its supplied body.

    `bodies` maps paragraph id (e.g. "PROCESS-RECORD") to the Java statements
    that should run between the markers. Raises if a requested paragraph id
    has no markers in the scaffold, so a typo fails loudly instead of
    silently leaving the stub in place.
    """
    result = scaffold_source
    for paragraph_id, body in bodies.items():
        pattern = _marker_pattern(paragraph_id)
        if not pattern.search(result):
            raise UnknownParagraphError(f"no markers found for paragraph {paragraph_id!r}")

        def _replace(m: re.Match[str], body: str = body) -> str:
            begin = f"// PARAGRAPH:{paragraph_id}:BEGIN"
            end = f"// PARAGRAPH:{paragraph_id}:END"
            return f"{begin}\n{body}\n{m.group(1)}{end}"

        result = pattern.sub(_replace, result)
    return result


if __name__ == "__main__":
    import sys

    scaffold_path = Path(sys.argv[1])
    body_path = Path(sys.argv[2])
    paragraph_id = sys.argv[3]
    out_path = Path(sys.argv[4])

    assembled = assemble(scaffold_path.read_text(encoding="utf-8"), {paragraph_id: body_path.read_text(encoding="utf-8")})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(assembled, encoding="utf-8")
    print(f"wrote {out_path}")
