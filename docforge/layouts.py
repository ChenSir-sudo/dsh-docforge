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
    #: The route deliberately goes around rather than straight, so the distance
    #: between the two boxes says nothing about how the connector reads.
    routed: bool = False


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
    allow_isolated: bool = False                     # see validate._check_isolated
    #: Drawing hints a rect cannot express -- a funnel's two widths, say.
    #: Keyed by node id; ``render`` reads them when it picks the shape.
    shapes: dict = field(default_factory=dict)
    connectors: list = field(default_factory=list)
    bands: list = field(default_factory=list)
    annotations: list = field(default_factory=list)
    size: tuple = None
    margin: float = 24.0

    def rect(self, node_id: str) -> Rect:
        return self.placements[node_id]

    def auto_size(self, width=None, margin=None):
        """Declare the canvas from what has actually been placed.

        Engines used to leave ``size`` unset and let the renderer infer it from
        the placements. That inference was invisible from the engine, so nothing
        told a new engine whether it owed a size. Saying it out loud costs one
        line and makes the contract checkable.
        """
        b = self.union(self.placements)
        pad = self.margin if margin is None else margin
        # A requested width is a *target*. If the content needs more room, the
        # canvas grows rather than the content spilling off the edge -- a canvas
        # narrower than its contents can only ever clip them.
        self.size = (max(width or 0.0, b.right + pad), b.bottom + pad)
        return self.size

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
    hosted = embed_size(n, float(n.get("fs", 13.5)))
    if n.get("as") == "embed" or (hosted and n.get("as") is None):
        # A host node is as big as the figure it contains, plus its own title.
        w, h = hosted or (0.0, 0.0)
        return (float(n.get("width") or max(w, MIN_W)),
                float(n.get("height") or max(h, 40.0)))
    fs = float(n.get("fs", fs or 15.0))
    subfs = float(n.get("subfs", subfs or 11.5))
    subs = _subs(n)
    widths = [T.tw(str(n.get("title", "")), fs, T.BOLD)]
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
    widths = [T.tw(str(c.get("title", "")), fs, T.BOLD)]
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
    plan.auto_size()
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
    plan.auto_size()
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
    plan.auto_size(width=width, margin=margin)
    if bus_y is not None:
        plan.size = (plan.size[0], max(plan.size[1], bus_y + 34.0))
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
    plan.auto_size()
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
    plan.auto_size()
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
    # the arcs bulge past the boxes, so the union of the placements is not the
    # extent of the figure -- the ellipse is
    plan.size = (cx + rx + opts.get("margin", 40.0),
                 cy + ry + opts.get("margin", 40.0))
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
    plan.auto_size()
    return plan


