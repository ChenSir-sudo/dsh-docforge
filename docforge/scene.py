"""Scene: the drawing surface.

A ``Scene`` does two jobs at once, and the second one is the important one:

1. It emits SVG.
2. It **records the geometry** of everything it draws — boxes, text blocks,
   edge polylines, label rectangles. ``docforge.validate`` walks that record to
   prove that no text overflows, no boxes overlap, no connector runs through an
   unrelated node and nothing falls off the canvas.

Because every primitive reports its own bounding box, the checks are exact
rather than heuristic: they use the same width estimates the layout used.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import text as T
from .geom import Rect, arc_points, polyline_length, rect_from_points, rounded_path

KINDS = ("line", "indigo", "teal", "amber", "red", "green", "violet", "slate", "ink")

DEFAULT_PAD = 12.0
"""Horizontal breathing room inside a box before text counts as overflowing."""


def esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@dataclass
class Item:
    """One drawn thing, plus everything the validator needs to judge it."""

    kind: str
    bbox: Rect
    id: str | None = None
    inner: Rect | None = None
    text_boxes: list = field(default_factory=list)
    pts: tuple = ()
    endpoints: tuple = ()
    meta: dict = field(default_factory=dict)

    @property
    def text_bbox(self):
        if not self.text_boxes:
            return None
        box = self.text_boxes[0]
        for b in self.text_boxes[1:]:
            box = box.union(b)
        return box

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "bbox": self.bbox.as_dict(),
            "label": self.meta.get("label") or self.meta.get("title"),
            "endpoints": list(self.endpoints),
        }


def _id_namespace(uid: str) -> str:
    """An id-safe namespace for one scene's SVG markers.

    Kept readable when the uid already is one, so a top-level figure's output is
    unchanged; suffixed with a short digest only when it is not.
    """
    text = str(uid)
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", text)
    if safe == text and text:
        return safe
    return f"{safe}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:6]}"


class Scene:
    """A single diagram."""

    def __init__(self, uid: str, width: float, height: float,
                 title: str = "", description: str = "", pad: float = DEFAULT_PAD,
                 marker_ns: str = None):
        self.uid = uid
        #: SVG ids are referenced with `url(#...)`, so they must survive being
        #: an NCName-ish token. A nested figure's uid is a *path* like
        #: `outer/inner`, which is readable in a finding but not usable as an
        #: id -- and two nested figures must not share marker ids or their
        #: arrowheads take each other's colour. Top-level ids are already safe,
        #: so they pass through unchanged and existing documents do not churn.
        self.marker_ns = marker_ns or _id_namespace(uid)
        self.width = float(width)
        self.height = float(height)
        self.title = title
        self.description = description
        self.pad = pad
        self.items: list = []
        #: Nested figures, keyed by the node that holds them. The validator
        #: walks these so a misplaced element inside a nested figure is still
        #: reported -- labelled with the path it lives at.
        self.children: dict = {}
        self._parts: list = []
        self._ids: set = set()
        self._n = 0

    # ------------------------------------------------------------------ util
    def _auto_id(self) -> str:
        self._n += 1
        return f"{self.uid}-a{self._n}"

    def _register(self, item: Item) -> Item:
        if item.id:
            if item.id in self._ids:
                raise ValueError(f"duplicate id {item.id!r} in scene {self.uid!r}")
            self._ids.add(item.id)
        self.items.append(item)
        return item

    def raw(self, markup: str) -> "Scene":
        self._parts.append(markup)
        return self

    def get(self, item_id: str) -> Item:
        for it in self.items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)

    def bounds(self) -> Rect:
        if not self.items:
            return Rect(0, 0, self.width, self.height)
        b = self.items[0].bbox
        for it in self.items[1:]:
            b = b.union(it.bbox)
        return b

    # ------------------------------------------------------------- primitives
    def node(self, x, y, w, h, title, sub=None, kind="default", id=None,
             fs=15.0, subfs=11.5, rx=12.0, dashes=False, mono=False,
             align="center", tcls="d-t", scls="d-s"):
        """A labelled rounded box. ``sub`` is a string (``\\n`` split) or a list."""
        subs = []
        if sub:
            subs = list(sub) if isinstance(sub, (list, tuple)) else str(sub).split("\n")
        title = str(title)

        tlh = fs + 6.0
        slh = subfs + 4.5
        total = tlh + slh * len(subs)
        top = y + h / 2.0 - total / 2.0

        boxes = []
        parts = [f'<g class="nd k-{kind}">']
        parts.append(
            f'<rect class="d-box" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'rx="{rx:g}"' + (' stroke-dasharray="6 5"' if dashes else "") + "/>"
        )
        cx = x + w / 2.0
        ty = top + tlh / 2.0
        tw_ = T.tw(title, fs)
        tx = cx if align == "center" else x + self.pad
        anchor = "middle" if align == "center" else "start"
        parts.append(
            f'<text class="{tcls}" x="{tx:g}" y="{ty:.1f}" text-anchor="{anchor}" '
            f'dominant-baseline="central" style="font-size:{fs:g}px">{esc(title)}</text>'
        )
        boxes.append(Rect(tx - tw_ / 2 if align == "center" else tx,
                          ty - fs / 2.0, tw_, fs))
        for i, ln in enumerate(subs):
            ly = top + tlh + slh * (i + 0.5)
            lw = T.tw(ln, subfs)
            lx = cx if align == "center" else x + self.pad
            parts.append(
                f'<text class="{scls}" x="{lx:g}" y="{ly:.1f}" text-anchor="{anchor}" '
                f'dominant-baseline="central" style="font-size:{subfs:g}px">{esc(ln)}</text>'
            )
            boxes.append(Rect(lx - lw / 2 if align == "center" else lx,
                              ly - subfs / 2.0, lw, subfs))
        parts.append("</g>")
        self.raw("".join(parts))
        return self._register(Item(
            kind="node", bbox=Rect(x, y, w, h),
            inner=Rect(x + self.pad, y + 4, w - 2 * self.pad, h - 8),
            text_boxes=boxes, id=id or self._auto_id(),
            meta={"kind": kind, "title": title, "mono": mono,
                  "lines": [title] + subs},
        ))

    def chip(self, x, y, w, h, label, kind="default", id=None, fs=12.5):
        return self.node(x, y, w, h, label, None, kind=kind, id=id, fs=fs, rx=h / 2.0)

    def card(self, x, y, w, h, title, sub=None, items=(), kind="default", id=None,
             fs=14.0, subfs=10.5, ifs=11.5, pad=15.0, gap=None, accent=None,
             item_code=False):
        """A list card: title, optional subtitle, then left-aligned lines."""
        items = [str(i) for i in items]
        gap = gap or (ifs + 6.5)
        title = str(title)
        parts = [f'<g class="nd k-{kind}">',
                 f'<rect class="d-box d-card" x="{x:g}" y="{y:g}" width="{w:g}" '
                 f'height="{h:g}" rx="12"/>']
        boxes = []
        cy = y + 23.0
        parts.append(
            f'<text class="d-t" x="{x + pad:g}" y="{cy:.1f}" '
            f'style="font-size:{fs:g}px" dominant-baseline="central">{esc(title)}</text>'
        )
        boxes.append(Rect(x + pad, cy - fs / 2.0, T.tw(title, fs), fs))
        if accent:
            aw = T.tw(accent, subfs)
            parts.append(
                f'<text class="d-num" x="{x + w - pad:g}" y="{cy:.1f}" text-anchor="end" '
                f'style="font-size:{subfs:g}px" dominant-baseline="central">{esc(accent)}</text>'
            )
            boxes.append(Rect(x + w - pad - aw, cy - subfs / 2.0, aw, subfs))
        if sub:
            sub = str(sub)
            cy += subfs + 6.0
            parts.append(
                f'<text class="d-s" x="{x + pad:g}" y="{cy:.1f}" '
                f'style="font-size:{subfs:g}px" dominant-baseline="central">{esc(sub)}</text>'
            )
            boxes.append(Rect(x + pad, cy - subfs / 2.0, T.tw(sub, subfs), subfs))
        if items:
            cy += gap + (2 if sub else 0)
            for line in items:
                # `d-ci` is the mono, slightly-darker role: a field name is an
                # identifier, not prose, and styling it as prose is what makes
                # a card read as one undifferentiated block.
                cls = "d-ci" if item_code else "d-s"
                parts.append(
                    f'<text class="{cls}" x="{x + pad:g}" y="{cy:.1f}" '
                    f'style="font-size:{ifs:g}px" dominant-baseline="central">{esc(line)}</text>'
                )
                boxes.append(Rect(x + pad, cy - ifs / 2.0, T.tw(line, ifs), ifs))
                cy += gap
        parts.append("</g>")
        self.raw("".join(parts))
        return self._register(Item(
            kind="card", bbox=Rect(x, y, w, h),
            inner=Rect(x + pad, y + 4, w - 2 * pad, h - 8),
            text_boxes=boxes, id=id or self._auto_id(),
            meta={"kind": kind, "title": title,
                  "lines": [title]
                           + ([str(accent)] if accent else [])
                           + ([str(sub)] if sub else [])
                           + items},
        ))

    def band(self, x, y, w, h, label=None, sub=None, kind="default", id=None,
             rx=16.0, lx=None, ly=None, fs=13.0, dash=False, anchor="start"):
        """A container rectangle. Drawn *before* its children."""
        extra = ' stroke-dasharray="7 6"' if dash else ""
        self.raw(
            f'<rect class="d-band b-{kind}" x="{x:g}" y="{y:g}" width="{w:g}" '
            f'height="{h:g}" rx="{rx:g}"{extra}/>'
        )
        boxes = []
        ax = lx if lx is not None else x + 20
        ay = ly if ly is not None else y + 22
        if label:
            label = str(label)
            self.raw(
                f'<text class="d-band-t bt-{kind}" x="{ax:g}" y="{ay:g}" '
                f'text-anchor="{anchor}" dominant-baseline="central" '
                f'style="font-size:{fs:g}px">{esc(label)}</text>'
            )
            lw = T.tw(label, fs)
            boxes.append(Rect(ax - lw / 2 if anchor == "middle" else
                              (ax - lw if anchor == "end" else ax),
                              ay - fs / 2.0, lw, fs))
        if sub:
            sub = str(sub)
            sw = T.tw(sub, fs - 1.5)
            sx = ax + T.tw(label, fs) + 16 if label else ax
            self.raw(
                f'<text class="d-sub" x="{sx:g}" y="{ay:g}" dominant-baseline="central" '
                f'style="font-size:{fs - 1.5:g}px">{esc(sub)}</text>'
            )
            boxes.append(Rect(sx, ay - (fs - 1.5) / 2.0, sw, fs - 1.5))
        return self._register(Item(
            kind="band", bbox=Rect(x, y, w, h), text_boxes=boxes,
            id=id or self._auto_id(),
            meta={"kind": kind, "label": label,
                  "lines": ([str(label)] if label else [])
                           + ([str(sub)] if sub else [])},
        ))

    def edge(self, pts, kind="line", label=None, id=None, from_id=None, to_id=None,
             dashed=False, head=True, tail=False, r=11.0, lfs=11.5,
             lx=None, ly=None, anchor="middle", halo=None, opacity=1.0,
             label_gap=9.0, snap=False, routed=False):
        """An orthogonal connector.

        ``from_id``/``to_id`` are recorded as the connector's endpoints so the
        validator can exclude the nodes it legitimately touches. They do *not*
        move the geometry unless ``snap=True`` — layout engines already compute
        exact ports, and snapping those to a node centre would drag the line
        straight through the box.
        """
        pts = [(float(a), float(b)) for a, b in pts]
        if snap and from_id:
            it = self.get(from_id)
            pts[0] = (it.bbox.cx, it.bbox.cy)
        if snap and to_id:
            it = self.get(to_id)
            pts[-1] = (it.bbox.cx, it.bbox.cy)
        d = rounded_path(pts, r)
        cls = f"dg-e e-{kind}" + (" dash" if dashed else "")
        attrs = f'class="{cls}" d="{d}" fill="none"'
        if head:
            attrs += f' marker-end="url(#m{self.marker_ns}-{kind})"'
        if tail:
            attrs += f' marker-start="url(#m{self.marker_ns}-{kind})"'
        self.raw(f"<path {attrs}/>")

        boxes = []
        if label:
            label = str(label)
            lw = T.tw(label, lfs)
            if lx is None:
                lx = (pts[0][0] + pts[-1][0]) / 2.0
            if ly is None:
                ly = (pts[0][1] + pts[-1][1]) / 2.0 - label_gap
            halo = halo or "var(--surface)"
            self.raw(
                f'<text class="d-el" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                f'opacity="{opacity:g}" style="font-size:{lfs:g}px;paint-order:stroke;'
                f'stroke:{halo};stroke-width:5px;stroke-linejoin:round" '
                f'dominant-baseline="central">{esc(label)}</text>'
            )
            ax = lx - lw / 2 if anchor == "middle" else (lx - lw if anchor == "end" else lx)
            boxes.append(Rect(ax, ly - lfs / 2.0, lw, lfs))
        bbox = rect_from_points(pts)
        return self._register(Item(
            kind="edge", bbox=bbox, pts=tuple(pts), text_boxes=boxes,
            id=id or self._auto_id(), endpoints=(from_id, to_id),
            meta={"kind": kind, "label": label, "length": polyline_length(pts),
                  "routed": bool(routed),
                  "lines": [label] if label else []},
        ))

    def line(self, pts, cls="d-life", id=None, meta=None):
        """A decorative rule that other elements must still not sit on.

        Drawn through :meth:`raw` it would be invisible to the validator — a
        sequence lifeline could cut straight through a message label and every
        check would stay green.
        """
        pts = [(float(a), float(b)) for a, b in pts]
        d = " ".join([f"M {pts[0][0]:g} {pts[0][1]:g}"]
                     + [f"L {x:g} {y:g}" for x, y in pts[1:]])
        self.raw(f'<path class="{cls}" d="{d}" fill="none"/>')
        return self._register(Item(
            kind="edge", bbox=rect_from_points(pts), pts=tuple(pts),
            id=id or self._auto_id(),
            meta={"kind": "line", "decor": True, "length": polyline_length(pts),
                  **(meta or {})},
        ))

    def arc(self, cx, cy, rx, ry, a0, a1, kind="violet", id=None, head=True,
            steps=32, from_id=None, to_id=None):
        pts = arc_points(cx, cy, rx, ry, a0, a1, steps)
        d = (f"M {pts[0][0]:.1f} {pts[0][1]:.1f} A {rx:g} {ry:g} 0 "
             f"{1 if abs(a1 - a0) > 180 else 0} 1 {pts[-1][0]:.1f} {pts[-1][1]:.1f}")
        hd = f' marker-end="url(#m{self.marker_ns}-{kind})"' if head else ""
        self.raw(f'<path class="dg-e e-{kind}" d="{d}" fill="none"{hd}/>')
        return self._register(Item(
            kind="arc", bbox=rect_from_points(pts).inflate(2), pts=tuple(pts),
            id=id or self._auto_id(), endpoints=(from_id, to_id),
            meta={"kind": kind, "a0": a0, "a1": a1,
                  "length": polyline_length(pts)},
        ))

    # ------------------------------------------------------------------
    # Data-shaped primitives: a value in a cell, a span on an axis, a stage
    # that narrows. Each registers like any other box, so text overflow,
    # overlap and edge-through all apply to them without extra rules.
    # ------------------------------------------------------------------
    def cell(self, x, y, w, h, value=None, label=None, kind="default",
             level=0, id=None, vfs=17.0, lfs=10.5, pad=10.0, rx=8.0,
             level_ratio=None):
        """One matrix cell: a value, with an optional caption beneath it.

        Intensity is what lets a grid read as a heat map instead of a table.
        Two ways to say it: ``level`` is the stepped 0-4 scale, ``level_ratio``
        is a continuous 0.0-1.0. The ratio is applied by *layering* an accent
        wash over the surface rather than by computing a mixed colour, so it
        stays a theme variable at every opacity and needs no colour arithmetic.
        """
        level = max(0, min(4, int(level)))
        ratio = level / 4.0 if level_ratio is None else max(0.0, min(1.0, float(level_ratio)))
        value = "" if value is None else str(value)
        label = str(label) if label else ""
        self.raw(f'<g class="nd k-{kind}">')
        self.raw(
            f'<rect class="d-cell" x="{x:g}" y="{y:g}" width="{w:g}" '
            f'height="{h:g}" rx="{rx:g}"/>'
        )
        if ratio > 0:
            # 0.78 is the ceiling: at full strength the value must still read.
            self.raw(
                f'<rect class="d-cell-fill" x="{x:g}" y="{y:g}" width="{w:g}" '
                f'height="{h:g}" rx="{rx:g}" fill-opacity="{0.78 * ratio:.3f}"/>'
            )
        boxes = []
        inner = Rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad)
        if value and label:
            vy = y + h * 0.40
            ly = y + h * 0.68
            self.raw(
                f'<text class="d-cell-v" x="{x + w / 2:g}" y="{vy:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" style="font-size:{vfs:g}px">{esc(value)}</text>'
            )
            self.raw(
                f'<text class="d-cell-l" x="{x + w / 2:g}" y="{ly:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" style="font-size:{lfs:g}px">{esc(label)}</text>'
            )
            boxes.append(Rect(x + (w - T.tw(value, vfs)) / 2.0, vy - vfs / 2.0,
                              T.tw(value, vfs), vfs))
            boxes.append(Rect(x + (w - T.tw(label, lfs)) / 2.0, ly - lfs / 2.0,
                              T.tw(label, lfs), lfs))
        elif value or label:
            text = value or label
            fs = vfs if value else lfs
            cy = y + h / 2.0
            self.raw(
                f'<text class="{"d-cell-v" if value else "d-cell-l"}" '
                f'x="{x + w / 2:g}" y="{cy:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" style="font-size:{fs:g}px">{esc(text)}</text>'
            )
            boxes.append(Rect(x + (w - T.tw(text, fs)) / 2.0, cy - fs / 2.0,
                              T.tw(text, fs), fs))
        self.raw("</g>")
        return self._register(Item(
            kind="cell", bbox=Rect(x, y, w, h), inner=inner,
            text_boxes=boxes, id=id or self._auto_id(),
            meta={"kind": kind, "label": label or value, "level": level,
                  "level_ratio": round(ratio, 4),
                  "lines": [t for t in (value, label) if t]},
        ))

    def bar(self, x, y, w, h, label=None, kind="teal", dashed=False, id=None,
            fs=11.0, pad=9.0, rx=7.0):
        """A span on an axis: one bar of a timeline or a Gantt row."""
        label = str(label) if label else ""
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.raw(f'<g class="nd k-{kind}">')
        self.raw(
            f'<rect class="d-bar" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'rx="{rx:g}"{dash}/>'
        )
        boxes = []
        extent = Rect(x, y, w, h)
        if label:
            tw = T.tw(label, fs)
            if tw <= w - 2 * pad:
                cx, anchor = x + w / 2.0, "middle"
                tb = Rect(cx - tw / 2.0, y + h / 2.0 - fs / 2.0, tw, fs)
            else:
                # Too narrow to hold its own label: the text sits just after the
                # bar, and the bar's *declared extent* grows to cover it. The
                # alternative is a label the validator would rightly call an
                # overflow, for a bar that renders exactly as intended.
                cx, anchor = x + w + pad, "start"
                tb = Rect(cx, y + h / 2.0 - fs / 2.0, tw, fs)
                extent = Rect(x, y, tb.right - x, h)
            boxes.append(tb)
            self.raw(
                f'<text class="d-bar-t" x="{cx:g}" y="{y + h / 2.0:.1f}" '
                f'text-anchor="{anchor}" dominant-baseline="central" '
                f'style="font-size:{fs:g}px">{esc(label)}</text>'
            )
        self.raw("</g>")
        return self._register(Item(
            kind="bar", bbox=extent,
            inner=Rect(extent.x + 2, extent.y + 2,
                       max(0.0, extent.w - 4), max(0.0, extent.h - 4)),
            text_boxes=boxes, id=id or self._auto_id(),
            meta={"kind": kind, "label": label, "lines": [label] if label else []},
        ))

    def funnel(self, cx, y, w_top, w_bottom, h, label=None, value=None,
               kind="indigo", id=None, fs=12.5, vfs=12.5, pad=12.0):
        """One stage of a funnel: a trapezoid from *w_top* down to *w_bottom*.

        The label is measured against the trapezoid's *narrower* end, because
        that is the width the text actually has to live in near the bottom.
        """
        label = str(label) if label else ""
        value = str(value) if value else ""
        self.raw(f'<g class="nd k-{kind}">')
        self.raw(
            f'<path class="d-funnel" d="M {cx - w_top / 2:g} {y:g} '
            f'L {cx + w_top / 2:g} {y:g} L {cx + w_bottom / 2:g} {y + h:g} '
            f'L {cx - w_bottom / 2:g} {y + h:g} Z"/>'
        )
        boxes = []
        safe = min(w_top, w_bottom) - 2 * pad
        texts = [t for t in (value, label) if t]
        if texts and safe > 10:
            cy = y + h * (0.40 if len(texts) > 1 else 0.5)
            for i, text in enumerate(texts):
                fs_i = vfs if (i == 0 and value) else fs
                ty = cy if i == 0 else cy + h * 0.26
                shown = T.truncate(text, fs_i, safe)
                self.raw(
                    f'<text class="{"d-funnel-v" if (i == 0 and value) else "d-funnel-l"}" '
                    f'x="{cx:g}" y="{ty:.1f}" text-anchor="middle" '
                    f'dominant-baseline="central" style="font-size:{fs_i:g}px">{esc(shown)}</text>'
                )
                boxes.append(Rect(cx - T.tw(shown, fs_i) / 2.0, ty - fs_i / 2.0,
                                  T.tw(shown, fs_i), fs_i))
        self.raw("</g>")
        return self._register(Item(
            kind="funnel", bbox=Rect(cx - max(w_top, w_bottom) / 2.0, y,
                                     max(w_top, w_bottom), h),
            inner=Rect(cx - safe / 2.0, y + 4, max(0.0, safe), max(0.0, h - 8)),
            text_boxes=boxes, id=id or self._auto_id(),
            meta={"kind": kind, "label": label or value,
                  "lines": [t for t in (value, label) if t]},
        ))

    def embed(self, x, y, w, h, title, sub_scene, kind="default", id=None,
              fs=13.5, pad=12.0, head_h=None):
        """A node that *contains* another figure.

        The nested scene is drawn into this box at its own intrinsic size and
        inside its own coordinate space -- no scaling, because scaling a figure
        scales its type with it. Its id namespace already carries the path, so
        its markers cannot collide with a sibling's.
        """
        title = str(title) if title else ""
        head = head_h if head_h is not None else (fs + 14.0 if title else 0.0)
        self.raw(f'<g class="nd k-{kind}">')
        self.raw(
            f'<rect class="d-box d-embed" x="{x:g}" y="{y:g}" width="{w:g}" '
            f'height="{h:g}" rx="12"/>'
        )
        boxes = []
        if title:
            self.raw(
                f'<text class="d-t" x="{x + pad:g}" y="{y + head / 2.0:.1f}" '
                f'dominant-baseline="central" style="font-size:{fs:g}px">{esc(title)}</text>'
            )
            boxes.append(Rect(x + pad, y + head / 2.0 - fs / 2.0, T.tw(title, fs), fs))
        # Two different regions, and conflating them is a real bug: `inner` is
        # where this item's *text* may live (so it has to contain the title),
        # while the nested figure gets its own box underneath the title.
        content = Rect(x + pad, y + head + pad, max(0.0, w - 2 * pad),
                       max(0.0, h - head - 2 * pad))
        if sub_scene is not None:
            sw, sh = sub_scene.width, sub_scene.height
            self.raw(f'<g transform="translate({content.x:g} {content.y:g})">')
            self.raw(sub_scene.fragment())
            self.raw("</g>")
        else:
            sw = sh = 0.0
        self.raw("</g>")
        return self._register(Item(
            kind="embed", bbox=Rect(x, y, w, h),
            inner=Rect(x + pad, y + 4, max(0.0, w - 2 * pad), max(0.0, h - 8)),
            text_boxes=boxes, id=id or self._auto_id(),
            meta={"kind": kind, "label": title, "lines": [title] if title else [],
                  "content_size": (sw, sh), "content_box": content,
                  "child": sub_scene},
        ))

    def tag(self, x, y, label, kind="line", anchor="middle", fs=11.0, pad=7.0,
            id=None):
        label = str(label)
        w = T.tw(label, fs) + pad * 2
        h = fs + 9
        rx = (x - w / 2) if anchor == "middle" else ((x - w) if anchor == "end" else x)
        self.raw(
            f'<g class="tg k-{kind}"><rect class="d-tag" x="{rx:.1f}" '
            f'y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:g}" rx="{h / 2:g}"/>'
            f'<text class="d-tag-t" x="{rx + w / 2:.1f}" y="{y:.1f}" '
            f'text-anchor="middle" dominant-baseline="central" '
            f'style="font-size:{fs:g}px">{esc(label)}</text></g>'
        )
        return self._register(Item(
            kind="tag", bbox=Rect(rx, y - h / 2, w, h),
            text_boxes=[Rect(rx + pad, y - fs / 2, w - 2 * pad, fs)],
            id=id or self._auto_id(),
            meta={"kind": kind, "label": label, "lines": [label]},
        ))

    def text(self, x, y, label, cls="d-s", anchor="start", fs=12.0, id=None,
             kind="default", maxw=None, owner=None):
        label = str(label)
        if maxw is not None:
            label = T.truncate(label, fs, maxw)
        self.raw(
            f'<text class="{cls}" x="{x:g}" y="{y:g}" text-anchor="{anchor}" '
            f'style="font-size:{fs:g}px" dominant-baseline="central">{esc(label)}</text>'
        )
        w = T.tw(label, fs)
        ax = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        return self._register(Item(
            kind="text", bbox=Rect(ax, y - fs / 2, w, fs),
            text_boxes=[Rect(ax, y - fs / 2, w, fs)],
            id=id or self._auto_id(),
            meta={"kind": kind, "label": label, "cls": cls, "owner": owner,
                  "lines": [label]},
        ))

    def lines(self, x, y, seq, cls="d-s", anchor="start", lh=16.0, fs=12.0,
              id=None, kind="default"):
        out = []
        for i, s in enumerate(seq):
            out.append(self.text(x, y + i * lh, s, cls=cls, anchor=anchor, fs=fs,
                                 kind=kind))
        return out

    def legend(self, x, y, entries, fs=11.5, gap=22.0, swatch=13.0):
        """``entries`` is a sequence of ``(kind, label)`` pairs."""
        cx = x
        out = []
        for kind, label in entries:
            self.raw(
                f'<g class="k-{kind}"><rect class="d-box" x="{cx:g}" '
                f'y="{y - swatch / 2:g}" width="{swatch:g}" height="{swatch:g}" '
                f'rx="4"/></g>'
            )
            out.append(self.text(cx + swatch + 6, y, label, fs=fs, kind="legend"))
            cx += swatch + 6 + T.tw(label, fs) + gap
        return out

    # ------------------------------------------------------------------ emit
    def _defs(self) -> str:
        parts = ["<defs>"]
        for k in KINDS:
            parts.append(
                f'<marker id="m{self.marker_ns}-{k}" viewBox="0 0 10 10" refX="9.2" refY="5" '
                f'markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" '
                f'orient="auto-start-reverse">'
                f'<path class="ah-{k}" d="M 0.6 0.6 L 9.4 5 L 0.6 9.4 z"/></marker>'
            )
        parts.append("</defs>")
        return "".join(parts)

    def fragment(self) -> str:
        """Everything except the ``<svg>`` wrapper, for use inside another scene.

        A nested ``<svg>`` opens a new viewport and scales the child to fit --
        which shrinks its type along with it. A ``<g>`` places it 1:1 in the
        parent's coordinate space, and the child's own ``<defs>`` travel with it
        so its markers resolve.
        """
        return self._defs() + "".join(self._parts)

    def svg(self, cls="dg", standalone=False, palette=None, svg_css=None) -> str:
        style = ""
        if standalone and palette and svg_css:
            tokens = "".join(f"--{k}:{v};" for k, v in palette.items())
            style = f"<style>:root{{{tokens}}}{svg_css}</style>"
        label = esc(self.description or self.title or "diagram")
        return (
            f'<svg class="{cls}" viewBox="0 0 {self.width:g} {self.height:g}" '
            f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="{label}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            + style + self._defs() + "".join(self._parts) + "</svg>"
        )
