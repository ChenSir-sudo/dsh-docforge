# docforge — interface contract

Frozen surface. Anything documented here is stable and may be relied on by
other parts of the package, by the CLI, and by plugin wrappers.

Version: `SCHEMA_VERSION = 1` (`docforge.SCHEMA_VERSION`)

---

## 1. Layers

```
materials (markdown / json)          figures (spec json / python DSL)
              |                                    |
        markdown.parse()                      layouts.render()
              |                                    |
           Doc model                             SVG string
              \______________  ___________________/
                             \/
                   document.render()
                             |
                   single-file HTML string
                             |
                   validate.check_document()
```

Every arrow is a pure function. Nothing touches the network or the filesystem
except the loaders (`specs.load`, `markdown.parse_file`) and the optional
screenshot helper (`render.shot`).

---

## 2. Geometry and text

```python
from docforge.geom import Rect, seg_seg_hit, seg_rect_hit, arc_points, rounded_path

Rect(x, y, w, h)            # frozen dataclass
  .right .bottom .cx .cy .area .is_empty
  .inflate(d) .shrink_to(d) .offset(dx, dy)
  .intersects(other, pad=0.0) -> bool
  .overlap_area(other) -> float
  .contains_point(x, y, pad=0.0) -> bool
  .contains_rect(other, pad=0.0) -> bool
  .union(other) -> Rect      .intersection(other) -> Rect
  .as_dict() -> {"x","y","w","h"}
```

```python
from docforge import text as T

T.units(s) -> float          # advance width in em; CJK counts 1.0, Latin 0.55
T.tw(s, fs) -> float         # rendered width in user units
T.fit(s, fs, maxw) -> float  # largest font size <= fs that still fits
T.wrap(s, fs, maxw) -> list[str]
T.truncate(s, fs, maxw) -> str
T.lines_needed(s, fs, maxw) -> int
```

The validator and every layout use these. Do not re-derive widths locally.

---

## 3. Scene

```python
from docforge.scene import Scene, Item, KINDS

sc = Scene(uid, width, height, title="", description="", pad=12.0)
```

`Scene` draws and simultaneously records geometry. Every primitive returns the
`Item` it created; use `item.id` for later references.

| method | records | notes |
|---|---|---|
| `node(x, y, w, h, title, sub=None, kind="default", id=None, fs=15, subfs=11.5, rx=12, dashes=False, align="center")` | `node` | `sub` is a list or `\n`-joined string |
| `chip(x, y, w, h, label, kind="default", id=None, fs=12.5)` | `node` | pill radius |
| `card(x, y, w, h, title, sub=None, items=(), kind="default", id=None, pad=15, accent=None)` | `card` | left-aligned list |
| `band(x, y, w, h, label=None, sub=None, kind="default", id=None, rx=16, lx=None, ly=None, fs=13, dash=False)` | `band` | draw **before** children |
| `edge(pts, kind="line", label=None, id=None, from_id=None, to_id=None, dashed=False, head=True, tail=False, r=11, lfs=11.5, lx=None, ly=None, anchor="middle", snap=False)` | `edge` | `from_id`/`to_id` are recorded as endpoints so the validator can exclude the nodes the connector legitimately touches. They move the geometry **only** when `snap=True` |
| `arc(cx, cy, rx, ry, a0, a1, kind="violet", id=None, head=True)` | `arc` | angles in degrees, clockwise |
| `tag(x, y, label, kind="line", anchor="middle", fs=11, pad=7)` | `tag` | pill annotation |
| `text(x, y, label, cls="d-s", anchor="start", fs=12, id=None, maxw=None)` | `text` | `maxw` truncates |
| `legend(x, y, entries, fs=11.5, gap=22)` | `text` × n | `entries = [(kind, label), ...]` |

`kind` ∈ `KINDS` = `line, indigo, teal, amber, red, green, violet, slate, ink`,
or `"default"` for the neutral box style.

Output:

```python
sc.svg(cls="dg") -> str
sc.svg(cls="dg", standalone=True, palette=theme.palette("light"),
       svg_css=theme.svg_css()) -> str    # self-contained .svg file
```

`Item`:

```python
Item(kind, bbox, id, inner, text_boxes, pts, endpoints, meta)
  .text_bbox -> Rect | None
  .as_dict() -> dict
```

