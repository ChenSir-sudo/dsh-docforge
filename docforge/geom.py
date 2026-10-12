"""Geometry primitives used for layout and for automated diagram checking.

Nothing here knows about SVG. It is deliberately a tiny, testable geometry kit:
the validator is only as trustworthy as these routines.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-9


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    # -- derived ---------------------------------------------------------
    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def is_empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    # -- operations ------------------------------------------------------
    def inflate(self, d: float) -> "Rect":
        return Rect(self.x - d, self.y - d, self.w + 2 * d, self.h + 2 * d)

    def shrink_to(self, d: float) -> "Rect":
        return self.inflate(-d)

    def offset(self, dx: float, dy: float) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def intersects(self, other: "Rect", pad: float = 0.0) -> bool:
        if pad:
            other = other.inflate(pad)
        return not (
            self.right <= other.x + EPS
            or other.right <= self.x + EPS
            or self.bottom <= other.y + EPS
            or other.bottom <= self.y + EPS
        )

    def overlap_area(self, other: "Rect") -> float:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0.0, w) * max(0.0, h)

    def contains_point(self, px: float, py: float, pad: float = 0.0) -> bool:
        return (
            self.x - pad <= px <= self.right + pad
            and self.y - pad <= py <= self.bottom + pad
        )

    def contains_rect(self, other: "Rect", pad: float = 0.0) -> bool:
        r = self.inflate(pad)
        return (
            other.x >= r.x - EPS
            and other.y >= r.y - EPS
            and other.right <= r.right + EPS
            and other.bottom <= r.bottom + EPS
        )

    def union(self, other: "Rect") -> "Rect":
        x0, y0 = min(self.x, other.x), min(self.y, other.y)
        x1, y1 = max(self.right, other.right), max(self.bottom, other.bottom)
        return Rect(x0, y0, x1 - x0, y1 - y0)

    def intersection(self, other: "Rect") -> "Rect":
        x0, y0 = max(self.x, other.x), max(self.y, other.y)
        x1, y1 = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))

    def as_dict(self) -> dict:
        return {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "w": round(self.w, 2),
            "h": round(self.h, 2),
        }

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Rect({self.x:g},{self.y:g},{self.w:g},{self.h:g})"


def rect_from_points(pts) -> Rect:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


# --------------------------------------------------------------------------
# Segment tests
# --------------------------------------------------------------------------
def _orient(ax, ay, bx, by, cx, cy) -> float:
    """Twice the signed area of triangle (a, b, c). >0 means c is left of a->b."""
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _sign(v: float) -> int:
    if v > EPS:
        return 1
    if v < -EPS:
        return -1
    return 0


def _on_seg(ax, ay, bx, by, cx, cy) -> bool:
    """Is c, already known collinear with a-b, inside the segment?"""
    return (
        min(ax, bx) - EPS <= cx <= max(ax, bx) + EPS
        and min(ay, by) - EPS <= cy <= max(ay, by) + EPS
    )


def seg_seg_hit(a0, a1, b0, b1):
    """Intersection point of segments a and b, or ``None``.

    Collinear overlaps report the first shared endpoint; touching endpoints
    are reported as that endpoint.
    """
    ax, ay = a0
    bx, by = a1
    cx, cy = b0
    dx, dy = b1

    o1 = _orient(ax, ay, bx, by, cx, cy)
    o2 = _orient(ax, ay, bx, by, dx, dy)
    o3 = _orient(cx, cy, dx, dy, ax, ay)
    o4 = _orient(cx, cy, dx, dy, bx, by)

    s1, s2, s3, s4 = _sign(o1), _sign(o2), _sign(o3), _sign(o4)

    if s1 == 0 and s2 == 0 and s3 == 0 and s4 == 0:
        # collinear: report the first coincident endpoint
        for p in (a0, a1):
            if _on_seg(cx, cy, dx, dy, p[0], p[1]):
                return (float(p[0]), float(p[1]))
        for p in (b0, b1):
            if _on_seg(ax, ay, bx, by, p[0], p[1]):
                return (float(p[0]), float(p[1]))
        return None

    if s1 != s2 and s3 != s4:
        denom = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
        if abs(denom) < EPS:
            return None
        t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denom
        return (ax + t * (bx - ax), ay + t * (by - ay))

    # touching endpoints / T junctions: the endpoint with zero orientation must
    # actually lie *on* the other segment, not merely on its infinite line.
    if s1 == 0 and _on_seg(ax, ay, bx, by, cx, cy):
        return (float(cx), float(cy))
    if s2 == 0 and _on_seg(ax, ay, bx, by, dx, dy):
        return (float(dx), float(dy))
    if s3 == 0 and _on_seg(cx, cy, dx, dy, ax, ay):
        return (float(ax), float(ay))
    if s4 == 0 and _on_seg(cx, cy, dx, dy, bx, by):
        return (float(bx), float(by))
    return None


def seg_rect_hit(p0, p1, rect: Rect, pad: float = 0.0) -> bool:
    """Does segment p0-p1 touch *rect* (optionally grown by *pad*)?"""
    r = rect.inflate(pad) if pad else rect
    if r.is_empty:
        return False
    corners = [
        (r.x, r.y),
        (r.right, r.y),
        (r.right, r.bottom),
        (r.x, r.bottom),
    ]
    if r.contains_point(p0[0], p0[1]) or r.contains_point(p1[0], p1[1]):
        return True
    for i in range(4):
        if seg_seg_hit(p0, p1, corners[i], corners[(i + 1) % 4]):
            return True
    return False


def seg_rect_enter(p0, p1, rect: Rect):
    """First point where segment p0-p1 enters *rect*, or ``None``."""
    if rect.contains_point(p0[0], p0[1]):
        return (float(p0[0]), float(p0[1]))
    corners = [(rect.x, rect.y), (rect.right, rect.y),
               (rect.right, rect.bottom), (rect.x, rect.bottom)]
    best = None
    for i in range(4):
        pt = seg_seg_hit(p0, p1, corners[i], corners[(i + 1) % 4])
        if pt is None:
            continue
        d = math.hypot(pt[0] - p0[0], pt[1] - p0[1])
        if best is None or d < best[0]:
            best = (d, pt)
    return best[1] if best else None


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------
def arc_points(cx, cy, rx, ry, a0, a1, steps: int = 32):
    """Sample an elliptical arc (angles in degrees, clockwise) into points."""
    if steps < 2:
        steps = 2
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


def rounded_path(pts, r: float = 11.0) -> str:
    """Orthogonal polyline with rounded corners, as an SVG path ``d``."""
    pts = [(float(a), float(b)) for a, b in pts]
    if len(pts) < 2:
        return ""
    if len(pts) == 2:
        return f"M {pts[0][0]:g} {pts[0][1]:g} L {pts[1][0]:g} {pts[1][1]:g}"
    d = [f"M {pts[0][0]:g} {pts[0][1]:g}"]
    for i in range(1, len(pts) - 1):
        px, py = pts[i - 1]
        cx, cy = pts[i]
        nx, ny = pts[i + 1]
        rr = r
        for ax, ay, bx, by in ((px, py, cx, cy), (nx, ny, cx, cy)):
            rr = min(rr, math.hypot(bx - ax, by - ay) / 2.0)
        ax, ay = _back(px, py, cx, cy, rr)
        bx, by = _back(nx, ny, cx, cy, rr)
        d.append(f"L {ax:.1f} {ay:.1f}")
        d.append(f"Q {cx:g} {cy:g} {bx:.1f} {by:.1f}")
    d.append(f"L {pts[-1][0]:g} {pts[-1][1]:g}")
    return " ".join(d)


def _back(ax, ay, bx, by, r):
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.0
    return bx - dx / length * r, by - dy / length * r


def polyline_length(pts) -> float:
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )


def point_on_polyline(pts, t: float):
    """Point at fraction *t* along a polyline (0..1)."""
    total = polyline_length(pts)
    if total <= 0:
        return pts[0]
    want = total * max(0.0, min(1.0, t))
    walked = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if walked + seg >= want:
            k = (want - walked) / seg if seg else 0.0
            return (
                pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k,
                pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k,
            )
        walked += seg
    return pts[-1]