@layout("tree")
def _tree(spec) -> Plan:
    """A hierarchy: one root, each parent centred over its own children.

    Nodes name their ``parent``; the root is ``options.root`` or the one node
    without a parent. Placement is the tidy-tree rule -- a leaf claims the next
    free slot, a parent takes the midpoint of its children -- so siblings stay
    adjacent and no edge has to cross a subtree to reach its target.

    ``options.direction`` is ``"down"`` (default) or ``"right"``.
    """
    plan = Plan()
    opts = spec.get("options", {})
    nodes = spec["nodes"]
    by_id = {n["id"]: n for n in nodes}
    fs, subfs = opts.get("fs", 14.5), opts.get("subfs", 10.5)
    down = opts.get("direction", "down") != "right"
    gap_main = opts.get("gap_main", opts.get("gap_y", 62.0) if down else opts.get("gap_x", 76.0))
    gap_cross = opts.get("gap_cross", opts.get("gap_x", 34.0) if down else opts.get("gap_y", 30.0))
    margin = opts.get("margin", 40.0)

    root = opts.get("root")
    children, parent_of = {}, {}
    for n in nodes:
        par = n.get("parent")
        parent_of[n["id"]] = par
        if par:
            children.setdefault(par, []).append(n["id"])
    if root is None:
        roots = [n["id"] for n in nodes if not n.get("parent")]
        if len(roots) != 1:
            raise ValueError(
                f"layout 'tree' needs exactly one root; found {len(roots)} "
                f"({', '.join(roots) or 'none'}). Set options.root or give every "
                f"node but one a parent."
            )
        root = roots[0]
    if root not in by_id:
        raise ValueError(f"layout 'tree': options.root {root!r} is not a node")
    unknown = sorted({p for p in parent_of.values() if p and p not in by_id})
    if unknown:
        raise ValueError(
            f"layout 'tree': {', '.join(unknown)} named as a parent but not a node"
        )

    depth, seen = {}, set()

    def walk(nid, level):
        if nid in seen:
            raise ValueError(f"layout 'tree': {nid!r} is reachable twice — the "
                             f"parent links contain a cycle")
        seen.add(nid)
        depth[nid] = level
        for kid in children.get(nid, []):
            walk(kid, level + 1)

    walk(root, 0)
    unreachable = sorted(set(by_id) - seen)
    if unreachable:
        raise ValueError(
            f"layout 'tree': {', '.join(unreachable)} not reachable from "
            f"root {root!r}"
        )

    sizes = {n["id"]: node_size(n, fs, subfs) for n in nodes}
    slot = [0.0]

    def place(nid):
        kids = children.get(nid, [])
        if not kids:
            x = slot[0]
            slot[0] += 1.0
            return x
        centres = [place(k) for k in kids]
        return (centres[0] + centres[-1]) / 2.0

    slot_x = {}
    order = []

    def record(nid):
        order.append(nid)
        for kid in children.get(nid, []):
            record(kid)

    # record slots as the recursion returns, so each node keeps its own centre
    def place_and_record(nid):
        kids = children.get(nid, [])
        if not kids:
            x = slot[0]
            slot[0] += 1.0
        else:
            centres = [place_and_record(k) for k in kids]
            x = (centres[0] + centres[-1]) / 2.0
        slot_x[nid] = x
        order.append(nid)
        return x

    place_and_record(root)

    widest = max(sizes[i][0] for i in order)
    tallest = max(sizes[i][1] for i in order)
    step_cross = (widest + gap_cross) if down else (tallest + gap_cross)
    row_gap = gap_main

    depth_h = {}
    for nid in order:
        d = depth[nid]
        need = (sizes[nid][1] if down else sizes[nid][0])
        depth_h[d] = max(depth_h.get(d, 0.0), need)
    offsets, acc = {}, 0.0
    for d in sorted(depth_h):
        offsets[d] = acc
        acc += depth_h[d] + row_gap

    for nid in order:
        w, h = sizes[nid]
        d = depth[nid]
        if down:
            cx = margin + slot_x[nid] * step_cross + widest / 2.0
            plan.placements[nid] = Rect(cx - w / 2.0, margin + offsets[d], w, h)
        else:
            cy = margin + slot_x[nid] * step_cross + tallest / 2.0
            plan.placements[nid] = Rect(margin + offsets[d], cy - h / 2.0, w, h)

    kind = opts.get("edge_kind", "line")
    for nid in order:
        for kid in children.get(nid, []):
            a, b = plan.placements[nid], plan.placements[kid]
            if down:
                mid = (a.bottom + b.y) / 2.0
                pts = [(a.cx, a.bottom), (a.cx, mid), (b.cx, mid), (b.cx, b.y - 3)]
            else:
                mid = (a.right + b.x) / 2.0
                pts = [(a.right, a.cy), (mid, a.cy), (mid, b.cy), (b.x - 3, b.cy)]
            plan.connectors.append(Connector(
                pts, kind=kind, from_id=nid, to_id=kid, r=10,
                label=_edge_label(spec, nid, kid),
            ))
    plan.auto_size(margin=margin)
    return plan