`meta` keys the validator relies on: `lines` (the text of each run, index
aligned with `text_boxes`), `title`, `label`. All primitives set `lines`.

### Why `snap` defaults to off

Layout engines already compute the exact port a connector leaves from. Snapping
that to the node's centre would drag the line straight through the box it just
left, and the validator would — correctly — report `edge-through`. Snapping is
for hand-written `free` figures where you want a connector to point at a node
without knowing its coordinates. Pass `from_id`/`to_id` either way: they are what
tells the validator which nodes this connector is *allowed* to touch.

A scene may also carry:

- ``scene.allow_isolated`` — a set of node ids that are deliberately
  unconnected; `_check_isolated` skips them. Populated from
  `options.allow_isolated` (``true`` for all nodes, or a list of ids).
- ``scene.allow_detached`` — set by the `sequence` engine, where a message's
  endpoints name a lane rather than the lane's header box.
- ``scene.allow_crossing`` — from `options.allow_crossing`. A connector crossing
  another is a warning (`edge-crossing`); some graphs, a state machine being the
  obvious one, are clearest with one deliberate crossing. Declaring it keeps the
  remaining reports meaningful. Note this suppresses crossings only — a
  *collinear overlap* (`edge-overlap`) is a separate rule and stays on.
- ``scene.allow_band_overlap`` — from `options.allow_band_overlap`, for a figure
  where one container is meant to sit across another (a rail beside stacked
  bands, say).

---

## 4. Validation

```python
from docforge import validate as V

V.check_scene(scene, overflow_tol=2.0, clearance=1.0, check_crossings=True,
              check_isolated=True, check_short=True) -> list[Finding]
V.check_document(html, figure_ids=(), toc_ids=()) -> list[Finding]
V.worst(findings) -> "error" | "warning" | "ok"
V.should_fail(findings, fail_on="error") -> bool     # fail_on: error|warning|none
V.summarize(findings) -> {"status","total","errors","warnings","by_code"}
V.format_text(findings) -> str
```

`Finding(code, severity, message, figure, item, detail)` with
`.as_dict()` for `--format json`.

Codes: `text-overflow`, `box-overlap`, `edge-through`, `label-collision`,
`out-of-canvas`, `degenerate-edge` are **errors**; `edge-crossing`,
`isolated-node`, `band-overlap`, `no-figures`, `short-connector`, `connector-detached` are **warnings**; document-level
`unresolved-figure`, `unresolved-token`, `tag-imbalance`, `figure-count`,
`duplicate-id`, `dangling-anchor`, `figure-missing`, `figure-spec-invalid`,
`figure-render-failed`, `toc-anchor-missing` are **errors**.

`toc_ids` is a list of heading anchors the caller believes its outline points
at; any id with no matching element is reported. Dangling `href="#…"` links are
caught separately, so this only fires when the outline and the body disagree.

`short-connector` complements the overlap check: two boxes may be perfectly
legal and still be stacked 5px apart, which leaves no room for the arrow between
them. Geometry alone cannot tell you that, so it is checked explicitly.

`overflow_tol` exists because Latin advance width is estimated at 0.55 em; the
checker allows 2px of slop before calling a run too wide. CJK's 1.0 em estimate
is accurate enough that the tolerance is rarely load-bearing.

`overflow_x_px` / `overflow_y_px` on a `text-overflow` finding are the **largest
one-sided overhang**, not the total excess: a centred run that is 6px too wide
reports 3px, because that is how far it visibly sticks out on each side. The
finding also carries `text_width_px` and `box_inner_width_px` for callers that
want the total.

---

## 5. Figures — declarative spec

```json
{
  "id": "intent",
  "layout": "fan",
  "title": "意图识别与条件路由",
  "kind": "流转图",
  "caption": "可选，覆盖文档里的默认图注",
  "size": [1200, 424],
  "options": { "...": "layout specific" },
  "nodes": [
    {"id": "msg", "title": "最新用户消息", "sub": ["messages[-1]"], "kind": "default"}
  ],
  "edges": [
    {"from": "msg", "to": "cls"},
    {"from": "route", "to": "gen", "label": "else", "kind": "indigo"}
  ],
  "bands": [{"label": "内核", "kind": "indigo", "nodes": ["a", "b"]}],
  "notes": [{"x": 50, "y": 386, "text": "兜底分支必须存在", "cls": "d-fig-t"}]
}
```

