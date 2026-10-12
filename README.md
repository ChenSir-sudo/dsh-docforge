# docforge

**Material in, one self-contained HTML file out — with diagrams whose geometry a validator proves is correct.**

[中文说明](README.zh-CN.md) · MIT licensed · Python ≥ 3.9, standard library only

docforge compiles a Markdown material plus a set of JSON figure specs into a single
`.html`: styles inlined, diagrams as inline SVG, no network requests, opens by
double-click, prints cleanly, themes switch live.

The point is not that it generates a page. The point is that **it can prove the
diagrams are not broken**. Every drawing primitive records its own bounding box as
it draws, and a validator reads that record to report text overflow, boxes that
intersect, connectors that cross an unrelated node, labels sitting on other text,
and elements outside the canvas. You do not have to find these by eye.

```
material markdown ──┐
                    ├──> markdown.parse ──> Doc ──┐
figure JSON ────────┘                             ├──> document.render ──> index.html
                    └──> specs.render ──> SVG ────┘
                              │
                              └──> validate.check_scene ──> findings (exit 0/1)
```

---

## Quick start

Nothing to install. Python ≥ 3.9, standard library only.

```bash
# 1. scaffold a material
bin/docforge init ./out --template doc

# 2. edit out/material.md and out/figures/*.json

# 3. validate first — get this clean before generating anything
bin/docforge check ./out/material.md

# 4. build
bin/docforge build ./out/material.md -o ./out/index.html
```

`bin/docforge` is a one-line POSIX wrapper that resolves symlinks, so it works from
any directory. From the repository root you can equivalently use
`python3 -m docforge.cli`. Put it on your `PATH` if you like:

```bash
export PATH="$PWD/bin:$PATH"
docforge skill-info
```

**Step 3 is not optional.** If `check` is not clean, do not build — every finding
names a specific figure and a specific element.

---

## Interfaces

docforge deliberately exposes more than one way in, so a caller can use as much or
as little of it as it needs.

### 1. Figure blocks inside the material

````markdown
```figure arch
@figures/arch.json          ← reference a file
```

```figure quick
{ "layout": "pipeline", "nodes": [{"id":"a","title":"A"}], "edges": [] }
```
````

### 2. Declarative figure specs

A figure is one JSON object. **The engine places things; the spec describes
content** — you never compute coordinates.

```json
{
  "id": "flow", "layout": "pipeline", "title": "Main flow",
  "nodes": [
    {"id": "in",  "title": "Parse input", "sub": ["raw input"]},
    {"id": "out", "title": "Emit",        "sub": ["final_answer"], "kind": "green"}
  ],
  "edges": [{"from": "in", "to": "out", "label": "parsed"}]
}
```

Ten layout engines: `pipeline` `dag` `fan` `layers` `hub` `ring` `sequence`
`state` `grid` `free`. Ask for the current list and each one's parameters:

```bash
bin/docforge layouts
```

Widths are derived from the text itself (CJK counts as 1.0 em, Latin as 0.55 em),
so do not hand-write widths. When you need to nudge, a node may carry
`x`/`y`/`width`/`height` to override placement; for anything truly irregular, use
`free` and route by hand with `connectors[].pts`.

### 3. Python API

```python
from docforge import specs, document, markdown
from docforge.theme import Theme

theme = Theme.load("paper")
doc = markdown.parse_file("out/material.md")
figures = {ref.id: specs.render_svg(specs.load(f"out/figures/{ref.id}.json"))
           for ref in doc.figures}
html = document.render(doc, figures, theme, numbering="auto")
```

### 4. Command line

| Command | What it does |
|---|---|
| `docforge build <material>` | material → single-file HTML |
| `docforge fig <figure>` | one figure → SVG (`--png` also writes a PNG) |
| `docforge check <target…>` | validate only; accepts figures or materials |
| `docforge init <dir>` | scaffold a material (`--template doc/report/course`) |
| `docforge themes` | list themes |
| `docforge layouts` | list layout engines |
| `docforge shot <html> <png>` | headless screenshot (optional) |
| `docforge examples` | list the bundled examples |
| `docforge skill-info` | machine-readable capability description |

`check` and `build` both accept `--format json` and `--fail-on error|warning|none`.

### 5. Capability self-description (for other agents and plugins)

```bash
bin/docforge skill-info --json          # layouts, themes, commands, exit codes, error codes
bin/docforge check x.json --format json
```

Exit codes: `0` clean · `1` validation failed · `2` usage/IO error · `3` internal error.

---

## Using it as an agent skill

The repository *is* the skill. Copy or symlink the folder into a skill root and any
agent that reads `SKILL.md` can use it — `SKILL.md` is the agent-facing entry point,
`INTERFACE.md` is the frozen contract.

```bash
git clone https://github.com/ChenSir-sudo/dsh-docforge.git ~/.dsh/skills/dsh-docforge
```

No packaging step, no dependencies, no daemon. The bundle is portable by design.

---

## Validation

This is the difference between docforge and gluing a page together from a template.
Both `check` and `build` run it.

**Errors** (must be fixed):

| code | Meaning |
|---|---|
| `text-overflow` | text is wider than its box |
| `box-overlap` | two boxes intersect |
| `edge-through` | a connector passes through an unrelated node |
| `label-collision` | a label sits on a box, another label, or a band caption |
| `edge-over-label` | a connector runs through another element's label |
| `out-of-canvas` | an element extends past the canvas |
| `degenerate-edge` | a connector has zero length |

