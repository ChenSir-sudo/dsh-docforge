"""Text metrics for mixed CJK / Latin strings.

Every box size, gap and clearance in docforge is *computed* from these numbers,
never eyeballed. This module is the single source of truth for "how wide is this
string going to be", and the geometry validator trusts it to decide whether a
label overflows its container.
"""

from __future__ import annotations

CJK_MIN = 0x2E80
"""Code points at or above this are treated as full-width (1.0 em)."""

#: Fallback advance for a glyph the table does not cover: accented Latin, Greek,
#: Cyrillic, symbols. The mean of the measured ASCII set, and a better guess than
#: one constant applied to every letter.
NARROW = 0.5159

#: Advance width of a monospace glyph, in em. Latin only in practice.
MONO = 0.60

#: Measured advance of every printable ASCII glyph, in em, at the document font
#: stack. One constant cannot describe a face where `l` is 0.20 em and `W` is
#: 0.92 -- a 4.5x spread -- and the error that produced reached 78px at 14px
#: against a 2px tolerance. Glyph *proportions* hold across sans faces even
#: though the absolute numbers shift, so this travels better than the constant.
#:
#: Calibrated on the font stack the documents actually declare, which is the
#: face a reader gets whenever the CSS resolves. Averaging across unrelated
#: faces was tried and is worse where it counts: it pushed the error on the
#: intended stack from 3.4px to 15.6px to buy a smaller error on faces the
#: stylesheet does not ask for.
#:
#: KNOWN LIMIT, measured: if the declared stack misses entirely and the browser
#: falls back to Arial/Helvetica metrics, the error grows to ~17px at 14px.
#: `tools/measure-text.py --faces` reports this; keep a metric-compatible
#: fallback at the end of --sans so it stays a hypothetical.
#:
#: Regenerate with ``python3 tools/measure-text.py --emit-table FILE``.
_ADVANCE = {
    " ": 0.2051, "!": 0.2666, "\"": 0.4033, "#": 0.6045, "$": 0.6045, "%": 0.8081,
    "&": 0.6689, "'": 0.2539, "(": 0.3223, ")": 0.3223, "*": 0.4004, "+": 0.6045,
    ",": 0.2148, "-": 0.4287, ".": 0.2148, "/": 0.2793, "0": 0.6064, "1": 0.4434,
    "2": 0.5659, "3": 0.5918, "4": 0.6045, "5": 0.5850, "6": 0.6172, "7": 0.5469,
    "8": 0.5996, "9": 0.6172, ":": 0.2148, ";": 0.2148, "<": 0.6045, "=": 0.6045,
    ">": 0.6045, "?": 0.4893, "@": 0.8745, "A": 0.6353, "B": 0.6045, "C": 0.6860,
    "D": 0.6787, "E": 0.5522, "F": 0.5278, "G": 0.7065, "H": 0.6992, "I": 0.2246,
    "J": 0.4951, "K": 0.6006, "L": 0.5244, "M": 0.8311, "N": 0.6992, "O": 0.7314,
    "P": 0.5776, "Q": 0.7314, "R": 0.5991, "S": 0.5933, "T": 0.5811, "U": 0.6963,
    "V": 0.6309, "W": 0.9238, "X": 0.6348, "Y": 0.6123, "Z": 0.6167, "[": 0.3223,
    "\\": 0.2793, "]": 0.3223, "^": 0.6045, "_": 0.5269, "`": 0.5000, "a": 0.5020,
    "b": 0.5537, "c": 0.5010, "d": 0.5537, "e": 0.5122, "f": 0.3037, "g": 0.5488,
    "h": 0.5391, "i": 0.2061, "j": 0.2051, "k": 0.4854, "l": 0.2041, "m": 0.8032,
    "n": 0.5269, "o": 0.5308, "p": 0.5493, "q": 0.5488, "r": 0.3081, "s": 0.4653,
    "t": 0.3013, "u": 0.5269, "v": 0.4829, "w": 0.7153, "x": 0.4683, "y": 0.4863,
    "z": 0.4678, "{": 0.3223, "|": 0.2158, "}": 0.3223, "~": 0.6045,
}

#: Bold text is wider than regular, and the advance table measures regular.
#: Node and card titles are 600; section, band and value text is 700. Ignoring
#: that left every bold label 5-12% under-estimated -- the same class of error
#: as the old single constant, just smaller.
BOLD = 1.05
HEAVY = 1.08
"""Weight multipliers, measured against the same corpus."""

#: The 700 weight, for call sites that read better as a role than a number.
#: Named for the role: `*_fs` in this codebase means font *size*.
WEIGHT_HEAVY = 700
WEIGHT_BOLD = 600


def weight_factor(weight: int) -> float:
    """How much wider *weight* sets a Latin glyph than regular."""
    if weight >= 700:
        return HEAVY
    if weight >= 600:
        return BOLD
    return 1.0


def char_width(ch: str, fs: float, weight: int = 400) -> float:
    """Advance of one glyph at *fs* and *weight*, in user units.

    The single place that decides how wide a character is. Truncation and
    wrapping used to compute this themselves with a flat constant, so they
    disagreed with :func:`tw` the moment the table replaced it -- and the
    validator, which measures with ``tw``, could then flag text the layout
    believed it had already truncated.

    CJK is full-width and its advance does not change with weight, so the
    multiplier applies to the Latin branch only.
    """
    if ord(ch) >= CJK_MIN:
        return fs
    return _ADVANCE.get(ch, NARROW) * fs * weight_factor(weight)


ELLIPSIS = "\u2026"

# Characters that make a good line-break opportunity in Latin text.
_BREAK_AFTER = "-/\u2013\u2014"


def units(s: str, weight: int = 400) -> float:
    """Advance width of *s*, in em, at *weight*.

    Sums a measured per-glyph table rather than assuming one Latin width, and
    scales by the weight's measured multiplier.
    """
    # fs = 1.0 so the result is in em, which is what callers of `units` expect.
    return sum(char_width(c, 1.0, weight) for c in str(s))


def tw_mono(s: str, fs: float) -> float:
    """Width of *s* set in the monospace face.

    Monospace advances are uniform, so this is not the proportional estimate
    with a fudge factor -- card geometry that holds field names has to use it
    or the boxes come out narrower than their own contents.
    """
    return sum((1.0 if ord(c) >= CJK_MIN else MONO) for c in str(s)) * fs


def tw(s: str, fs: float, weight: int = 400) -> float:
    """Rendered width of *s* at *fs* and *weight*, in user units."""
    return units(s, weight) * fs


def fit(s: str, fs: float, maxw: float, weight: int = 400) -> float:
    """Largest font size <= *fs* at which *s* still fits within *maxw*."""
    u = units(s, weight)
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
        cw = char_width(ch, fs)
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
            cw = char_width(ch, fs)
            if w + cw > maxw and line:
                # Prefer the most recent Latin break opportunity, but only if it
                # keeps a reasonable amount of the line.
                cut = last_break if last_break >= max(1, int(len(line) * 0.4)) else len(line)
                head, tail = line[:cut], line[cut:]
                out.append(head.rstrip())
                line, w = tail.lstrip(), 0.0
                for c2 in line:
                    w += char_width(c2, fs)
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
