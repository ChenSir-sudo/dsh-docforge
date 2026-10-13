"""Automated checking. This module is the reason the pipeline is trustworthy.

Every primitive in :mod:`docforge.scene` records its geometry; this module
inspects that record and reports concrete defects:

===============  ========  ==================================================
code             severity  meaning
===============  ========  ==================================================
text-overflow    error     a text run is wider/taller than the box holding it
box-overlap      error     two node/card/tag boxes intersect
edge-through     error     a connector runs through an unrelated node
label-collision  error     a label sits on top of a box or another label
out-of-canvas    error     an element falls outside the viewBox
degenerate-edge  error     a connector has no length
edge-crossing    warning   two connectors cross
isolated-node    warning   a node has no connectors at all
band-overlap     warning   two container bands intersect
===============  ========  ==================================================

The width estimates come from the same :mod:`docforge.text` helpers the layout
used, so these are exact checks against the layout's own model rather than
guesses.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .geom import Rect, seg_rect_hit, seg_seg_hit

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: Every code this module can emit. Kept here, not just in the docs, so that
#: ``skill-info`` can advertise them and a test can prove SKILL.md documents
#: each one — adding a check without documenting it fails the suite.
ERROR_CODES = (
    # figure geometry
    "text-overflow", "box-overlap", "edge-through", "label-collision",
    "out-of-canvas", "degenerate-edge",
    # document structure
    "unresolved-figure", "unresolved-token", "tag-imbalance", "figure-count",
    "duplicate-id", "dangling-anchor", "figure-missing", "figure-spec-missing",
    "figure-spec-invalid", "figure-render-failed", "toc-anchor-missing",
    # connector overlaps that no other rule covers
    "edge-over-label", "embed-overflow",
)
WARNING_CODES = (
    "edge-crossing", "isolated-node", "band-overlap", "no-figures",
    "short-connector", "connector-detached", "label-clearance", "edge-overlap",
)
ALL_CODES = ERROR_CODES + WARNING_CODES
_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

BOX_KINDS = ("node", "card", "tag", "cell", "bar", "funnel", "embed")
LABEL_KINDS = ("edge", "text")


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    figure: str = ""
    item: str = ""
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "figure": self.figure,
            "item": self.item,
            "message": self.message,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        where = f"[{self.figure}] " if self.figure else ""
        what = f" ({self.item})" if self.item else ""
        return f"{self.severity.upper():7} {where}{self.code}{what}: {self.message}"


# --------------------------------------------------------------------------
# Scene checks
# --------------------------------------------------------------------------
SHORT_CONNECTOR = 12.0
"""A connector shorter than this between two boxes is almost always a layout
mistake — the arrowhead swallows the line and the relationship stops reading.
It is a warning, not an error, because a deliberately tight detail view is
legitimate."""


def check_scene(scene, overflow_tol=2.0, clearance=1.0, check_crossings=True,
                check_isolated=True, check_short=True) -> list:
    """Return every finding for one scene, sorted by severity."""
    out: list = []
    items = scene.items
    boxes = [i for i in items if i.kind in BOX_KINDS]
    bands = [i for i in items if i.kind == "band"]
    canvas = Rect(0, 0, scene.width, scene.height)

    _check_bounds(scene, items, canvas, out)
    _check_text(scene, boxes + bands, overflow_tol, out)
    _check_overlap(scene, boxes, out)
    _check_band_overlap(scene, bands, out)
    _check_edges(scene, items, boxes, clearance, out)
    _check_embeds(scene, items, out)
    for child in (getattr(scene, "children", None) or {}).values():
        # A nested figure is checked in its own right, in its own coordinates.
        # Nesting is not a way to get a diagram past the validator: the findings
        # simply arrive labelled with the path they came from.
        out.extend(check_scene(child, overflow_tol, clearance, check_crossings,
                               check_isolated, check_short))
    _check_detached(scene, items, boxes, out)
    _check_labels(scene, items, boxes, bands, out)
    _check_edges_over_labels(scene, items, out)
    _check_edge_overlap(scene, items, out)
    _check_clearance(scene, items, boxes, out)
    if check_crossings and not getattr(scene, "allow_crossing", False):
        _check_crossings(scene, items, out)
    if check_isolated:
        _check_isolated(scene, items, boxes, out)
    if check_short:
        _check_short(scene, items, boxes, out)
    out.sort(key=lambda f: (_ORDER.get(f.severity, 9), f.code, f.item))
    return out


def _check_bounds(scene, items, canvas, out):
    tol = 0.75
    for it in items:
        if it.kind in ("band",):
            continue
        if not canvas.inflate(tol).contains_rect(it.bbox):
            over = _overflow_amount(it.bbox, canvas)
            out.append(Finding(
                "out-of-canvas", ERROR,
                f"{it.kind} extends {over:g}px outside the "
                f"{scene.width:g}x{scene.height:g} canvas",
                figure=scene.uid, item=it.id,
                detail={"bbox": it.bbox.as_dict(), "overflow_px": round(over, 2)},
            ))


def _overflow_amount(bbox: Rect, canvas: Rect) -> float:
    return max(
        canvas.x - bbox.x,
        canvas.y - bbox.y,
        bbox.right - canvas.right,
        bbox.bottom - canvas.bottom,
        0.0,
    )


def _check_text(scene, items, tol, out):
    """Text must fit the box that owns it."""
    for it in items:
        if not it.text_boxes:
            continue
        inner = it.inner
        if inner is None:
            continue
        lines = it.meta.get("lines") or []
        for idx, tb in enumerate(it.text_boxes):
            slack = Rect(
                inner.x - tol, inner.y - tol, inner.w + 2 * tol, inner.h + 2 * tol
            )
            if slack.contains_rect(tb):
                continue
            label = lines[idx] if idx < len(lines) else f"line {idx + 1}"
            over_x = max(tb.right - inner.right, inner.x - tb.x, 0.0)
            over_y = max(tb.bottom - inner.bottom, inner.y - tb.y, 0.0)
            out.append(Finding(
                "text-overflow", ERROR,
                f"text {label!r} does not fit its {it.kind} "
                f"(overflows {over_x:.0f}px horizontally, {over_y:.0f}px vertically)",
                figure=scene.uid, item=it.id,
                detail={
                    "text": label,
                    "text_width_px": round(tb.w, 1),
                    "box_inner_width_px": round(inner.w, 1),
                    "overflow_x_px": round(over_x, 2),
                },
            ))


def _check_overlap(scene, boxes, out):
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if not a.bbox.intersects(b.bbox):
                continue
            area = a.bbox.overlap_area(b.bbox)
            out.append(Finding(
                "box-overlap", ERROR,
                f"{a.kind} {a.meta.get('title') or a.id!r} overlaps "
                f"{b.kind} {b.meta.get('title') or b.id!r} by {area:.0f}px^2",
                figure=scene.uid, item=a.id,
                detail={"other": b.id, "overlap_area": round(area, 1),
                        "a": a.bbox.as_dict(), "b": b.bbox.as_dict()},
            ))


def _check_band_overlap(scene, bands, out):
    if getattr(scene, "allow_band_overlap", False):
        return
    for i in range(len(bands)):
        for j in range(i + 1, len(bands)):
            a, b = bands[i], bands[j]
            if a.bbox.intersects(b.bbox, pad=-1.0):
                out.append(Finding(
                    "band-overlap", WARNING,
                    f"container {a.meta.get('label') or a.id!r} overlaps "
                    f"container {b.meta.get('label') or b.id!r}",
                    figure=scene.uid, item=a.id, detail={"other": b.id},
                ))


def _check_edges(scene, items, boxes, clearance, out):
    for it in items:
        if it.kind not in ("edge", "arc"):
            continue
        if len(it.pts) < 2:
            out.append(Finding("degenerate-edge", ERROR, "connector has < 2 points",
                               figure=scene.uid, item=it.id))
            continue
        if it.meta.get("length", 1.0) < 2.0:
            out.append(Finding("degenerate-edge", ERROR,
                               "connector is shorter than 2px",
                               figure=scene.uid, item=it.id))
        if it.meta.get("decor"):
            # A decorative rule is background furniture: a gridline behind a
            # bar, a lifeline behind a message and its label. It is exempt from
            # every collision rule for the same reason -- labels carry a halo
            # that knocks the line out, so text on top of one stays readable by
            # construction. Measured as a connector it produced nothing but
            # false positives on sequence diagrams.
            continue
        # An arc must clear *every* node, including the two it joins: a ring arc
        # whose sweep is too long cuts straight through the node it is heading
        # for, and excluding its own endpoints is what used to hide that.
        attached = set() if it.kind == "arc" else {e for e in it.endpoints if e}
        pad = clearance + (4.0 if it.kind == "arc" else 0.0)
        for box in boxes:
            if box.id in attached:
                continue
            hit = _segments_hit(it.pts, box.bbox, pad)
            if hit:
                out.append(Finding(
                    "edge-through", ERROR,
                    f"connector {it.meta.get('label') or it.id!r} passes through "
                    f"{box.meta.get('title') or box.id!r} at "
                    f"({hit[0]:.0f}, {hit[1]:.0f})",
                    figure=scene.uid, item=it.id,
                    detail={"blocked_by": box.id, "at": [round(hit[0], 1), round(hit[1], 1)]},
                ))


def _segments_hit(pts, rect: Rect, clearance: float):
    target = rect.shrink_to(clearance) if clearance else rect
    if target.is_empty:
        return None
    for i in range(len(pts) - 1):
        from .geom import seg_rect_enter
        pt = seg_rect_enter(pts[i], pts[i + 1], target)
        if pt is not None:
            return pt
    return None


DETACH_TOL = 12.0
"""How far a connector endpoint may sit from the box it claims to join.

