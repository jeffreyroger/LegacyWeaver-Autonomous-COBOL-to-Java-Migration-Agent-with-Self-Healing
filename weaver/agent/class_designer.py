"""Application-wide Class Designer dedup -- Phase AA2
(migration-framework-spec.md Section 3.2's stronger claim: "establishes
shared class structures to avoid redundant class generations across
modular translations").

`weaver/agent/scaffold.py`'s per-program `generate()` is untouched
(hardened, byte-identical-output contract, CLAUDE.md rule 6/7) -- this is
a separate, additive scan that looks ACROSS every program in a directory
and reports which of their record layouts are structurally identical, so
a shared Java class can be generated once instead of once per program
(`weaver/agent/shared_class_codegen.py`).

"Structurally identical" is exact, not fuzzy: two `weaver.layout.Field`
tuples dedup only when every field's name, offset, width, numeric-ness,
decimal scale, sign, trailing-separate-sign flag, redefines target, and
edit style match, in the same order (`layout_signature`). This is most
often true when two independently-written programs `COPY` the same
copybook (this repo's `feecalc.cob`/`billfee.cob` fixture pair, sharing
`FEE-REC.cpy`, is exactly that real-world case) -- never a heuristic
"looks similar" match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from weaver.cobol.frontend import UnsupportedProgramError, load_program, to_scaffold_spec
from weaver.layout import Field

_LAYOUT_KINDS = ("input_layout", "report_layout", "totals_layout")


def layout_signature(layout: tuple[Field, ...]) -> tuple:
    """A hashable, exact identity for a layout's shape. Two layouts with
    the same signature are byte-for-byte structurally identical."""
    return tuple(
        (f.name, f.offset, f.width, f.numeric, f.decimal_scale, f.signed,
         f.trailing_separate_sign, f.redefines, f.edit_style)
        for f in layout
    )


@dataclass(frozen=True)
class LayoutUse:
    program_id: str
    layout_kind: str  # "input_layout" | "report_layout" | "totals_layout"


@dataclass(frozen=True)
class SharedLayout:
    class_name: str
    layout: tuple[Field, ...]
    used_by: tuple[LayoutUse, ...]

    @property
    def layout_kind(self) -> str:
        """Every use of one `SharedLayout` shares the same `layout_kind`
        by construction -- dedup groups by exact field-tuple signature
        (name/offset/width/... in order), and `weaver.cobol.frontend`
        never produces the same field-name sequence for both an
        input-record layout and a report/totals-line layout (their field
        naming conventions -- AR-*/FR-* vs RL-*/TL-* -- never collide in
        this harness's fixtures). Asserted, not just assumed."""
        kinds = {u.layout_kind for u in self.used_by}
        assert len(kinds) == 1, f"a shared layout must not mix layout kinds, got {kinds}"
        return next(iter(kinds))


@dataclass(frozen=True)
class DedupPlan:
    shared: tuple[SharedLayout, ...]
    skipped: tuple[str, ...]  # source paths that could not be parsed as a file-based program


def _class_name_for(layout: tuple[Field, ...]) -> str:
    """Deterministic, readable class name derived from the layout's own
    first non-redefined field name -- e.g. FEE-REC's first field FR-ID ->
    "FrRecord". Never a hash: two runs over the same source always name
    the shared class identically, and the name stays legible in generated
    output."""
    base = next((f.name for f in layout if f.redefines is None), layout[0].name)
    prefix = base.split("-")[0] if "-" in base else base
    return "".join(p.capitalize() for p in re.split(r"[-_]", prefix) if p) + "Record"


def discover_shared_layouts(cobol_dir: Path, copybook_dir: Path | None = None) -> DedupPlan:
    """Scans every `*.cob` file under `cobol_dir` (recursively) with the
    real, unmodified `weaver.cobol.frontend.load_program` -- a source that
    isn't a file-based program in that module's narrow sense (a
    subprogram, an unsupported shape) raises `UnsupportedProgramError`,
    which is caught and recorded in `DedupPlan.skipped` rather than
    aborting the whole scan or guessing at its shape.
    """
    signature_uses: dict[tuple, list[LayoutUse]] = {}
    signature_layout: dict[tuple, tuple[Field, ...]] = {}
    skipped: list[str] = []

    for cobol_file in sorted(cobol_dir.rglob("*.cob")):
        # Prefer the caller's copybook_dir; fall back to a sibling
        # "copybooks/" directory next to the source file itself (the
        # convention every existing fixture under fixtures/cobol*/ uses) --
        # a scan across many programs can't assume they all share one
        # copybook location.
        candidate_dirs = [copybook_dir] if copybook_dir is not None else []
        candidate_dirs.append(cobol_file.parent / "copybooks")

        model = None
        for candidate in candidate_dirs:
            try:
                model = load_program(cobol_file, copybook_dir=candidate)
                break
            except (UnsupportedProgramError, FileNotFoundError):
                continue
        if model is None:
            skipped.append(str(cobol_file))
            continue
        try:
            spec = to_scaffold_spec(model)
        except UnsupportedProgramError:
            skipped.append(str(cobol_file))
            continue

        for kind in _LAYOUT_KINDS:
            layout = getattr(spec, kind)
            if not layout:
                continue
            sig = layout_signature(layout)
            signature_uses.setdefault(sig, []).append(LayoutUse(model.program_id, kind))
            signature_layout.setdefault(sig, layout)

    eligible = [
        (sig, uses) for sig, uses in signature_uses.items()
        if len({u.program_id for u in uses}) >= 2  # dedup only crosses programs, never within one
    ]
    # Sort by first use, not the raw signature tuple -- a signature can mix
    # None/str in the same field position across different shapes, which
    # isn't safely orderable; (program_id, layout_kind) always is.
    eligible.sort(key=lambda item: (item[1][0].program_id, item[1][0].layout_kind))

    used_names: dict[str, int] = {}
    shared = []
    for sig, uses in eligible:
        base_name = _class_name_for(signature_layout[sig])
        count = used_names.get(base_name, 0)
        used_names[base_name] = count + 1
        # Two DIFFERENT shapes can derive the same base name (e.g. two
        # distinct totals-line shapes both starting with TL-); disambiguate
        # deterministically rather than silently colliding class names.
        class_name = base_name if count == 0 else f"{base_name}{count + 1}"
        shared.append(SharedLayout(class_name=class_name, layout=signature_layout[sig], used_by=tuple(uses)))
    shared = tuple(shared)
    return DedupPlan(shared=shared, skipped=tuple(skipped))


__all__ = ["DedupPlan", "LayoutUse", "SharedLayout", "discover_shared_layouts", "layout_signature"]
