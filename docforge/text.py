"""Text metrics for mixed CJK / Latin strings.

Every box size, gap and clearance in docforge is *computed* from these numbers,
never eyeballed. This module is the single source of truth for "how wide is this
string going to be", and the geometry validator trusts it to decide whether a
label overflows its container.
"""

from __future__ import annotations

CJK_MIN = 0x2E80
"""Code points at or above this are treated as full-width (1.0 em)."""

NARROW = 0.55
MONO = 0.60
"""Advance width of a monospace glyph, in em. Latin only in practice."""
"""Advance width of a Latin glyph, in em."""

ELLIPSIS = "\u2026"

# Characters that make a good line-break opportunity in Latin text.
_BREAK_AFTER = "-/\u2013\u2014"


def units(s: str) -> float:
    """Approximate advance width of *s*, in em."""
    return sum(1.0 if ord(c) >= CJK_MIN else NARROW for c in str(s))


def tw_mono(s: str, fs: float) -> float:
    """Width of *s* set in the monospace face.

    Monospace advances are uniform, so this is not the proportional estimate
    with a fudge factor -- card geometry that holds field names has to use it
    or the boxes come out narrower than their own contents.
    """
    return sum((1.0 if ord(c) >= CJK_MIN else MONO) for c in str(s)) * fs


def tw(s: str, fs: float) -> float:
    """Approximate rendered width of *s* at font size *fs*, in user units."""
    return units(s) * fs


def fit(s: str, fs: float, maxw: float) -> float:
    """Largest font size <= *fs* at which *s* still fits within *maxw*."""
    u = units(s)
    if u <= 0:
        return fs
    return min(fs, maxw / u)


def truncate(s: str, fs: float, maxw: float, ellipsis: str = ELLIPSIS) -> str:
    """Shorten *s* so that it fits *maxw* at *fs*, appending *ellipsis*."""
    s = str(s)
    if tw(s, fs) <= maxw:
        return s
    budget = maxw - tw(ellipsis, fs)
    if budget < 0:
        # Not even the ellipsis fits: the only result that honours *maxw* is
        # the empty string (no glyph is narrower than the ellipsis).
        return ""
    out, w = "", 0.0
    for ch in s:
        cw = (1.0 if ord(ch) >= CJK_MIN else NARROW) * fs
        if w + cw > budget:
            break
        out += ch
        w += cw
    return out + ellipsis


def wrap(s: str, fs: float, maxw: float) -> list:
    """Greedy wrap for mixed CJK / Latin text.

    CJK may break between any two characters; Latin prefers to break at spaces
    or after a hyphen. An explicit ``\\n`` always forces a break.
    """
    out: list = []
    for para in str(s).split("\n"):
        if para == "":
            out.append("")
            continue
        line, w = "", 0.0
        last_break = -1  # index in `line` just past a good break point
        for ch in para:
            cw = (1.0 if ord(ch) >= CJK_MIN else NARROW) * fs
            if w + cw > maxw and line:
                # Prefer the most recent Latin break opportunity, but only if it
                # keeps a reasonable amount of the line.
                cut = last_break if last_break >= max(1, int(len(line) * 0.4)) else len(line)
                head, tail = line[:cut], line[cut:]
                out.append(head.rstrip())
                line, w = tail.lstrip(), 0.0
                for c2 in line:
                    w += (1.0 if ord(c2) >= CJK_MIN else NARROW) * fs
                last_break = -1
            line += ch
            w += cw
            if ch == " " or ord(ch) >= CJK_MIN or ch in _BREAK_AFTER:
                last_break = len(line)
        out.append(line)
    return out


def lines_needed(s: str, fs: float, maxw: float) -> int:
    """How many lines *s* occupies when wrapped into *maxw*."""
    return max(1, len(wrap(s, fs, maxw)))


def block_height(rows, lead_gap: float = 5.0) -> float:
    """Total height of a stacked text block.

    *rows* is a sequence of font sizes, one per line.
    """
    rows = list(rows)
    if not rows:
        return 0.0
    return sum(fs + lead_gap for fs in rows) - lead_gap
