"""Layout engines.

An engine does **not** draw. It returns a :class:`Plan` — where every node goes,
which connectors join them, and which containers wrap which members — and
:func:`render` then draws the plan in a fixed order (containers, nodes,
connectors, annotations).

Splitting it that way buys two things. Containers can be sized from the content
they wrap instead of being hand-measured, and every coordinate in a figure comes
from one place, which is what makes the geometry validator meaningful.

Engines own *placement*. The spec owns *content*. Where an engine cannot know
better, a node may carry explicit ``x``/``y``/``w``/``h`` and a connector may
carry explicit ``pts`` — the escape hatch that keeps hand-tuned diagrams
possible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import text as T
from .geom import Rect, point_on_polyline
from .scene import Scene

# --------------------------------------------------------------------------
# Plan model
# --------------------------------------------------------------------------
@dataclass
class Connector:
    pts: list
    kind: str = "line"
    label: str = None
    from_id: str = None
    to_id: str = None
    dashed: bool = False
    lx: float = None
    ly: float = None
    anchor: str = "middle"
    head: bool = True
    tail: bool = False
    r: float = 11.0
    lfs: float = 11.5
    label_gap: float = 9.0
    auto_label: bool = True
    snap: bool = False


@dataclass
class Band:
    x: float
    y: float
    w: float
    h: float
    label: str = None
    sub: str = None
    kind: str = "default"
    rx: float = 16.0
    fs: float = 13.0
    dash: bool = False
    label_at: tuple = None


@dataclass
class Annotation:
    kind: str          # text | tag | legend | line
    args: dict = field(default_factory=dict)


@dataclass
class Plan:
    placements: dict = field(default_factory=dict)   # node id -> Rect
    allow_detached: bool = False                     # see validate._check_detached
    allow_crossing: bool = False                     # see validate._check_crossings
    connectors: list = field(default_factory=list)
    bands: list = field(default_factory=list)
    annotations: list = field(default_factory=list)
    size: tuple = None
    margin: float = 24.0

    def rect(self, node_id: str) -> Rect:
        return self.placements[node_id]

    def union(self, ids) -> Rect:
        rects = [self.placements[i] for i in ids if i in self.placements]
        if not rects:
            return Rect(0, 0, 0, 0)
        out = rects[0]
        for r in rects[1:]:
            out = out.union(r)
        return out


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------
NODE_PAD = 18.0
NODE_VPAD = 14.0
MIN_W = 88.0
MAX_W = 460.0


def node_size(n: dict, fs=None, subfs=None, pad=NODE_PAD, vpad=NODE_VPAD):
    """Intrinsic size of a node, derived from its text.

    A node marked ``as_card`` delegates to :func:`card_size`, so every engine
    that asks "how big is this?" gets the right answer without having to know
    that cards exist. (Measuring a card with the node formula leaves it one
    ``items`` line too short, which surfaces as ``text-overflow`` on its own
    last row.)
    """
    if n.get("as_card"):
        return card_size(n)
    fs = float(n.get("fs", fs or 15.0))
    subfs = float(n.get("subfs", subfs or 11.5))
    subs = _subs(n)
    widths = [T.tw(str(n.get("title", "")), fs)]
    widths += [T.tw(s, subfs) for s in subs]
    w = max(widths) + 2 * pad
    h = (fs + 6.0) + (subfs + 4.5) * len(subs) + 2 * vpad
    w = max(n.get("min_width", MIN_W), min(n.get("max_width", MAX_W), w))
    return float(n.get("width") or w), float(n.get("height") or h)


def card_size(c: dict):
    fs = float(c.get("fs", 14.0))
    subfs = float(c.get("subfs", 10.5))
    ifs = float(c.get("ifs", 11.5))
    gap = c.get("gap") or (ifs + 6.5)
    pad = float(c.get("pad", 15.0))
    widths = [T.tw(str(c.get("title", "")), fs)]
    if c.get("accent"):
        widths.append(T.tw(str(c["accent"]), subfs) * 2)
    if c.get("sub"):
        widths.append(T.tw(str(c["sub"]), subfs))
    measure = T.tw_mono if c.get("item_code") else T.tw
    widths += [measure(str(i), ifs) for i in c.get("items", [])]
    w = max(widths) + 2 * pad
    h = 23.0
    if c.get("sub"):
        h += subfs + 6.0
    h += 12.0
    h += gap * len(c.get("items", []))
    h += 14.0
    return float(c.get("width") or w), float(c.get("height") or h)


def _subs(n: dict) -> list:
    sub = n.get("sub")
    if not sub:
        return []
    return [str(s) for s in (sub if isinstance(sub, (list, tuple)) else [sub])]


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
def port(r: Rect, side: str, inset: float = 0.0):
    if side == "left":
        return (r.x, r.cy)
    if side == "right":
        return (r.right, r.cy)
    if side == "top":
        return (r.cx, r.y)
    return (r.cx, r.bottom)


def facing_side(a: Rect, b: Rect) -> str:
    """Which side of *a* points at *b*."""
    hgap = max(a.x - b.right, b.x - a.right, 0.0)
    vgap = max(a.y - b.bottom, b.y - a.bottom, 0.0)
    dx = b.cx - a.cx
    dy = b.cy - a.cy
    if hgap > 0 and hgap >= vgap:
        return "right" if dx > 0 else "left"
    if vgap > 0:
        return "bottom" if dy > 0 else "top"
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "bottom" if dy > 0 else "top"


PORT_INSET = 16.0
PORT_SPACING = 30.0


def spread_ports(items, box_of, side_of, other_of, inset=PORT_INSET,
                 spacing=PORT_SPACING):
    """Give connectors sharing one side of a box their own port.

    *items* is the list of connectors; *box_of(item)* is the Rect whose side is
    shared, *side_of(item)* is that side, and *other_of(item)* is the Rect at
    the far end, used to order the ports so the lines do not braid.

    Returns a list of offsets, index-aligned with *items*.
    """
    groups = {}
    for idx, it in enumerate(items):
        groups.setdefault((id(box_of(it)), side_of(it)), []).append(idx)

    offsets = [0.0] * len(items)
    for (_, side), idxs in groups.items():
        if len(idxs) < 2:
            continue
        box = box_of(items[idxs[0]])
        vertical = side in ("left", "right")
        span = (box.h if vertical else box.w) - 2 * inset
        step = min(spacing, span / (len(idxs) - 1)) if span > 0 else 0.0
        ordered = sorted(idxs, key=lambda i: (other_of(items[i]).cy if vertical
                                              else other_of(items[i]).cx))
        mid = (len(ordered) - 1) / 2.0
        for rank, i in enumerate(ordered):
            offsets[i] = (rank - mid) * step
    return offsets


def opposite(side: str) -> str:
    return {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[side]


def route(a: Rect, b: Rect, out=None, into=None, channel=None, off=0.0,
          in_off=0.0):
    """An orthogonal polyline from rect *a* to rect *b*.

    ``channel`` pins the middle coordinate of a Z-shaped run. ``off`` and
    ``in_off`` slide the exit and entry ports along their sides — that is how a
    fan-out gets distinct exits, and how a fan-in gets distinct arrowheads
    instead of stacking them on one point.
    """
    out = out or facing_side(a, b)
    into = into or facing_side(b, a)
    p0 = list(port(a, out))
    p1 = list(port(b, into))
    if out in ("left", "right"):
        p0[1] += off
    else:
        p0[0] += off
    if into in ("left", "right"):
        p1[1] += in_off
    else:
        p1[0] += in_off

    if out in ("left", "right") and into in ("left", "right"):
        if abs(p0[1] - p1[1]) < 0.5:
            return [tuple(p0), tuple(p1)]
        mid = channel if channel is not None else (p0[0] + p1[0]) / 2.0
        return [tuple(p0), (mid, p0[1]), (mid, p1[1]), tuple(p1)]
    if out in ("top", "bottom") and into in ("top", "bottom"):
        if abs(p0[0] - p1[0]) < 0.5:
            return [tuple(p0), tuple(p1)]
        mid = channel if channel is not None else (p0[1] + p1[1]) / 2.0
        return [tuple(p0), (p0[0], mid), (p1[0], mid), tuple(p1)]
    if out in ("left", "right"):
        return [tuple(p0), (p1[0], p0[1]), tuple(p1)]
    return [tuple(p0), (p0[0], p1[1]), tuple(p1)]


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
LAYOUTS: dict = {}


def layout(name):
    def deco(fn):
        LAYOUTS[name] = fn
        return fn
    return deco


def engine_for(spec) -> str:
    return spec.get("layout") or "free"


# --------------------------------------------------------------------------
# Engines
# --------------------------------------------------------------------------
@layout("pipeline")
def _pipeline(spec) -> Plan:
    """A horizontal chain, optionally wrapping into a serpentine."""
    plan = Plan()
    opts = spec.get("options", {})
    nodes = spec["nodes"]
    ids = [n["id"] for n in nodes]
    fs = opts.get("fs", 15.0)
    subfs = opts.get("subfs", 11.5)
    margin = opts.get("margin", 36.0)
    width = opts.get("width", (spec.get("size") or [1200])[0])
    gap = opts.get("gap", 36.0)
    rows_limit = opts.get("rows")

    sizes = {}
    for n in nodes:
        w, h = node_size(n, fs, subfs)
        if opts.get("uniform_height"):
            h = opts["uniform_height"]
        sizes[n["id"]] = [w, h]

    usable = width - 2 * margin
    # how many fit per row?
    per_row = len(ids)
    if rows_limit:
        per_row = max(1, math.ceil(len(ids) / rows_limit))
    while per_row > 1:
        need = sum(sizes[i][0] for i in ids[:per_row]) + gap * (per_row - 1)
        if need <= usable:
            break
        per_row -= 1
    per_row = max(1, per_row)

    rows = [ids[i:i + per_row] for i in range(0, len(ids), per_row)]
    # stretch each row to fill the usable width
    row_h = max(sizes[i][1] for i in ids)
    v_gap = opts.get("v_gap", 96.0)
    top = opts.get("y", margin + 8)

    for ri, row in enumerate(rows):
        n = len(row)
        if opts.get("stretch", True) and n > 1:
            total = sum(sizes[i][0] for i in row)
            slack = usable - total
            g = min(opts.get("max_gap", 64.0), max(gap, slack / (n - 1))) if slack > 0 else gap
            extra = (slack - g * (n - 1)) / n if slack > g * (n - 1) else 0.0
        else:
            g, extra = gap, 0.0
        wsum = sum(sizes[i][0] + extra for i in row) + g * (n - 1)
        x = margin + max(0.0, (usable - wsum) / 2.0)
        y = top + ri * (row_h + v_gap)
        for nid in row:
            w, h = sizes[nid]
            w += extra
            plan.placements[nid] = Rect(x, y + (row_h - h) / 2.0, w, h)
            x += w + g

    ek = opts.get("edge_kind", "line")
    for ri, row in enumerate(rows):
        for i in range(len(row) - 1):
            a, b = plan.placements[row[i]], plan.placements[row[i + 1]]
            plan.connectors.append(Connector(
                [port(a, "right"), port(b, "left")], kind=opts.get("arrow_kind", ek),
                from_id=row[i], to_id=row[i + 1],
                label=_edge_label(spec, row[i], row[i + 1]),
                label_gap=16.0,
            ))
        if ri + 1 < len(rows):
            a = plan.placements[row[-1]]
            b = plan.placements[rows[ri + 1][0]]
            ch = a.bottom + v_gap * 0.45
            plan.connectors.append(Connector(
                [(a.cx, a.bottom), (a.cx, ch), (margin - 20, ch),
                 (margin - 20, b.cy), (b.x - 4, b.cy)],
                kind=opts.get("wrap_kind", "slate"), dashed=True, r=14,
            ))
    return plan


@layout("fan")
def _fan(spec) -> Plan:
    """A chain leading into a hub that fans out to N stacked targets.

    ``options.prefix`` is an optional list of node ids laid out left-to-right
    and chained into ``options.source``; ``options.targets`` stack vertically on
    the right and share one riser.
    """
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 50.0)
    fs, subfs = opts.get("fs", 14.5), opts.get("subfs", 10.5)
    by_id = {n["id"]: n for n in spec["nodes"]}
    prefix = list(opts.get("prefix", []))
    source = opts["source"]
    targets = list(opts["targets"])

    tgap = opts.get("target_gap", 20.0)
    sizes = {t: node_size(by_id[t], fs, subfs) for t in targets}
    stack_h = sum(sizes[t][1] for t in targets) + tgap * max(0, len(targets) - 1)
    top = opts.get("y", 20.0)
    centre = top + stack_h / 2.0

    # The composition is chain + reach + target column, and it is *centred* on
    # the canvas. Pinning the target column to the right (and the chain to the
    # left) leaves whatever space is left over as a long, purposeless run in the
    # middle; the reach is a fixed visual distance, not a remainder.
    gap = opts.get("chain_gap", 44.0)
    reach = opts.get("reach", 130.0)
    riser_gap = opts.get("riser_gap", 80.0)
    chain_ids = prefix + [source]
    chain_sizes = [node_size(by_id[n], fs, subfs) for n in chain_ids]
    chain_w = (sum(w for w, _ in chain_sizes)
               + gap * (len(chain_ids) - 1))
    tw_max = max(sizes[t][0] for t in targets)
    span = reach + riser_gap
    content = chain_w + span + tw_max
    left = margin + max(0.0, (width - 2 * margin - content) / 2.0)
    tx = left + chain_w + span
    riser = tx - riser_gap

    y = top
    for t in targets:
        w, h = sizes[t]
        plan.placements[t] = Rect(tx, y, w, h)
        y += h + tgap

    sx = left
    for nid, (w, h) in zip(chain_ids[:-1], chain_sizes[:-1]):
        plan.placements[nid] = Rect(sx, centre - h / 2.0, w, h)
        sx += w + gap
    sw, sh = chain_sizes[-1]
    plan.placements[source] = Rect(sx, centre - sh / 2.0, sw, sh)

    chain = prefix + [source]
    for i in range(len(chain) - 1):
        a, b = plan.placements[chain[i]], plan.placements[chain[i + 1]]
        edge = _edge_between(spec, chain[i], chain[i + 1]) or {}
        plan.connectors.append(Connector(
            [port(a, "right"), port(b, "left")], kind=opts.get("chain_kind", "line"),
            from_id=chain[i], to_id=chain[i + 1],
            label=edge.get("label"),
            lx=edge.get("lx", (a.right + b.x) / 2.0),
            ly=edge.get("ly", centre - 17.0),
            anchor=edge.get("anchor", "middle"),
        ))

    # fan-out
    src = plan.placements[source]
    kind = opts.get("edge_kind", "teal")
    first = plan.placements[targets[0]]
    labels = opts.get("labels", {})
    plan.connectors.append(Connector(
        [(src.right, src.cy), (riser, src.cy), (riser, first.cy), (first.x - 4, first.cy)],
        kind=kind, from_id=source, to_id=targets[0], r=10,
        label=labels.get(targets[0]),
        lx=(riser + first.x) / 2.0, ly=first.cy - opts.get("label_gap", 15.0),
        anchor="middle",
    ))
    for t in targets[1:]:
        r = plan.placements[t]
        plan.connectors.append(Connector(
            [(riser, r.cy), (r.x - 4, r.cy)], kind=kind,
            from_id=source, to_id=t, r=8,
            label=labels.get(t), lx=(riser + r.x) / 2.0,
            ly=r.cy - opts.get("label_gap", 15.0), anchor="middle",
        ))
    plan.connectors.append(Connector(
        [(riser, src.cy), (riser, plan.placements[targets[-1]].cy)],
        kind=kind, head=False, r=0, from_id=source,
    ))
    return plan


@layout("dag")
def _dag(spec) -> Plan:
    """A layered directed graph: any shape of edges, no serpentine assumptions.

    Nodes are assigned to columns by longest path from a source, so a diamond
    puts its branches side by side and rejoins them. Edges are routed with
    :func:`route`; where the router has to choose, ``options.channel`` pins the
    middle coordinate and a crossing is reported by the validator rather than
    silently drawn.
    """
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 60.0)
    fs, subfs = opts.get("fs", 14.5), opts.get("subfs", 10.5)
    nodes = spec.get("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    edges = [e for e in spec.get("edges", []) if e.get("from") and e.get("to")]

    # longest-path layering, tolerant of cycles
    layer = {n["id"]: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for e in edges:
            want = layer.get(e["from"], 0) + 1
            if want > layer.get(e["to"], 0):
                layer[e["to"]] = want
                changed = True
        if not changed:
            break
    if opts.get("center_sinks"):          # pull leaves towards the last column
        deepest = max(layer.values()) if layer else 0
        has_out = {e["from"] for e in edges}
        for n in nodes:
            if n["id"] not in has_out:
                layer[n["id"]] = deepest

    layers = {}
    for n in nodes:
        layers.setdefault(layer[n["id"]], []).append(n["id"])
    order = sorted(layers)
    for k in order:
        layers[k].sort(key=lambda i: [n["id"] for n in nodes].index(i))

    # column geometry
    col_w = {}
    for k in order:
        col_w[k] = max(node_size(by_id[i], fs, subfs)[0] for i in layers[k])
    gap_x = opts.get("gap_x", 70.0)
    total_w = sum(col_w[k] for k in order) + gap_x * (len(order) - 1)
    x = margin + max(0.0, (width - 2 * margin - total_w) / 2.0)
    col_x = {}
    for k in order:
        col_x[k] = x
        x += col_w[k] + gap_x

    gap_y = opts.get("gap_y", 26.0)
    tallest = max(
        sum(node_size(by_id[i], fs, subfs)[1] for i in layers[k])
        + gap_y * (len(layers[k]) - 1)
        for k in order
    )
    top = opts.get("y", 24.0)
    for k in order:
        col_h = (sum(node_size(by_id[i], fs, subfs)[1] for i in layers[k])
                 + gap_y * (len(layers[k]) - 1))
        y = top + (tallest - col_h) / 2.0
        for nid in layers[k]:
            w, h = node_size(by_id[nid], fs, subfs)
            plan.placements[nid] = Rect(col_x[k] + (col_w[k] - w) / 2.0, y, w, h)
            y += h + gap_y

    # An edge that skips a column would run straight through whatever sits in
    # the column between. Send those along a bus beneath the whole graph, where
    # nothing can be in the way, instead of pretending a straight run is fine.
    spanning = [e for e in edges
                if abs(layer.get(e["to"], 0) - layer.get(e["from"], 0)) > 1]
    bus_y = None
    if spanning:
        deepest = max(r.bottom for r in plan.placements.values())
        bus_y = deepest + opts.get("bus_gap", 40.0)

    routes = []
    for e in edges:
        a, b = plan.placements[e["from"]], plan.placements[e["to"]]
        routes.append({
            "e": e, "a": a, "b": b,
            "out": e.get("out") or facing_side(a, b),
            "into": e.get("into") or facing_side(b, a),
        })
    out_off = spread_ports(routes, lambda r: r["a"], lambda r: r["out"],
                           lambda r: r["b"])
    in_off = spread_ports(routes, lambda r: r["b"], lambda r: r["into"],
                          lambda r: r["a"])

    channel = opts.get("channel")
    for r, oo, io in zip(routes, out_off, in_off):
        e, a, b = r["e"], r["a"], r["b"]
        pts = e.get("pts")
        if pts is None and bus_y is not None and e in spanning:
            # drop into the gutter beside the source column, never through it
            la = layer.get(e["from"], 0)
            drop_x = col_x[la] + col_w[la] + gap_x / 2.0
            pts = [(a.right, a.cy), (drop_x, a.cy), (drop_x, bus_y),
                   (b.cx, bus_y), (b.cx, b.bottom + 4)]
        if pts is None:
            pts = route(a, b, out=r["out"], into=r["into"],
                        channel=channel if len(order) > 2 else None,
                        off=e.get("off", 0.0) + oo,
                        in_off=e.get("in_off", 0.0) + io)
        plan.connectors.append(Connector(
            pts, kind=e.get("kind", "line"), label=e.get("label"),
            from_id=e["from"], to_id=e["to"], dashed=e.get("dashed", False),
            lx=e.get("lx"), ly=e.get("ly"), anchor=e.get("anchor", "middle"),
            r=12.0, head=e.get("head", True),
        ))
    if bus_y is not None:
        plan.size = (width, bus_y + 34.0)
    return plan


@layout("grid")
def _grid(spec) -> Plan:
    """Cards or nodes laid out in a fixed-column grid."""
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 48.0)
    cols = int(opts.get("cols", 4))
    gap_x = opts.get("gap_x", 16.0)
    gap_y = opts.get("gap_y", 16.0)
    as_card = opts.get("as_card", False)
    items = spec.get("items") or spec.get("nodes") or []
    origin_y = opts.get("y", 20.0)

    sizes = []
    for it in items:
        sizes.append(card_size(it) if as_card else node_size(it, opts.get("fs", 13.0),
                                                             opts.get("subfs", 10.5)))
    cw = max(s[0] for s in sizes)
    ch = max(s[1] for s in sizes)
    usable = width - 2 * margin
    if opts.get("fill", True):
        cw = (usable - gap_x * (cols - 1)) / cols
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        plan.placements[it["id"]] = Rect(
            margin + c * (cw + gap_x), origin_y + r * (ch + gap_y), cw, ch
        )
    return plan


@layout("layers")
def _layers(spec) -> Plan:
    """Stacked containers, each holding a row (or grid) of nodes."""
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 36.0)
    inner = opts.get("inner_pad", 22.0)
    fs, subfs = opts.get("fs", 14.5), opts.get("subfs", 10.5)
    band_gap = opts.get("band_gap", 40.0)
    label_h = opts.get("label_h", 44.0)
    by_id = {n["id"]: n for n in spec["nodes"]}
    top = opts.get("y", 20.0)
    y = top

    for grp in spec.get("groups", []):
        ids = grp["nodes"]
        cols = int(grp.get("cols", len(ids)))
        gap_x = grp.get("gap_x", opts.get("gap_x", 24.0))
        usable = width - 2 * margin - 2 * inner
        rows = [ids[i:i + cols] for i in range(0, len(ids), cols)]
        cw = (usable - gap_x * (cols - 1)) / cols if cols > 1 else usable
        row_sizes = []
        for row in rows:
            row_sizes.append(max(node_size(by_id[i], fs, subfs)[1] for i in row))
        content_h = sum(row_sizes) + opts.get("row_gap", 14.0) * (len(rows) - 1)
        band_y = y
        band_h = label_h + content_h + inner
        plan.bands.append(Band(
            margin, band_y, width - 2 * margin, band_h,
            label=grp.get("label"), sub=grp.get("sub"), kind=grp.get("kind", "default"),
            fs=grp.get("fs", 13.0),
        ))
        cy = band_y + label_h
        for ri, row in enumerate(rows):
            rh = row_sizes[ri]
            for ci, nid in enumerate(row):
                w, h = node_size(by_id[nid], fs, subfs)
                w = cw
                x = margin + inner + ci * (cw + gap_x)
                plan.placements[nid] = Rect(x, cy + (rh - h) / 2.0, w, h)
            cy += rh + opts.get("row_gap", 14.0)
        # chain arrows inside the band
        if grp.get("chain", True):
            for row in rows:
                for i in range(len(row) - 1):
                    a, b = plan.placements[row[i]], plan.placements[row[i + 1]]
                    plan.connectors.append(Connector(
                        [(a.right, a.cy), (b.x - 3, b.cy)],
                        kind=grp.get("kind", "default") if grp.get("kind") != "default"
                        else "line",
                        from_id=row[i], to_id=row[i + 1], r=6,
                    ))
        y = band_y + band_h + band_gap
    plan.size = (width, y - band_gap + 24.0)
    return plan


@layout("hub")
def _hub(spec) -> Plan:
    """A central node with satellites on the left and right."""
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 60.0)
    fs, subfs = opts.get("fs", 14.0), opts.get("subfs", 11.0)
    by_id = {n["id"]: n for n in spec["nodes"]}
    center = opts["center"]
    left, right = opts.get("left", []), opts.get("right", [])
    below = opts.get("below")

    cw, ch = node_size(by_id[center], opts.get("cfs", 15.5), opts.get("csubfs", 11.0))
    gap_y = opts.get("gap_y", 24.0)
    col_w = min(opts.get("col_w", 330.0), (width - 2 * margin - cw - 2 * opts.get("col_gap", 80.0)) / 2)

    def stack(ids, x):
        sizes = [node_size(by_id[i], fs, subfs) for i in ids]
        total = sum(s[1] for s in sizes) + gap_y * max(0, len(ids) - 1)
        y = opts.get("y", 20.0) + max(0.0, (opts.get("center_y", 220.0) - total / 2.0))
        out = {}
        for i, s in zip(ids, sizes):
            out[i] = Rect(x, y, col_w, s[1])
            y += s[1] + gap_y
        return out

    L = stack(left, margin)
    R = stack(right, width - margin - col_w)
    ccy = opts.get("center_y", 220.0)
    plan.placements[center] = Rect((width - cw) / 2.0, ccy - ch / 2.0, cw, ch)
    plan.placements.update(L)
    plan.placements.update(R)
    if below:
        bw, bh = node_size(by_id[below], fs, subfs)
        plan.placements[below] = Rect((width - cw) / 2.0 + (cw - bw) / 2.0,
                                      plan.placements[center].bottom + opts.get("below_gap", 110.0),
                                      bw, bh)

    c = plan.placements[center]
    for ids, side in ((left, "left"), (right, "right")):
        if not ids:
            continue
        xs = [plan.placements[i].cy for i in ids]
        xs.sort()
        trunk = (margin + col_w + opts.get("col_gap", 80.0) / 2.0) if side == "left" \
            else (width - margin - col_w - opts.get("col_gap", 80.0) / 2.0)
        for nid in ids:
            r = plan.placements[nid]
            plan.connectors.append(Connector(
                [port(r, side), (trunk, r.cy), (trunk, c.cy), port(c, "left" if side == "left" else "right")],
                kind="slate", from_id=nid, to_id=center, r=12,
            ))
    if below:
        b = plan.placements[below]
        plan.connectors.append(Connector(
            [(c.cx, c.bottom), (b.cx, b.y - 4)], kind=opts.get("below_kind", "violet"),
            from_id=center, to_id=below,
        ))
    return plan


@layout("ring")
def _ring(spec) -> Plan:
    """Nodes on an ellipse, joined clockwise by arcs."""
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    by_id = {n["id"]: n for n in spec["nodes"]}
    # the hub node sits in the middle; it must not also consume a slot on the
    # ring, or the ring ends up with a gap where it would have been
    centre_id = opts.get("center")
    ids = [n["id"] for n in spec["nodes"] if n["id"] != centre_id]
    cx = opts.get("cx", width / 2.0)
    cy = opts.get("cy", 248.0)
    rx = opts.get("rx", 392.0)
    ry = opts.get("ry", 166.0)
    fs, subfs = opts.get("fs", 13.5), opts.get("subfs", 10.5)
    gap_deg = opts.get("gap_deg", 8.0)
    pad = opts.get("pad", 3.0)   # land the arrowhead on the box edge
    start = opts.get("start_deg", -90.0)

    n = len(ids)
    step = 360.0 / n
    angles = [start + i * step for i in range(n)]
    sizes = {}
    for nid, a in zip(ids, angles):
        w, h = node_size(by_id[nid], fs, subfs)
        sizes[nid] = (w, h)
        r = math.radians(a)
        px, py = cx + rx * math.cos(r), cy + ry * math.sin(r)
        plan.placements[nid] = Rect(px - w / 2.0, py - h / 2.0, w, h)

    # How far the arc must stay clear of a node, measured along the ellipse. A
    # fixed angle does not work: the same 20 degrees is a different number of
    # pixels at every point on an ellipse, so a wide box near the flat end of
    # the ellipse swallows the gap and the arc cuts straight through it.
    def half_angle(nid):
        """Angular half-width of a node, measured along the ellipse.

        The tangent direction matters: a box is not a circle, so its extent
        along the curve is the projection of its half-width and half-height onto
        that direction — taking the diagonal instead makes every gap too big and
        collapses the arcs.
        """
        r = math.radians(angles[ids.index(nid)])
        tx, ty = -rx * math.sin(r), ry * math.cos(r)
        length = math.hypot(tx, ty) or 1.0
        ux, uy = abs(tx / length), abs(ty / length)
        w, h = sizes[nid]
        extent = ux * w / 2.0 + uy * h / 2.0
        return math.degrees((extent + pad) / length)

    # never let the clearance eat the whole step, or the arc becomes a dot
    ceiling = step * opts.get("gap_frac", 0.42)
    halves = [min(max(gap_deg, half_angle(nid)), ceiling) for nid in ids]
    kind = opts.get("arc_kind", "violet")
    for i in range(n):
        a0 = angles[i] + halves[i]
        a1 = angles[(i + 1) % n] - halves[(i + 1) % n]
        if a1 <= a0:          # the closing arc wraps past 360; keep the sweep short
            a1 += 360.0
        plan.annotations.append(Annotation("arc", dict(
            cx=cx, cy=cy, rx=rx, ry=ry, a0=a0, a1=a1, kind=kind,
            from_id=ids[i], to_id=ids[(i + 1) % n],
        )))
    if centre_id:
        w, h = node_size(by_id[centre_id], 15.0, 11.0)
        plan.placements[centre_id] = Rect(cx - w / 2.0, cy - h / 2.0, w, h)
    return plan


@layout("sequence")
def _sequence(spec) -> Plan:
    """Lanes and messages: an interaction diagram."""
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 60.0)
    lanes = spec["lanes"]
    header_h = opts.get("header_h", 52.0)
    top = opts.get("y", 20.0)
    lane_w = opts.get("lane_w", (width - 2 * margin) / max(1, len(lanes)) - 26.0)
    step = opts.get("step", 40.0)
    first_y = top + header_h + opts.get("first_gap", 44.0)

    xs = {}
    for i, ln in enumerate(lanes):
        cx = margin + lane_w / 2.0 + i * ((width - 2 * margin - lane_w) / max(1, len(lanes) - 1))
        xs[ln["id"]] = cx
        plan.placements[ln["id"]] = Rect(cx - lane_w / 2.0, top, lane_w, header_h)
    bottom = first_y + step * max(1, len(spec.get("messages", []))) + opts.get("tail", 40.0)

    for ln in lanes:
        plan.annotations.append(Annotation("lane", dict(
            x=xs[ln["id"]], top=top + header_h + 2, bottom=bottom,
        )))
        plan.annotations.append(Annotation("laneheader", dict(
            id=ln["id"], x=xs[ln["id"]] - lane_w / 2.0, y=top,
            w=lane_w, h=header_h, title=ln.get("title", ""), sub=ln.get("sub"),
        )))
    for i, m in enumerate(spec.get("messages", [])):
        y = first_y + i * step
        frm, to = m.get("from"), m.get("to")
        if m.get("self") or frm == to:
            plan.annotations.append(Annotation("selfcall", dict(
                x=xs[frm], y=y, label=m.get("label", ""), kind=m.get("kind", "slate"),
                dashed=m.get("dashed", True),
            )))
            continue
        a, b = xs[frm], xs[to]
        plan.connectors.append(Connector(
            [(a, y), (b, y)], kind=m.get("kind", "line"), dashed=m.get("dashed", False),
            label=m.get("label"), lx=(a + b) / 2.0, ly=y - 11.0,
            from_id=frm, to_id=to, label_gap=11.0, auto_label=False, snap=False,
        ))
    for act in spec.get("activations", []):
        plan.annotations.append(Annotation("activation", dict(
            x=xs[act["lane"]], y0=first_y + act["from"] * step - 14.0,
            y1=first_y + act["to"] * step + 14.0,
        )))
    # messages hang off a lane's lifeline, not off its header box, so the
    # "endpoint must touch the node" check does not apply here
    plan.allow_detached = True
    plan.size = (width, bottom)
    return plan


@layout("state")
def _state(spec) -> Plan:
    """States on a grid, joined by labelled transitions."""
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 60.0)
    fs, subfs = opts.get("fs", 13.5), opts.get("subfs", 10.5)
    by_id = {n["id"]: n for n in spec["nodes"]}
    rows = spec["rows"]
    row_gap = opts.get("row_gap", 66.0)
    col_gap = opts.get("col_gap", 60.0)
    top = opts.get("y", 20.0)
    uniform_w = opts.get("uniform_width")
    if uniform_w is None:
        uniform_w = max(node_size(by_id[i], fs, subfs)[0] for row in rows for i in row)
    row_h = max(node_size(by_id[i], fs, subfs)[1] for row in rows for i in row)

    slot = (width - 2 * margin - uniform_w) / max(1, max(len(r) for r in rows) - 1)
    ys = {}
    for ri, row in enumerate(rows):
        y = top + ri * (row_h + row_gap)
        ys[ri] = y
        n = len(row)
        for ci, nid in enumerate(row):
            w, h = node_size(by_id[nid], fs, subfs)
            w = uniform_w
            x = margin + ci * slot if n > 1 else margin
            plan.placements[nid] = Rect(x, y + (row_h - h) / 2.0, w, h)

    where = {}
    for ri, row in enumerate(rows):
        for ci, nid in enumerate(row):
            where[nid] = (ri, ci)

    for t in spec.get("transitions", []):
        a = plan.placements[t["from"]]
        b = plan.placements[t["to"]]
        pts = t.get("pts")
        if not pts:
            ra, ca = where.get(t["from"], (0, 0))
            rb, cb = where.get(t["to"], (0, 0))
            if t.get("out") and t.get("into"):
                out, into = t["out"], t["into"]
            elif rb == ra:
                # same row: leave and enter horizontally
                out = "right" if cb >= ca else "left"
                into = "left" if cb >= ca else "right"
            else:
                # different row: drop out of the source and come in from the
                # far side of the target, so the run happens in the row gutter
                out = "bottom" if rb > ra else "top"
                into = "top" if rb > ra else "bottom"
            pts = route(a, b, out=out, into=into, channel=t.get("channel"),
                        off=t.get("off", 0.0))
        plan.connectors.append(Connector(
            pts, kind=t.get("kind", "line"), label=t.get("label"),
            from_id=t["from"], to_id=t["to"], dashed=t.get("dashed", False),
            lx=t.get("lx"), ly=t.get("ly"), anchor=t.get("anchor", "middle"),
            r=t.get("r", 12.0), head=t.get("head", True),
        ))
    return plan


@layout("free")
def _free(spec) -> Plan:
    """Explicit coordinates. The escape hatch for hand-tuned figures."""
    plan = Plan()
    opts = spec.get("options", {})
    fs, subfs = opts.get("fs", 15.0), opts.get("subfs", 11.5)
    for n in spec.get("nodes", []):
        if n.get("as_card"):
            w, h = card_size(n)
        else:
            w, h = node_size(n, fs, subfs)
        plan.placements[n["id"]] = Rect(
            n.get("x", 0.0), n.get("y", 0.0),
            n.get("width", w), n.get("height", h),
        )
    for c in spec.get("connectors", []):
        plan.connectors.append(Connector(
            [tuple(p) for p in c["pts"]],
            kind=c.get("kind", "line"), label=c.get("label"),
            from_id=c.get("from"), to_id=c.get("to"),
            dashed=c.get("dashed", False), lx=c.get("lx"), ly=c.get("ly"),
            anchor=c.get("anchor", "middle"), head=c.get("head", True),
            tail=c.get("tail", False), r=c.get("r", 11.0),
            lfs=c.get("lfs", 11.5),
        ))
    for b in spec.get("bands", []):
        plan.bands.append(Band(**b))
    if spec.get("size"):
        plan.size = tuple(spec["size"])
    return plan


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------
def render(spec, scene: Scene = None) -> Scene:
    """Plan a figure and draw it."""
    name = engine_for(spec)
    if name not in LAYOUTS:
        raise KeyError(f"unknown layout {name!r}; known: {', '.join(sorted(LAYOUTS))}")
    plan = LAYOUTS[name](spec)
    opts = spec.get("options", {})
    margin = opts.get("margin", plan.margin)
    by_id = {n["id"]: n for n in spec.get("nodes", [])}

    missing = [nid for nid in by_id if nid not in plan.placements]
    if missing:
        raise ValueError(
            f"layout {name!r} did not place {', '.join(sorted(missing))} — "
            f"every node must be reachable from the layout's options"
        )

    # -- size ---------------------------------------------------------------
    declared = spec.get("size") or (plan.size and list(plan.size))
    if declared:
        width, height = float(declared[0]), float(declared[1])
        if plan.size:
            # the engine laid the content out and knows how tall it is; a
            # smaller declared size would clip it, and clipping is never right
            height = max(height, float(plan.size[1]))
    else:
        b = plan.union(plan.placements)
        width = float(opts.get("width", 1200.0 if opts.get("fixed_width", True) else b.right + margin))
        height = b.bottom + margin

    sc = scene or Scene(
        spec.get("id", "fig"), width, height,
        title=spec.get("title", ""),
        description=spec.get("description") or spec.get("title", ""),
    )

    # -- containers ---------------------------------------------------------
    for b in plan.bands:
        sc.band(b.x, b.y, b.w, b.h, label=b.label, sub=b.sub, kind=b.kind,
                rx=b.rx, fs=b.fs, dash=b.dash,
                lx=b.label_at[0] if b.label_at else None,
                ly=b.label_at[1] if b.label_at else None)
    for g in opts.get("auto_bands", []) or spec.get("auto_bands", []):
        members = [i for i in g["nodes"] if i in plan.placements]
        r = plan.union(members)
        pad_x = g.get("pad_x", 22.0)
        pad_y = g.get("pad_y", 22.0)
        label_h = g.get("label_h", 0.0)
        sc.band(r.x - pad_x, r.y - pad_y - label_h, r.w + 2 * pad_x,
                r.h + 2 * pad_y + label_h, label=g.get("label"),
                sub=g.get("sub"), kind=g.get("kind", "default"),
                rx=g.get("rx", 16.0), fs=g.get("fs", 13.0),
                lx=r.x - pad_x + (g.get("lx_off", 0.0)) if g.get("label") else None,
                ly=(r.y - pad_y - label_h / 2.0) if g.get("label") else None)

    # -- nodes --------------------------------------------------------------
    for nid, r in plan.placements.items():
        n = by_id.get(nid)
        if n is None:
            continue
        if n.get("as_card"):
            sc.card(r.x, r.y, r.w, r.h, n.get("title", ""), n.get("sub"),
                    n.get("items", []), kind=n.get("kind", "default"), id=nid,
                    fs=n.get("fs", 14.0), subfs=n.get("subfs", 10.5),
                    ifs=n.get("ifs", 11.5), pad=n.get("pad", 15.0),
                    gap=n.get("gap"), accent=n.get("accent"),
                    item_code=n.get("item_code", False))
        elif n.get("as_chip"):
            sc.chip(r.x, r.y, r.w, r.h, n.get("title", ""),
                    kind=n.get("kind", "default"), id=nid, fs=n.get("fs", 12.5))
        else:
            sc.node(r.x, r.y, r.w, r.h, n.get("title", ""), _subs(n),
                    kind=n.get("kind", "default"), id=nid,
                    fs=n.get("fs", opts.get("fs", 15.0)),
                    subfs=n.get("subfs", opts.get("subfs", 11.5)),
                    rx=n.get("rx", 12.0), dashes=n.get("dashes", False),
                    align=n.get("align", "center"))

    # -- connectors ---------------------------------------------------------
    for c in plan.connectors:
        lx, ly, anchor = c.lx, c.ly, c.anchor
        if c.label and c.auto_label and lx is None:
            mid = point_on_polyline(c.pts, 0.5) if len(c.pts) > 1 else c.pts[0]
            lx, ly = mid[0], mid[1] - c.label_gap
        sc.edge(c.pts, kind=c.kind, label=c.label, from_id=c.from_id,
                to_id=c.to_id, dashed=c.dashed, head=c.head, tail=c.tail,
                r=c.r, lfs=c.lfs, lx=lx, ly=ly, anchor=anchor, snap=c.snap)

    allow = opts.get("allow_isolated")
    if allow:
        sc.allow_isolated = set(by_id) if allow is True else set(allow)
    if getattr(plan, "allow_detached", False):
        sc.allow_detached = True
    if opts.get("allow_band_overlap"):
        sc.allow_band_overlap = True
    if getattr(plan, "allow_crossing", False) or opts.get("allow_crossing"):
        sc.allow_crossing = True

    # -- annotations --------------------------------------------------------
    for a in plan.annotations:
        _annotate(sc, a)
    for note in spec.get("notes", []):
        _note(sc, note)
    return sc


def _annotate(sc: Scene, a: Annotation):
    k, d = a.kind, a.args
    if k == "arc":
        sc.arc(d["cx"], d["cy"], d["rx"], d["ry"], d["a0"], d["a1"], kind=d["kind"],
               from_id=d.get("from_id"), to_id=d.get("to_id"))
    elif k == "text":
        sc.text(d["x"], d["y"], d["label"], cls=d.get("cls", "d-s"),
                anchor=d.get("anchor", "start"), fs=d.get("fs", 12.0))
    elif k == "tag":
        sc.tag(d["x"], d["y"], d["label"], kind=d.get("kind", "line"),
               anchor=d.get("anchor", "middle"), fs=d.get("fs", 11.0))
    elif k == "laneheader":
        sc.node(d["x"], d["y"], d["w"], d["h"], d["title"],
                [d["sub"]] if d.get("sub") else None, kind="default",
                id=d["id"], fs=13.0, subfs=10.0, rx=10.0)
    elif k == "lane":
        sc.line([(d["x"], d["top"]), (d["x"], d["bottom"])], cls="d-life")
    elif k == "activation":
        sc.raw(f'<rect class="d-act" x="{d["x"] - 6:g}" y="{d["y0"]:g}" width="12" '
               f'height="{d["y1"] - d["y0"]:g}" rx="5"/>')
    elif k == "selfcall":
        x, y = d["x"], d["y"]
        cls = "dg-e e-" + d["kind"] + (" dash" if d.get("dashed") else "")
        sc.raw(f'<path class="{cls}" d="M {x:g} {y:g} L {x + 36:g} {y:g} '
               f'L {x + 36:g} {y + 22:g} L {x + 5:g} {y + 22:g}" fill="none"/>')
        if d.get("label"):
            sc.text(x + 46, y + 11, d["label"], cls="d-el", fs=11.0)


def _note(sc: Scene, note: dict):
    kind = note.get("type", "text")
    if kind == "tag":
        sc.tag(note["x"], note["y"], note["text"], kind=note.get("kind", "line"),
               anchor=note.get("anchor", "middle"), fs=note.get("fs", 11.0))
    elif kind == "legend":
        sc.legend(note["x"], note["y"],
                  [(e[0], e[1]) for e in note["entries"]], fs=note.get("fs", 11.5))
    elif kind == "hline":
        sc.raw(f'<path class="dg-e e-{note.get("kind", "line")}'
               f'{" dash" if note.get("dashed") else ""}" '
               f'd="M {note["x"]:g} {note["y"]:g} L {note["x2"]:g} {note["y"]:g}" '
               f'fill="none" opacity="{note.get("opacity", 1.0):g}"/>')
    else:
        sc.text(note["x"], note["y"], note["text"], cls=note.get("cls", "d-s"),
                anchor=note.get("anchor", "start"), fs=note.get("fs", 12.0))


def _edge_between(spec, a, b):
    """The spec's edge object for a→b, so engines can honour its overrides."""
    for e in spec.get("edges", []):
        if e.get("from") == a and e.get("to") == b:
            return e
    return None


def _edge_label(spec, a, b):
    e = _edge_between(spec, a, b)
    return e.get("label") if e else None
