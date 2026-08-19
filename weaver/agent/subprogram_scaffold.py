"""Subprogram scaffold generator — Phase X2
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md).

Generates a standalone Java class for one `SubprogramModel` (Phase X1):
one `public static java.math.BigDecimal <method>(java.math.BigDecimal
<input>)`, body between the same `// PARAGRAPH:<id>:BEGIN`/`:END` markers
`weaver/agent/scaffold.py` already uses -- `weaver/agent/assemble.py`'s
existing `assemble()` works on this output unchanged, no new substitution
mechanism.

Naming follows `weaver/cobol/naming.py`'s existing rules (same rules
`frontend.py`/`scaffold.py` already use) so a subprogram-generated name and
a file-based-generated name can never drift apart, per that module's own
stated purpose.
"""

from __future__ import annotations

from weaver.cobol.naming import java_field_name, java_method_name
from weaver.cobol.subprogram import SubprogramModel


def _class_name(program_id: str) -> str:
    """LEAF-A -> LeafA, LEAF-B -> LeafB."""
    return "".join(part.capitalize() for part in program_id.split("-"))


def generate(model: SubprogramModel, method_body: str | None = None) -> str:
    """The standalone Java class for `model`.

    `method_body` is the Java statements to place between the paragraph's
    markers (e.g. a synthesized/verified body). `None` (the default) emits
    the same unsynthesized stub `scaffold.py`'s `_paragraph_stub` emits for
    a file-based unit -- an explicit `throw`, never silently returning a
    placeholder value that would look like a real answer.
    """
    class_name = _class_name(model.program_id)
    method_name = java_method_name(model.paragraph_id)
    input_name = java_field_name(model.input_param.name)

    if method_body is None:
        body = (
            f"        // PARAGRAPH:{model.paragraph_id}:BEGIN\n"
            f'        throw new UnsupportedOperationException("{model.paragraph_id} not yet synthesized");\n'
            f"        // PARAGRAPH:{model.paragraph_id}:END"
        )
    else:
        body = (
            f"        // PARAGRAPH:{model.paragraph_id}:BEGIN\n"
            f"{method_body}\n"
            f"        // PARAGRAPH:{model.paragraph_id}:END"
        )

    return f"""\
public final class {class_name} {{

    public static java.math.BigDecimal {method_name}(java.math.BigDecimal {input_name}) {{
{body}
    }}
}}
"""


__all__ = ["generate"]
