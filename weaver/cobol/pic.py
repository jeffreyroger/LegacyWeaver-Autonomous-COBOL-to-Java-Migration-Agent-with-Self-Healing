"""PICTURE clause parser — Step U1.

Turns a PIC string into the `(width, decimal_scale, signed, numeric)` tuple
the rest of the harness describes fields with. Two categories:

  storage picture   X(16), S9(9)V99, 9V9(5)  -- width is *stored bytes*
  numeric-edited    -(9)9.99                 -- width is *print positions*

The distinction matters and is the reason hand-derivation went wrong once:
`V` is an implied decimal point occupying zero bytes, while `.` in an edit
mask occupies one print position, and a floating sign `-(9)` occupies nine.
`PIC -(9)9.99` is therefore 13 print positions, not 12 — computed here
rather than counted by eye (see CLAUDE.md rule 6, report-line correction).

Anything outside the supported vocabulary raises rather than guessing: a
silently misparsed picture produces a plausible-looking layout that
invalidates every downstream byte comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Storage symbols, then numeric-edit symbols. Deliberately narrow.
_STORAGE_SYMBOLS = set("XA9SV")
_EDIT_SYMBOLS = set("9-+.,Z*")
_SUPPORTED = _STORAGE_SYMBOLS | _EDIT_SYMBOLS

_TOKEN_RE = re.compile(r"([A-Z0-9\-+.,*$/])(?:\((\d+)\))?")


class UnsupportedPictureError(ValueError):
    """A PICTURE clause outside the frontend's declared scope (Phase U).

    Raised, never worked around: COMP/COMP-3 packed decimal, DBCS, CR/DB
    credit symbols, insertion characters (B, 0, /) and currency symbols all
    change byte width in ways this parser does not model.
    """


@dataclass(frozen=True)
class Picture:
    source: str
    width: int  # stored bytes, or print positions for an edit mask
    numeric: bool
    decimal_scale: int
    signed: bool
    edited: bool


def _expand(pic_text: str) -> str:
    """'-(9)9.99' -> '---------9.99'; 'S9(9)V99' -> 'S999999999V99'."""
    text = pic_text.strip().upper()
    if not text:
        raise UnsupportedPictureError("empty PICTURE clause")

    out: list[str] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise UnsupportedPictureError(
                f"PIC {pic_text!r}: unparseable at offset {pos} ({text[pos]!r})"
            )
        symbol, count = m.group(1), m.group(2)
        if symbol not in _SUPPORTED:
            raise UnsupportedPictureError(
                f"PIC {pic_text!r}: symbol {symbol!r} is outside Phase U's supported "
                f"vocabulary ({''.join(sorted(_SUPPORTED))})"
            )
        out.append(symbol * (int(count) if count else 1))
        pos = m.end()
    return "".join(out)


def parse(pic_text: str, *, sign_separate: bool = False) -> Picture:
    """Parse one PICTURE clause.

    `sign_separate` comes from the item's `SIGN IS {LEADING|TRAILING}
    SEPARATE` clause, which lives outside the picture string but changes its
    stored width by one byte.
    """
    chars = _expand(pic_text)

    is_edited = any(c in "-+.,Z*" for c in chars)
    if is_edited:
        if sign_separate:
            raise UnsupportedPictureError(
                f"PIC {pic_text!r}: SIGN SEPARATE on a numeric-edited item is not modelled"
            )
        return _parse_edited(pic_text, chars)

    if any(c in "9SV" for c in chars):
        return _parse_numeric(pic_text, chars, sign_separate)

    if all(c in "XA" for c in chars):
        return Picture(
            pic_text,
            len(chars),
            numeric=False,
            decimal_scale=0,
            signed=False,
            edited=False,
        )

    raise UnsupportedPictureError(f"PIC {pic_text!r}: mixed or unrecognised category")


def _parse_numeric(pic_text: str, chars: str, sign_separate: bool) -> Picture:
    if any(c in "XA" for c in chars):
        raise UnsupportedPictureError(
            f"PIC {pic_text!r}: mixed alphanumeric/numeric items are not modelled"
        )
    signed = "S" in chars
    digits = chars.count("9")

    # V is the implied decimal point: zero stored bytes, and everything to
    # its right is the fractional part. This is the K2 "off by one after the
    # first numeric field" failure, computed instead of counted.
    if chars.count("V") > 1:
        raise UnsupportedPictureError(f"PIC {pic_text!r}: more than one V")
    scale = chars.split("V", 1)[1].count("9") if "V" in chars else 0

    width = digits + (1 if signed and sign_separate else 0)
    return Picture(
        pic_text, width, numeric=True, decimal_scale=scale, signed=signed, edited=False
    )


def _parse_edited(pic_text: str, chars: str) -> Picture:
    if chars.count(".") > 1:
        raise UnsupportedPictureError(f"PIC {pic_text!r}: more than one decimal point")

    # Every symbol in an edit mask occupies exactly one print position --
    # including each floating-sign position and the decimal point itself.
    width = len(chars)
    signed = "-" in chars or "+" in chars
    scale = sum(1 for c in chars.split(".", 1)[1] if c in "9Z*") if "." in chars else 0

    return Picture(
        pic_text, width, numeric=True, decimal_scale=scale, signed=signed, edited=True
    )