Roughly one arrowhead: within that the gap is visually filled by the marker, so
it still reads as "points at this box". Beyond it the arrow is pointing at
empty space. A warning rather than an error because a deliberate standoff is a
legitimate stylistic choice.

Sequence diagrams opt out entirely — see ``Scene.allow_detached``.
"""


def _check_embeds(scene, items, out, tol=0.5):
    """A nested figure must fit the box it was given.

    The alternative is a sub-diagram quietly cropped at the edge of its parent,
    which looks deliberate and is not.
    """
    for it in items:
        if it.kind != "embed":
            continue
        sw, sh = it.meta.get("content_size") or (0.0, 0.0)
        if sw <= 0 and sh <= 0:
            continue
        inner = it.meta.get("content_box") or it.inner
        if inner is None:
            continue
        over_x = max(0.0, sw - inner.w)
        over_y = max(0.0, sh - inner.h)
        if over_x <= tol and over_y <= tol:
            continue
        out.append(Finding(
            "embed-overflow", ERROR,
            f"nested figure {it.meta.get('label') or it.id!r} needs "
            f"{sw:.0f}x{sh:.0f} but was given {inner.w:.0f}x{inner.h:.0f}",
            figure=scene.uid, item=it.id,
            detail={"needed": [round(sw, 1), round(sh, 1)],
                    "given": [round(inner.w, 1), round(inner.h, 1)],
                    "overflow_x_px": round(over_x, 1),
                    "overflow_y_px": round(over_y, 1)},
        ))


def _check_detached(scene, items, boxes, out, tol=DETACH_TOL):
    """A connector endpoint that names a node must actually point at that node.

    Nothing else catches this: a connector ending in empty space neither
    overlaps a box nor crosses one, so it renders as an arrow pointing at
    nothing while every other check stays green.

    ``scene.allow_detached`` opts a whole scene out: in a sequence diagram the
    endpoints name a *lane*, and the arrow correctly lands on the lane's
    lifeline rather than on the header box at the top.
    """
    if getattr(scene, "allow_detached", False):
        return
    by_id = {b.id: b for b in boxes}
    for it in items:
        if len(it.pts) < 2:
            continue
        if it.kind != "edge":
            continue
        # Only the arrow end is checked. `from_id` doubles as bookkeeping —
        # a fan-out labels every tap with its shared source so the crossing
        # check knows they are one family — and those taps legitimately start
        # on a trunk in mid-air, not on the box.
        end = it.endpoints[1] if len(it.endpoints) > 1 else None
        for end, point in ((end, it.pts[-1]),):
            if not end:
                continue
            box = by_id.get(end)
            if box is None:
                continue
            gap = _point_gap(point, box.bbox)
            if gap <= tol:
                continue
            out.append(Finding(
                "connector-detached", WARNING,
                f"connector points at ({point[0]:.0f}, {point[1]:.0f}), "
                f"{gap:.0f}px away from "
                f"{box.meta.get('title') or box.id!r}, which it claims to join",
                figure=scene.uid, item=it.id,
                detail={"node": end, "gap_px": round(gap, 1),
                        "point": [round(point[0], 1), round(point[1], 1)]},
            ))


def _point_gap(point, rect) -> float:
    dx = max(rect.x - point[0], point[0] - rect.right, 0.0)
    dy = max(rect.y - point[1], point[1] - rect.bottom, 0.0)
    if dx and dy:
        import math
        return math.hypot(dx, dy)
    return dx or dy


def _check_labels(scene, items, boxes, bands, out, tol=1.5):
    """Labels must not sit on a box, on another label, or on a band caption.

    A band is a *container*: connectors and their labels are meant to live
    inside one, so the band's whole rect is the wrong thing to test against.
    Its caption is the part that cannot be shared -- a note dropped there
    covered the caption while colliding with nothing the checker could see.
    """
    labels = []
    for it in items:
        if it.kind not in LABEL_KINDS:
            continue
        for idx, tb in enumerate(it.text_boxes):
            labels.append((it, idx, tb.shrink_to(tol)))

    for it, idx, tb in labels:
        if tb.is_empty:
            continue
        lines = it.meta.get("lines") or []
        text = lines[idx] if idx < len(lines) else "?"
        for box in boxes:
            if not box.bbox.intersects(tb):
                continue
            out.append(Finding(
                "label-collision", ERROR,
                f"label {text!r} overlaps {box.kind} "
                f"{box.meta.get('title') or box.id!r}",
                figure=scene.uid, item=it.id,
                detail={"text": text, "collides_with": box.id},
            ))
        for band in bands:
            # A band is a container: connectors -- and their labels -- belong
            # inside it, so only its *header strip* is exclusive. The strip runs
            # from the band's top edge through its caption line, because a note
            # landing there collides with the rounded border and crowds the
            # caption even when it misses the glyphs themselves.
            caps = band.text_boxes
            bottom = (max(cb.bottom for cb in caps) + 6.0) if caps else band.bbox.y + 44.0
            strip = Rect(band.bbox.x, band.bbox.y, band.bbox.w,
                         max(8.0, min(bottom, band.bbox.bottom) - band.bbox.y))
            if not strip.intersects(tb):
                continue
            out.append(Finding(
                "label-collision", ERROR,
                f"label {text!r} overlaps the caption of band "
                f"{band.meta.get('label') or band.id!r}",
                figure=scene.uid, item=it.id,
                detail={"text": text, "collides_with": band.id},
            ))

    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            (a, ai, ab), (b, bi, bb) = labels[i], labels[j]
            if a is b:
                continue
            if not ab.intersects(bb):
                continue
            la = (a.meta.get("lines") or [])[ai] if ai < len(a.meta.get("lines") or []) else "?"
            lb = (b.meta.get("lines") or [])[bi] if bi < len(b.meta.get("lines") or []) else "?"
            out.append(Finding(
                "label-collision", ERROR,
                f"labels {la!r} and {lb!r} overlap each other",
                figure=scene.uid, item=a.id, detail={"other": b.id},
            ))


LABEL_CLEARANCE = 5.0
"""How much air a label needs before it reads as attached to something else."""


def _check_edges_over_labels(scene, items, out, tol=1.0):
    """A connector must not run through another element's label.

    The label halo knocks the line out where they cross, but the label still
    reads as belonging to the wrong connector — and when two labels and a line
    meet, all three become hard to read.
    """
    labels = [(i, tb) for i in items if i.kind in LABEL_KINDS for tb in i.text_boxes]
    for it in items:
        if it.kind not in ("edge", "arc") or it.meta.get("decor"):
            continue
        for lab, tb in labels:
            if lab is it:
                continue
            box = tb.shrink_to(tol)
            if box.is_empty:
                continue
            for k in range(len(it.pts) - 1):
                if not seg_rect_hit(it.pts[k], it.pts[k + 1], box, 0.0):
                    continue
                text = (lab.meta.get("lines") or ["?"])[0]
                out.append(Finding(
                    "edge-over-label", ERROR,
                    f"connector {it.meta.get('label') or it.id!r} runs through the "
                    f"label {text!r}, which belongs to another element",
                    figure=scene.uid, item=it.id,
                    detail={"label": text, "owner": lab.id},
                ))
                break


def _check_edge_overlap(scene, items, out, minimum=10.0):
    """Two connectors that share a collinear run, without sharing an endpoint.

    Fan-out from one node is a deliberate bus and is skipped; anything else
    lying on top of another line means one of them is in the wrong place.
    """
    edges = [i for i in items
             if i.kind in ("edge", "arc") and len(i.pts) >= 2
             and not i.meta.get("decor")]
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            a, b = edges[i], edges[j]
            if set(e for e in a.endpoints if e) & set(e for e in b.endpoints if e):
                continue
            if a.meta.get("decor") or b.meta.get("decor"):
                continue
            run = _collinear_run(a.pts, b.pts)
            if run < minimum:
                continue
            out.append(Finding(
                "edge-overlap", WARNING,
                f"connector {a.meta.get('label') or a.id!r} lies along "
                f"{b.meta.get('label') or b.id!r} for {run:.0f}px",
                figure=scene.uid, item=a.id,
                detail={"other": b.id, "overlap_px": round(run, 1)},
            ))


def _collinear_run(pa, pb, eps=0.75):
    """Longest stretch where two polylines coincide."""
    longest = 0.0
    for i in range(len(pa) - 1):
        (ax, ay), (bx, by) = pa[i], pa[i + 1]
        for j in range(len(pb) - 1):
            (cx, cy), (dx, dy) = pb[j], pb[j + 1]
            cross = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
            if abs(cross) > eps * max(1.0, math.hypot(bx - ax, by - ay)):
                continue
            # collinear: project b's segment onto a's and measure the overlap
            ux, uy = bx - ax, by - ay
            length = math.hypot(ux, uy) or 1.0
            ux, uy = ux / length, uy / length
            def t(px, py):
                return (px - ax) * ux + (py - ay) * uy
            t0, t1, t2, t3 = t(ax, ay), t(bx, by), t(cx, cy), t(dx, dy)
            lo = max(min(t0, t1), min(t2, t3))
            hi = min(max(t0, t1), max(t2, t3))
            if hi - lo > longest:
                # and the perpendicular distance must actually be zero
                perp = abs((cx - ax) * (-uy) + (cy - ay) * ux)
                if perp <= eps:
                    longest = hi - lo
    return longest


def _check_clearance(scene, items, boxes, out, minimum=LABEL_CLEARANCE):
    """Warn when a label is close enough to a box to read as part of it."""
    for it in items:
        if it.kind not in LABEL_KINDS or it.meta.get("decor"):
            continue
        for tb in it.text_boxes:
            for box in boxes:
                if box.bbox.intersects(tb):
                    continue                      # label-collision already reports it
                gap = _clearance(tb, box.bbox)
                if gap >= minimum:
                    continue
                text = (it.meta.get("lines") or ["?"])[0]
                out.append(Finding(
                    "label-clearance", WARNING,
                    f"label {text!r} sits {gap:.1f}px from "
                    f"{box.meta.get('title') or box.id!r}",
                    figure=scene.uid, item=it.id,
                    detail={"text": text, "near": box.id, "gap_px": round(gap, 1)},
                ))


def _check_crossings(scene, items, out, join_tol=2.0):
    edges = [i for i in items
             if i.kind in ("edge", "arc") and len(i.pts) >= 2
             and not i.meta.get("decor")]
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            a, b = edges[i], edges[j]
            if set(e for e in a.endpoints if e) & set(e for e in b.endpoints if e):
                continue
            pt = _polylines_cross(a.pts, b.pts, join_tol)
            if pt:
                out.append(Finding(
                    "edge-crossing", WARNING,
                    f"connector {a.meta.get('label') or a.id!r} crosses "
                    f"{b.meta.get('label') or b.id!r} at ({pt[0]:.0f}, {pt[1]:.0f})",
                    figure=scene.uid, item=a.id,
                    detail={"other": b.id, "at": [round(pt[0], 1), round(pt[1], 1)]},
                ))


def _polylines_cross(pa, pb, join_tol):
    for i in range(len(pa) - 1):
        for j in range(len(pb) - 1):
            pt = seg_seg_hit(pa[i], pa[i + 1], pb[j], pb[j + 1])
            if pt is None:
                continue
            if _near_vertex(pt, pa, join_tol) or _near_vertex(pt, pb, join_tol):
                continue  # a join, not a crossing
            return pt
    return None


def _near_vertex(pt, pts, tol):
    return any(abs(pt[0] - p[0]) <= tol and abs(pt[1] - p[1]) <= tol for p in pts)


def _check_short(scene, items, boxes, out, minimum=SHORT_CONNECTOR):
    """Flag connectors whose visible run between two boxes is too small.

    The geometry validator can prove boxes do not overlap; only this can notice
    that they are stacked so tightly the arrow between them has nowhere to go.
    """
    by_id = {b.id: b for b in boxes}
    for it in items:
        if it.kind not in ("edge", "arc") or it.meta.get("length") is None:
            continue
        if it.meta.get("routed"):
            # A dependency arrow goes around its bars on purpose; the gap
            # between them is not what makes it readable.
            continue
        ends = [e for e in it.endpoints if e]
        if len(ends) != 2:
            continue
        a, b = by_id.get(ends[0]), by_id.get(ends[1])
        if a is None or b is None:
            continue
        if a.bbox.intersects(b.bbox):
            continue                      # box-overlap already reports this
        gap = _clearance(a.bbox, b.bbox)
        if gap < minimum:
            out.append(Finding(
                "short-connector", WARNING,
                f"only {gap:.0f}px between "
                f"{a.meta.get('title') or a.id!r} and "
                f"{b.meta.get('title') or b.id!r}; the connector "
                f"will not read",
                figure=scene.uid, item=it.id,
                detail={"from": a.id, "to": b.id, "gap_px": round(gap, 1),
                        "advice": "open the gap or drop this connector"},
            ))


def _clearance(a, b) -> float:
    """Shortest straight-line separation between two non-overlapping boxes."""
    dx = max(a.x - b.right, b.x - a.right, 0.0)
    dy = max(a.y - b.bottom, b.y - a.bottom, 0.0)
    if dx and dy:
        import math
        return math.hypot(dx, dy)
    return dx or dy


def _check_isolated(scene, items, boxes, out):
    allowed = set(getattr(scene, "allow_isolated", ()) or ())
    used = set()
    for it in items:
        if it.kind in ("edge", "arc"):
            used.update(e for e in it.endpoints if e)
    for box in boxes:
        if box.id not in used and box.id not in allowed:
            out.append(Finding(
                "isolated-node", WARNING,
                f"{box.kind} {box.meta.get('title') or box.id!r} has no connector",
                figure=scene.uid, item=box.id,
            ))


# --------------------------------------------------------------------------
# Document checks
# --------------------------------------------------------------------------
def check_document(html: str, figure_ids=(), toc_ids=()) -> list:
    """Structural checks on the assembled single-file HTML."""
    out: list = []

    leftover = re.findall(r"<!--\s*FIG:[^>]*-->", html)
    if leftover:
        out.append(Finding("unresolved-figure", ERROR,
                           f"{len(leftover)} figure placeholder(s) were never "
                           f"resolved, e.g. {leftover[0][:60]}"))
    leftover = re.findall(r"\{\{[^}]{0,40}\}\}", html)
    if leftover:
        out.append(Finding("unresolved-token", ERROR,
                           f"{len(leftover)} template token(s) left in output, "
                           f"e.g. {leftover[0][:60]}"))

    figures = len(re.findall(r"<figure[ >]", html))
    closes = len(re.findall(r"</figure>", html))
    if figures != closes:
        out.append(Finding("tag-imbalance", ERROR,
                           f"<figure> opened {figures}x but closed {closes}x"))
    if figure_ids and figures != len(figure_ids):
        out.append(Finding("figure-count", ERROR,
                           f"document contains {figures} figures but "
                           f"{len(figure_ids)} were declared"))

    for tag in ("div", "pre", "table", "ul", "ol", "p", "h1", "h2", "h3"):
        o = len(re.findall(rf"<{tag}[ >]", html))
        c = len(re.findall(rf"</{tag}>", html))
        if o != c:
            out.append(Finding("tag-imbalance", ERROR,
                               f"<{tag}> opened {o}x but closed {c}x"))

    ids = re.findall(r'''\sid=["\']([^"\']+)["\']''', html)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        out.append(Finding("duplicate-id", ERROR,
                           f"duplicate element ids: {', '.join(dupes[:5])}"))

    for anchor in set(re.findall(r'''href=["\']#([^"\']+)["\']''', html)):
        if anchor not in ids:
            out.append(Finding("dangling-anchor", ERROR,
                               f"link target #{anchor} does not exist"))

    if "<svg" not in html:
        out.append(Finding("no-figures", WARNING,
                           "document contains no inline SVG figure"))

    idset = set(ids)
    for tid in toc_ids:
        if tid not in idset:
            out.append(Finding("toc-anchor-missing", ERROR,
                               f"table-of-contents entry #{tid} has no heading"))
    for fid in figure_ids:
        if f"fig-{fid}" not in idset and fid not in idset:
            out.append(Finding("figure-missing", ERROR,
                               f"figure {fid!r} was declared but is not "
                               f"referenced from the document"))
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def worst(findings) -> str:
    if any(f.severity == ERROR for f in findings):
        return ERROR
    if any(f.severity == WARNING for f in findings):
        return WARNING
    return "ok"


def should_fail(findings, fail_on="error") -> bool:
    if fail_on in ("none", "off", None):
        return False
    if fail_on == "warning":
        return bool(findings)
    return any(f.severity == ERROR for f in findings)


def summarize(findings) -> dict:
    by_code: dict = {}
    for f in findings:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    return {
        "status": worst(findings),
        "total": len(findings),
        "errors": sum(1 for f in findings if f.severity == ERROR),
        "warnings": sum(1 for f in findings if f.severity == WARNING),
        "by_code": dict(sorted(by_code.items())),
    }


def format_text(findings, limit=40) -> str:
    if not findings:
        return "ok — no findings"
    lines = []
    for f in findings[:limit]:
        lines.append(str(f))
    if len(findings) > limit:
        lines.append(f"... and {len(findings) - limit} more")
    stats = summarize(findings)
    lines.append(
        f"-- {stats['errors']} error(s), {stats['warnings']} warning(s), "
        f"{stats['total']} total"
    )
    return "\n".join(lines)
