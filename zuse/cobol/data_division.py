"""DATA DIVISION reader — Step U2.

Builds the level hierarchy, computes byte offsets, and flattens it into the
`zuse.layout.Field` tables the harness compares and the scaffold decodes.

Flattening rule (this is the part with judgement in it, so it is stated
rather than implied). A layout table records the byte ranges the harness
actually slices:

  * elementary items are emitted;
  * a group is emitted only when some other item REDEFINES it — the group
    owns the raw bytes an overlay re-slices, so it must exist as a field
    (this is `AR-FLAGS`), and its own children are then redundant;
  * the redefining group itself is not emitted; its elementary children are,
    each carrying `redefines=<target group>` so the scaffold generator can
    compute their offset relative to the bytes they overlay;
  * FILLER is unnamed and never emitted.

Applied to `ACCOUNT-REC.cpy` this reproduces `zuse/layout.py:INPUT_LAYOUT`
field for field, which is Step U2's acceptance test.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from zuse.agent.scaffold import ConditionName
from zuse.cobol.naming import java_condition_name
from zuse.cobol.pic import Picture, UnsupportedPictureError, parse as parse_picture
from zuse.cobol.source import Statement
from zuse.layout import Field

# USAGE clauses that change stored width. Phase U models DISPLAY only.
_UNSUPPORTED_USAGE = (
    "COMP",
    "COMPUTATIONAL",
    "COMP-1",
    "COMPUTATIONAL-1",
    "COMP-2",
    "COMPUTATIONAL-2",
    "COMP-3",
    "COMPUTATIONAL-3",
    "COMP-4",
    "COMPUTATIONAL-4",
    "COMP-5",
    "COMPUTATIONAL-5",
    "BINARY",
    "PACKED-DECIMAL",
    "INDEX",
)

_CONDITION_LEVEL = 88
_FILLER = "FILLER"


class UnsupportedDataItemError(ValueError):
    """A data description outside Phase U's declared scope."""


@dataclass
class DataItem:
    level: int
    name: str
    picture: Picture | None = None
    redefines: str | None = None
    sign_separate: bool = False
    conditions: list[tuple[str, str]] = dc_field(default_factory=list)
    children: list[DataItem] = dc_field(default_factory=list)
    offset: int = 0
    width: int = 0


def _literal(token: str) -> str:
    return token.strip().strip("\"'")


def _parse_description(text: str) -> DataItem | tuple[str, str]:
    """One data-description statement -> a DataItem, or an 88-level pair."""
    tokens = text.split()
    level = int(tokens[0])
    name = tokens[1] if len(tokens) > 1 else _FILLER

    if level == _CONDITION_LEVEL:
        if "VALUE" not in [t.upper() for t in tokens]:
            raise UnsupportedDataItemError(f"88-level without VALUE: {text!r}")
        idx = [t.upper() for t in tokens].index("VALUE")
        rest = tokens[idx + 1 :]
        if rest and rest[0].upper() == "IS":
            rest = rest[1:]
        if len(rest) != 1:
            raise UnsupportedDataItemError(
                f"only single-valued 88-levels are modelled: {text!r}"
            )
        return name, _literal(rest[0])

    item = DataItem(level=level, name=name)
    upper = [t.upper() for t in tokens]

    for keyword in ("OCCURS", "RENAMES"):
        if keyword in upper:
            raise UnsupportedDataItemError(
                f"{keyword} is outside Phase U's scope: {text!r}"
            )
    for usage in upper:
        if usage in _UNSUPPORTED_USAGE:
            raise UnsupportedDataItemError(
                f"USAGE {usage} changes stored width and is outside Phase U's scope "
                f"(DISPLAY only): {text!r}"
            )

    if "REDEFINES" in upper:
        item.redefines = tokens[upper.index("REDEFINES") + 1]

    # SIGN [IS] {LEADING|TRAILING} [SEPARATE [CHARACTER]]
    if "SEPARATE" in upper:
        if "LEADING" in upper:
            raise UnsupportedDataItemError(
                f"SIGN IS LEADING SEPARATE is not modelled (trailing only): {text!r}"
            )
        item.sign_separate = True

    pic_index = next((i for i, t in enumerate(upper) if t in ("PIC", "PICTURE")), None)
    if pic_index is not None:
        pic_tokens = tokens[pic_index + 1 :]
        if pic_tokens and pic_tokens[0].upper() == "IS":
            pic_tokens = pic_tokens[1:]
        if not pic_tokens:
            raise UnsupportedDataItemError(f"PIC with no picture string: {text!r}")
        try:
            item.picture = parse_picture(
                pic_tokens[0], sign_separate=item.sign_separate
            )
        except UnsupportedPictureError as exc:
            raise UnsupportedDataItemError(f"{name}: {exc}") from exc

    return item