`layout` selects an engine in `docforge.layouts.LAYOUTS`
(`pipeline`, `dag`, `fan`, `layers`, `hub`, `ring`, `sequence`, `state`,
`grid`, `free`). Engines own
placement; the spec owns content. A node's `x`/`y`/`w`/`h`, when present,
override the engine (escape hatch for hand placement).

```python
from docforge import specs
sp = specs.load("figures/intent.json")   # path | dict -> normalised dict
sp = specs.normalize(sp)                 # fills defaults, raises SpecError
specs.validate_spec(sp) -> list[str]     # structural problems, [] when fine
sc = specs.render(sp)                    # -> Scene
svg = specs.render_svg(sp, theme)        # -> str
specs.check(sp) -> list[Finding]         # render + validate in one call
```

`normalize` is the gate: an unknown layout, a duplicate node id, an edge
pointing at a node that does not exist, or a layout that silently failed to
place a declared node all raise `SpecError` rather than producing a figure that
is missing a box.

## 6. Documents — material format

```markdown
---
title: 通用 Agent 实战开发流程
eyebrow: Playbook · 完整落地版
theme: paper
numbering: auto
---

# 总体架构

正文……

```figure intent
{ "layout": "pipeline", ... }
```

> [!ACCEPT]
> 验收标准。
```

`markdown.parse(text) -> Doc`, `document.render(doc, figures, theme, **opts) -> str`.

```python
Doc(meta: dict, blocks: list, figures: list[FigureRef], toc: list[TocEntry])
FigureRef(id, number, kind, name, spec_or_path, caption)
```

`document.render` signature:

```python
render(doc, figures: dict[str, str], theme, *,
       numbering="auto", dark=True, toc=True, validate=True) -> str
```

`figures` maps figure id → SVG markup. The caller renders them, so the
document layer never imports the layout layer. A missing id produces a visible
placeholder and a `figure-missing` finding, never silence.

Heading numbering (`numbering="auto"`) implements the markdown-standard ladder —
`一、` / `1.` / `[1]` / `1.1` / `[1]` — and is **idempotent**: a title that the
author already numbered is emitted verbatim, so `### [1] 关键动作` does not become
`[1] [1] 关键动作`.

---

## 7. Themes

```python
from docforge.theme import Theme, document_css, svg_css

t = Theme.load("paper")          # or a path to a JSON file
t.palette("light") -> {"bg": "#eef1f6", ...}    # no leading --
t.css() -> ":root{...}[data-theme=\"dark\"]{...}"
document_css(t) -> theme.css() + assets/base.css
svg_css() -> assets/svg.css      # only the .dg / .d-box / .k-* / .e-* rules
```

`doc.meta["mode"]` (default `light`) chooses the opening mode; the `dark` flag on
`render` controls only whether the light/dark toggle is emitted.

A theme JSON has `name`, `label`, `description`, `light{}`, `dark{}`.
Both maps must declare the same token names — `Theme.missing()` proves it.

---

### 7.1 Screenshots serialise

`render.shot()` takes an exclusive lock (`$TMPDIR/docforge-shot.lock`) for the
duration of the browser run, waiting up to 180s. Headless Chromium is
memory-hungry: several at once make each other slow enough to time out, so they
queue. `shot(..., wait_for_lock=0)` fails fast instead of waiting.

---

## 8. CLI

```
docforge build   <material.md> [-o out.html] [--theme NAME]
                 [--numbering auto|manual] [--no-toc] [--no-dark]
                 [--fail-on error|warning|none] [--format text|json] [-q]
docforge fig     <figure.json> [-o out.svg] [--theme NAME] [--mode light|dark]
                 [--png out.png] [--width 1400] [--scale 2]
docforge check   <figure.json|material.md>... [--format text|json]
                 [--fail-on error|warning|none] [--clearance N] [--no-crossings]
docforge init    <dir> [--template doc|report|course] [--force]
docforge themes  [--json]
docforge layouts [--json]
docforge examples [--json]
docforge shot    <in.html> <out.png> [--width] [--height] [--scale] [--browser]
docforge skill-info [--json]
```

Exit codes: `0` clean, `1` validation failed, `2` usage/IO error, `3` internal
error. `skill-info --json` is the machine-readable capability descriptor a
plugin wrapper or another agent should read first.