@layout("matrix")
def _matrix(spec) -> Plan:
    """A grid of cells with row and column headers -- a heat map or 2x2.

    Cells come from ``nodes``, each naming its ``row`` and ``col``; the headers
    come from ``options.row_labels`` / ``options.col_labels``. The engine
    implies ``as: cell`` so a matrix spec does not have to repeat it, but a node
    may still override its own shape.
    """
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 40.0)
    row_labels = [str(r) for r in opts.get("row_labels", [])]
    col_labels = [str(c) for c in opts.get("col_labels", [])]
    lfs = opts.get("lfs", 12.0)
    gap = opts.get("gap", 12.0)

    n_cols = max(len(col_labels),
                 max((int(n.get("col", 0)) + 1 for n in spec["nodes"]), default=1))
    n_rows = max(len(row_labels),
                 max((int(n.get("row", 0)) + 1 for n in spec["nodes"]), default=1))

    # a gutter wide enough for the longest row header, a strip for the columns
    gutter = (max(T.tw(t, lfs, T.WEIGHT_HEAVY) for t in row_labels)
              + opts.get("gutter_pad", 18.0)
              if row_labels else 0.0)
    head_h = opts.get("head_h", 34.0) if col_labels else 0.0
    usable = width - 2 * margin - gutter
    cw = opts.get("cell_w") or (usable - gap * (n_cols - 1)) / n_cols
    ch = opts.get("cell_h", 104.0)
    top = opts.get("y", margin) + head_h

    for n in spec["nodes"]:
        r, c = int(n.get("row", 0)), int(n.get("col", 0))
        rect = Rect(margin + gutter + c * (cw + gap), top + r * (ch + gap), cw, ch)
        plan.placements[n["id"]] = rect
        plan.shapes[n["id"]] = {"as": "cell"}

    cx0 = margin + gutter
    for c, text in enumerate(col_labels):
        plan.annotations.append(Annotation("text", dict(
            x=cx0 + c * (cw + gap) + cw / 2.0,
            y=(top - head_h / 2.0) if head_h else top - 14.0,
            label=text, anchor="middle", fs=lfs, cls="d-mx-head")))
    for r, text in enumerate(row_labels):
        plan.annotations.append(Annotation("text", dict(
            x=margin + gutter - opts.get("gutter_pad", 18.0),
            y=top + r * (ch + gap) + ch / 2.0,
            label=text, anchor="end", fs=lfs, cls="d-mx-head")))
    if opts.get("corner"):
        plan.annotations.append(Annotation("text", dict(
            x=margin, y=(top - head_h / 2.0) if head_h else top - 14.0,
            label=str(opts["corner"]), anchor="start", fs=opts.get("cfs", 11.0),
            cls="d-mx-corner")))

    bottom = top + n_rows * ch + (n_rows - 1) * gap
    plan.size = (width, bottom + margin)
    plan.allow_isolated = True      # cells are a grid, not a graph
    return plan