**Warnings** (require judgement): `edge-crossing`, `isolated-node`,
`band-overlap`, `short-connector`, `connector-detached`, `edge-overlap`,
`label-clearance`, `no-figures`.

When a node really is meant to stand alone, **declare it** rather than suppress the
check:

```json
"options": {"allow_isolated": ["security"]}
```

The document level adds `unresolved-figure`, `tag-imbalance`, `duplicate-id`,
`dangling-anchor`, `figure-missing`, `figure-spec-invalid`, `figure-render-failed`
and others — all errors.

```bash
bin/docforge check out/material.md --format json --fail-on warning
```

### Why this holds up

`Scene` records an `Item(kind, bbox, inner, text_boxes, pts, endpoints)` for every
element as it emits the SVG. The validator reads that record and measures with **the
same text metrics the layout itself used**, so it is checking whether the layout model
is internally consistent — not guessing at pixels.

The limits are worth stating. Latin glyph width is estimated at 0.55 em and the
checker keeps a 2 px tolerance, so an unusual font can still be slightly off. The
1.0 em estimate for CJK is accurate enough in practice.

---

## Themes

A theme is a JSON file whose `light` and `dark` token maps must declare the same
keys (`Theme.missing()` proves it). **No SVG in the document hard-codes a colour** —
everything goes through CSS variables, so switching a theme recolours the diagrams
along with the prose.

| Theme | Look |
|---|---|
| `paper` | light paper with indigo (default) |
| `midnight` | cool dark ground with teal |
| `contrast` | high contrast, for accessibility and print |

Add your own by copying `themes/paper.json` and changing values. A material can open
in dark mode with `mode: dark` in its front matter.

---

## Screenshots (optional)

Validation **never needs a browser**. You only need a Chromium-family browser when
you want a human to look at the render.

```bash
bin/docforge shot out/index.html /tmp/shot.png --width 1440 --height 2400
```

If no browser is found it says so and points at `DOCFORGE_BROWSER`; it does not
pretend to have succeeded. Note that a capture starts at the top of the page — to
inspect a later chapter, render that chapter as its own page and shoot it.

Headless Chromium is memory-hungry, and several at once slow each other into
timeouts, so `shot()` serialises concurrent captures behind an inter-process file
lock (waiting up to 180 s). Parallel agents will not trample each other.

---

## Tests

```bash
sh tools/test.sh                   # unit + end-to-end (POSIX sh, not python)
python3 -m unittest discover -s tests -t . -v
```

Five groups:

- **Geometry and metrics** (`test_geom` / `test_text`) — segment intersection, rect
  relations, CJK width estimation. The foundation the validator stands on.
- **Scene recording** (`test_scene`) — does every primitive register the right
  geometry and `lines`.
- **Validator** (`test_validate` / `test_overlap`) — every code needs a **triggering**
  case *and* a **just-below-threshold** case that must not fire. The crossing
  false-positive guards (shared fan-out source, T-junctions) are tested separately.
- **Layout engines** (`test_layouts`) — each engine's placement properties (order,
  non-overlap, points on the given ellipse, diamond in one column), and **every
  engine's output must be error-free**.
- **End-to-end** (`test_e2e`) — material → HTML, build determinism, and that a bad
  material actually fails.

---

## Layout

```
dsh-docforge/
  SKILL.md            agent-facing usage notes (the entry point when deployed as a skill)
  INTERFACE.md        frozen contract: every signature and data structure
  README.md           this file
  README.zh-CN.md     Chinese README
  docforge/           the importable package
    text.py           CJK/Latin width metrics
    geom.py           Rect / segments / rounded polylines / arc sampling
    scene.py          Scene: draws and records geometry
    layouts.py        the ten layout engines (produce a Plan, never draw)
    specs.py          figure specs: load / normalise / validate / render
    validate.py       geometry and document validation
    theme.py          theme tokens → CSS
    highlight.py      per-language code highlighting (tok-* spans, stdlib only)
    markdown.py       material parsing
    document.py       document assembly → single-file HTML
    render.py         optional headless screenshots
    cli.py            command line
  assets/             base.css (structure) + code.css (code chrome) + svg.css (figure rules)
  themes/             paper / midnight / contrast
  templates/          doc / report / course starter materials
  examples/           bundled examples, including a full flagship document
  tests/              unit and end-to-end
  tools/              test and packaging scripts
```

`assets/svg.css` is the single source of figure styling. It is inlined into the
document **and** embedded in a standalone `.svg` export, so the two can never drift.

---

## Extending

**Add a layout engine.** Write a function in `layouts.py` that returns a `Plan` and
register it with `@layout("name")`, then add a line to `cli.LAYOUT_DOC`. A `Plan` only
says *who is where, who connects to whom, which container wraps what*; drawing is done
centrally by `render()`. A new engine therefore gets validation, theming and standalone
SVG export for free.

**Add a validation rule.** Add a `_check_xxx(scene, ..., out)` in `validate.py` that
appends `Finding` objects, and call it from `check_scene`. If the code is new, add it
to `ERROR_CODES` or `WARNING_CODES` and document it in `SKILL.md` — a test asserts that
every advertised code is documented, so adding a check without documenting it fails
the suite.

Details are in [`INTERFACE.md`](INTERFACE.md).

---

## License

MIT — see [LICENSE](LICENSE).