def parse_items(stmts: list[Statement]) -> list[DataItem]:
    """Build the 01-level forest from a run of data-description statements."""
    roots: list[DataItem] = []
    stack: list[DataItem] = []

    for stmt in stmts:
        parsed = _parse_description(stmt.text)
        if isinstance(parsed, tuple):
            if not stack:
                raise UnsupportedDataItemError(
                    f"88-level with no parent: {stmt.text!r}"
                )
            stack[-1].conditions.append(parsed)
            continue

        while stack and stack[-1].level >= parsed.level:
            stack.pop()
        if stack:
            stack[-1].children.append(parsed)
        else:
            roots.append(parsed)
        stack.append(parsed)

    for root in roots:
        _assign_offsets(root, 0)
    return roots


def _assign_offsets(item: DataItem, start: int) -> None:
    item.offset = start
    if item.picture is not None:
        item.width = item.picture.width
        return

    by_name = {c.name: c for c in item.children}
    cursor = start
    for child in item.children:
        if child.redefines is not None:
            target = by_name.get(child.redefines)
            if target is None:
                raise UnsupportedDataItemError(
                    f"{child.name} REDEFINES {child.redefines}, which is not a sibling"
                )
            # An overlay starts where its target starts and consumes no new
            # bytes -- the cursor deliberately does not advance.
            _assign_offsets(child, target.offset)
        else:
            _assign_offsets(child, cursor)
            cursor += child.width
    item.width = cursor - start


def _to_field(item: DataItem, redefines: str | None) -> Field:
    pic = item.picture
    if pic is None:  # a group emitted because it is a REDEFINES target
        return Field(item.name, offset=item.offset, width=item.width, numeric=False)
    return Field(
        item.name,
        offset=item.offset,
        width=item.width,
        numeric=pic.numeric,
        decimal_scale=pic.decimal_scale,
        signed=pic.signed,
        trailing_separate_sign=item.sign_separate,
        redefines=redefines,
    )


def flatten(root: DataItem) -> tuple[Field, ...]:
    """Flatten one 01-level into a comparison/scaffold field table."""
    out: list[Field] = []

    def walk(item: DataItem, siblings: list[DataItem], owner: str | None) -> None:
        if item.name.upper() == _FILLER:
            return
        if item.picture is not None:
            out.append(_to_field(item, owner or item.redefines))
            return
        if any(s.redefines == item.name for s in siblings):
            # This group's raw bytes are re-sliced by an overlay, so the group
            # itself is the field; its children would double-count them.
            out.append(_to_field(item, owner))
            return
        for child in item.children:
            walk(child, item.children, item.redefines or owner)

    walk(root, [root], None)
    return tuple(out)


def condition_names(root: DataItem) -> tuple[ConditionName, ...]:
    """88-levels beneath `root`, in declaration order."""
    out: list[ConditionName] = []

    def walk(item: DataItem) -> None:
        for name, value in item.conditions:
            out.append(ConditionName(java_condition_name(name), item.name, value))
        for child in item.children:
            walk(child)

    walk(root)
    return tuple(out)


def elementary_items(root: DataItem) -> tuple[DataItem, ...]:
    """Every named elementary item beneath `root`, in declaration order."""
    out: list[DataItem] = []

    def walk(item: DataItem) -> None:
        if item.name.upper() == _FILLER:
            return
        if item.picture is not None:
            out.append(item)
            return
        for child in item.children:
            walk(child)

    walk(root)
    return tuple(out)