@layout("timeline")
def _timeline(spec) -> Plan:
    """Lanes with bars positioned along a shared axis.

    ``options.axis`` gives the tick labels; a node says which ``row`` it sits in
    and spans ``start``..``end`` in tick units. Bars are implied, so a node only
    needs its label and its span.
    """
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 40.0)
    axis = [str(a) for a in opts.get("axis", [])]
    rows = [str(r) for r in opts.get("row_labels", [])]
    lfs = opts.get("lfs", 12.0)
    afs = opts.get("axis_fs", 11.0)
    row_h = opts.get("row_h", 46.0)
    bar_h = opts.get("bar_h", 26.0)
    gap = opts.get("gap", 12.0)

    n_rows = max(len(rows),
                 max((int(n.get("row", 0)) + 1 for n in spec["nodes"]), default=1))
    span = float(max(1, len(axis) - 1))

    gutter = (max(T.tw(t, lfs, T.WEIGHT_HEAVY) for t in rows)
              + opts.get("gutter_pad", 18.0)
              if rows else 0.0)
    head_h = opts.get("head_h", 30.0) if axis else 0.0
    track_x = margin + gutter
    track_w = width - 2 * margin - gutter
    top = opts.get("y", margin) + head_h

    def num(v, fallback=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return fallback

    def clamp(v):
        return min(max(v, 0.0), span)

    # Pack each row's spans into sub-lanes. Two overlapping tasks in one row are
    # a real thing to draw (parallel work), and stacking them is what makes both
    # readable -- the alternative was letting them collide and then declaring the
    # collision away.
    by_row = {}
    for n in spec["nodes"]:
        by_row.setdefault(int(n.get("row", 0)), []).append(n)
    lane_of, lane_count = {}, {}
    for r, items in by_row.items():
        ends = []
        for n in sorted(items, key=lambda x: (clamp(num(x.get("start"))),
                                              clamp(num(x.get("end"), 1.0)))):
            a = clamp(num(n.get("start")))
            b = max(a, clamp(num(n.get("end"), a + 1.0)))
            for li, last in enumerate(ends):
                if a >= last - 1e-9:
                    lane_of[n["id"]], ends[li] = li, b
                    break
            else:
                lane_of[n["id"]] = len(ends)
                ends.append(b)
        lane_count[r] = max(1, len(ends))

    lane_gap = opts.get("lane_gap", 10.0)
    lane_h = bar_h + lane_gap
    # a row is as tall as its busiest lane stack, never less than row_h
    row_top, y = {}, top
    for r in range(n_rows):
        row_top[r] = y
        y += max(row_h, lane_count.get(r, 1) * lane_h - lane_gap + opts.get("row_pad", 18.0))

    # ticks are drawn first so the bars sit on top of their own gridline
    for i, text in enumerate(axis):
        x = track_x + (i / span) * track_w
        plan.annotations.append(Annotation("axis_tick", dict(
            x=x, top=top - 8.0, bottom=y, label=text)))
    for r, text in enumerate(rows):
        plan.annotations.append(Annotation("text", dict(
            x=margin + gutter - opts.get("gutter_pad", 18.0),
            y=row_top.get(r, top) + row_h / 2.0, label=text, anchor="end", fs=lfs,
            cls="d-tl-head")))

    for n in spec["nodes"]:
        r = int(n.get("row", 0))
        a = clamp(num(n.get("start")))
        b = max(a, clamp(num(n.get("end"), a + 1.0)))
        x0 = track_x + (a / span) * track_w
        x1 = track_x + (b / span) * track_w
        w = max(opts.get("min_bar", 26.0), x1 - x0)
        # A minimum-width bar sitting on the last tick would hang off the end,
        # so slide it back inside rather than let it leave the canvas.
        x0 = min(x0, track_x + track_w - w)
        yy = row_top.get(r, top) + lane_of.get(n["id"], 0) * lane_h
        plan.placements[n["id"]] = Rect(x0, yy, w, bar_h)
        plan.shapes[n["id"]] = {"as": "bar"}

    # Dependencies between bars. Finish-to-start is the useful default: the
    # arrow leaves the end of one span and enters the start of the next. A link
    # that points backwards in time is routed around underneath, because a
    # straight run would cut back through the bars between them.
    links = list(spec.get("links") or opts.get("links") or [])
    for link in links:
        src, dst = link.get("from"), link.get("to")
        for end in (src, dst):
            if end not in plan.placements:
                raise ValueError(
                    f"layout 'timeline': link names {end!r}, which is not a bar"
                )
        a, b = plan.placements[src], plan.placements[dst]
        if b.x >= a.right:
            mid = (a.right + b.x) / 2.0
            pts = [(a.right, a.cy), (mid, a.cy), (mid, b.cy), (b.x - 3, b.cy)]
            # beside the vertical run: the polyline's own midpoint sits on a
            # corner, and a label there lands against one of the two bars
            if link.get("lx") is None:
                link["lx"] = mid + 5.0
                link.setdefault("ly", (a.cy + b.cy) / 2.0)
                link.setdefault("anchor", "start")
        else:
            ch = max(a.bottom, b.bottom) + opts.get("link_gap", 20.0)
            pts = [(a.cx, a.bottom), (a.cx, ch), (b.cx, ch), (b.cx, b.bottom + 3)]
            if link.get("lx") is None:
                link["lx"] = (a.cx + b.cx) / 2.0
                link.setdefault("ly", ch - 9.0)
                link.setdefault("anchor", "middle")
        plan.connectors.append(Connector(
            pts, kind=link.get("kind", "slate"), from_id=src, to_id=dst,
            label=link.get("label"), lx=link.get("lx"), ly=link.get("ly"),
            anchor=link.get("anchor", "middle"), dashed=link.get("dashed", False),
            r=9, routed=True,
        ))

    # a backward link's channel sits below every bar, so the canvas owes it room
    bottom = y - lane_gap
    for c in plan.connectors:
        bottom = max(bottom, max(p[1] for p in c.pts))
    plan.size = (width, bottom + margin)
    plan.allow_isolated = True      # bars sit on lanes, they do not connect
    return plan


@layout("funnel")
def _funnel(spec) -> Plan:
    """Stages that narrow, each drawn as the trapezoid into the next.

    Stage widths follow ``value`` when every stage declares a positive number,
    so the shape carries the drop-off; otherwise they fall off linearly to
    ``min_ratio`` of the first. ``options.drop_labels`` annotates the gaps.
    """
    plan = Plan()
    opts = spec.get("options", {})
    width = opts.get("width", (spec.get("size") or [1200])[0])
    margin = opts.get("margin", 60.0)
    nodes = spec["nodes"]
    if not nodes:
        return plan
    stage_h = opts.get("stage_h", 74.0)
    gap = opts.get("gap", opts.get("stage_gap", 12.0))
    top = opts.get("y", margin)
    usable = width - 2 * margin - opts.get("side_pad", 120.0)

    values = []
    for n in nodes:
        try:
            v = float(n.get("value_n", n.get("value", 0)))
        except (TypeError, ValueError):
            v = 0.0
        values.append(v if v > 0 else 0.0)
    if all(v > 0 for v in values) and len(set(values)) > 1:
        widths = [max(usable * opts.get("min_ratio", 0.18),
                      usable * (v / values[0])) for v in values]
    else:
        lo = usable * opts.get("min_ratio", 0.18)
        step = (usable - lo) / max(1, len(nodes) - 1)
        widths = [usable - i * step for i in range(len(nodes))]

    cx = width / 2.0
    y = top
    for i, n in enumerate(nodes):
        w_top = widths[i]
        w_bottom = widths[i + 1] if i + 1 < len(widths) else widths[i] * opts.get("tail_ratio", 0.86)
        plan.placements[n["id"]] = Rect(cx - max(w_top, w_bottom) / 2.0, y,
                                        max(w_top, w_bottom), stage_h)
        plan.shapes[n["id"]] = {"as": "funnel", "w_top": w_top, "w_bottom": w_bottom}
        drops = opts.get("drop_labels") or []
        if i < len(drops) and drops[i]:
            plan.annotations.append(Annotation("text", dict(
                x=cx + max(w_top, w_bottom) / 2.0 + opts.get("drop_gap", 18.0),
                y=y + stage_h + gap / 2.0, label=str(drops[i]), anchor="start",
                fs=opts.get("dfs", 11.0), cls="d-fn-drop")))
        y += stage_h + gap
    plan.size = (width, y - gap + margin)
    plan.allow_isolated = True      # stages flow by position, not by connectors
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
    else:
        plan.auto_size()
    return plan


#: How deep a figure may nest. A sub-spec cannot literally reference itself,
#: but nothing stops an author building a deep chain, and past a few levels the
#: result is unreadable anyway.
EMBED_DEPTH = 4

#: Horizontal room an embedded figure keeps inside its host box.
EMBED_PAD = 12.0


def embed_size(n, fs=13.5, pad=EMBED_PAD) -> tuple:
    """Size of a node that hosts a nested figure: its title plus the content."""
    emb = n.get("_embed")
    if not emb:
        return None
    title = str(n.get("title", ""))
    head = (fs + 14.0) if title else 0.0
    head = float(n.get("head_h", head))
    tw = T.tw(title, fs, T.BOLD) + 2 * pad if title else 0.0
    return (max(tw, emb["w"] + 2 * pad), head + emb["h"] + 2 * pad)


def resolve_embeds(spec, path, depth=0) -> None:
    """Render every nested spec a level down, once, before layout.

    An engine has to know how big a host node is before it can place it, and
    that size depends on the nested figure -- so the recursion happens first and
    the result is parked on the node. Rendering here rather than in ``render``
    also means each child is built exactly once.
    """
    for n in spec.get("nodes", []):
        sub = n.get("sub_spec")
        if not sub:
            n.pop("_embed", None)
            continue
        if depth + 1 > EMBED_DEPTH:
            raise ValueError(
                f"{path}/{n.get('id')}: figures nested deeper than {EMBED_DEPTH}"
            )
        sub_path = f"{path}/{n.get('id')}"
        child = render(sub, path=sub_path, _depth=depth + 1)
        n["_embed"] = {"scene": child, "w": child.width, "h": child.height,
                       "path": sub_path}


def render(spec, scene: Scene = None, path: str = None, _depth: int = 0) -> Scene:
    """Plan a figure and draw it."""
    name = engine_for(spec)
    if name not in LAYOUTS:
        raise KeyError(f"unknown layout {name!r}; known: {', '.join(sorted(LAYOUTS))}")
    path = path or str(spec.get("id", "fig"))
    resolve_embeds(spec, path, _depth)
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
    # The engine knows how big its figure is; the renderer does not guess. A
    # declared size acts as a *minimum* on both axes, because a canvas smaller
    # than its contents can only ever clip them.
    if not plan.size:
        raise ValueError(
            f"layout {name!r} did not declare a size; an engine must set "
            f"plan.size or call plan.auto_size()"
        )
    width, height = float(plan.size[0]), float(plan.size[1])
    if spec.get("size"):
        width = max(width, float(spec["size"][0]))
        height = max(height, float(spec["size"][1]))

    sc = scene or Scene(
        path, width, height,
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
        hint = plan.shapes.get(nid) or {}
        shape = (n.get("as") or hint.get("as")
                 or ("card" if n.get("as_card") else
                     "chip" if n.get("as_chip") else
                     "embed" if n.get("_embed") else "node"))
        if shape == "card":
            sc.card(r.x, r.y, r.w, r.h, n.get("title", ""), n.get("sub"),
                    n.get("items", []), kind=n.get("kind", "default"), id=nid,
                    fs=n.get("fs", 14.0), subfs=n.get("subfs", 10.5),
                    ifs=n.get("ifs", 11.5), pad=n.get("pad", 15.0),
                    gap=n.get("gap"), accent=n.get("accent"),
                    item_code=n.get("item_code", False))
        elif shape == "chip":
            sc.chip(r.x, r.y, r.w, r.h, n.get("title", ""),
                    kind=n.get("kind", "default"), id=nid, fs=n.get("fs", 12.5))
        elif shape == "cell":
            sc.cell(r.x, r.y, r.w, r.h, value=n.get("value"), label=n.get("title"),
                    kind=n.get("kind", "default"), level=n.get("level", 0), id=nid,
                    level_ratio=n.get("level_ratio"),
                    vfs=n.get("vfs", 17.0), lfs=n.get("lfs", 10.5),
                    pad=n.get("pad", 10.0), rx=n.get("rx", 8.0))
        elif shape == "bar":
            sc.bar(r.x, r.y, r.w, r.h, n.get("title"),
                   kind=n.get("kind", "teal"), dashed=n.get("dashed", False),
                   id=nid, fs=n.get("fs", 11.0), pad=n.get("pad", 9.0))
        elif shape == "embed":
            child = (n.get("_embed") or {}).get("scene")
            if child is not None:
                sc.children[nid] = child
            sc.embed(r.x, r.y, r.w, r.h, n.get("title", ""), child,
                     kind=n.get("kind", "default"), id=nid,
                     fs=n.get("fs", 13.5), pad=n.get("pad", EMBED_PAD),
                     head_h=n.get("head_h"))
        elif shape == "funnel":
            # An engine that computes the taper passes it through `shapes`; a
            # hand-placed one declares `w_top` / `w_bottom` itself. Falling back
            # to the rect for both ends would silently draw a plain rectangle.
            sc.funnel(r.cx, r.y,
                      hint.get("w_top", n.get("w_top", r.w)),
                      hint.get("w_bottom", n.get("w_bottom", r.w)),
                      r.h, n.get("title"), n.get("value"),
                      kind=n.get("kind", "indigo"), id=nid,
                      fs=n.get("fs", 12.5), vfs=n.get("vfs", 12.5))
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
                r=c.r, lfs=c.lfs, lx=lx, ly=ly, anchor=anchor, snap=c.snap,
                routed=c.routed)

    if getattr(plan, "allow_isolated", False):
        sc.allow_isolated = set(by_id)
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
    elif k == "axis_tick":
        # the gridline a bar sits on, with its tick label above the strip
        sc.line([(d["x"], d["top"]), (d["x"], d["bottom"])], cls="d-tl-tick")
        sc.text(d["x"], d["top"] - 14.0, d["label"], cls="d-tl-axis",
                anchor="middle", fs=d.get("fs", 11.0))
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
