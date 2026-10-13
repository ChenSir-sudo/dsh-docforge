"""Figure specs: loading, validation, and rendering to SVG.

A spec is plain JSON — that is deliberate. It is the interface an agent (or a
plugin wrapper, or a human) can produce without importing anything.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import layouts
from .scene import Scene
from .theme import Theme

REQUIRED = ("id", "layout")
KNOWN_LAYOUTS = tuple(sorted(layouts.LAYOUTS))


class SpecError(Exception):
    pass


def load(ref):
    """Load a spec from a path, or pass a dict through."""
    if isinstance(ref, dict):
        return normalize(ref)
    path = Path(ref)
    if not path.is_file():
        raise SpecError(f"no such figure spec: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path}: invalid JSON — {exc}") from exc
    return normalize(data)


def normalize(spec: dict) -> dict:
    """Fill in defaults and fail fast on structural mistakes."""
    if not isinstance(spec, dict):
        raise SpecError("a figure spec must be a JSON object")
    for key in REQUIRED:
        if key not in spec:
            raise SpecError(f"figure spec is missing required key {key!r}")
    if spec["layout"] not in layouts.LAYOUTS:
        raise SpecError(
            f"unknown layout {spec['layout']!r}; known: {', '.join(KNOWN_LAYOUTS)}"
        )
    spec.setdefault("title", "")
    spec.setdefault("kind", "")
    spec.setdefault("options", {})
    spec.setdefault("nodes", [])
    problems = validate_spec(spec)
    if problems:
        raise SpecError("; ".join(problems))
    return spec


def validate_spec(spec: dict) -> list:
    """Structural problems that would produce a broken or misleading figure."""
    out = []
    layout = spec.get("layout")
    if layout not in layouts.LAYOUTS:
        out.append(f"unknown layout {layout!r}")

    nodes = spec.get("nodes", [])
    ids = [n.get("id") for n in nodes]
    if any(i is None for i in ids):
        out.append("every node needs an id")
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    if dupes:
        out.append(f"duplicate node ids: {', '.join(dupes)}")

    known = {i for i in ids if i}
    for e in spec.get("edges", []):
        for end in ("from", "to"):
            if e.get(end) and e[end] not in known:
                out.append(f"edge references unknown node {e[end]!r}")
    for c in spec.get("connectors", []):
        for end in ("from", "to"):
            if c.get(end) and c[end] not in known:
                out.append(f"connector references unknown node {c[end]!r}")
        if not c.get("pts"):
            out.append("every connector needs explicit pts")
    for t in spec.get("transitions", []):
        for end in ("from", "to"):
            if t.get(end) not in known:
                out.append(f"transition references unknown node {t.get(end)!r}")
    for g in spec.get("groups", []) + spec.get("auto_bands", []):
        for nid in g.get("nodes", []):
            if nid not in known:
                out.append(f"group {g.get('label')!r} references unknown node {nid!r}")

    opts = spec.get("options", {})
    if layout == "fan":
        for key in ("source", "targets"):
            if key not in opts:
                out.append(f"the fan layout needs options.{key}")
        for nid in [opts.get("source")] + list(opts.get("targets", [])):
            if nid and nid not in known:
                out.append(f"fan references unknown node {nid!r}")
    if layout == "hub":
        if "center" not in opts:
            out.append("the hub layout needs options.center")
        for nid in [opts.get("center")] + list(opts.get("left", [])) \
                + list(opts.get("right", [])) + ([opts["below"]] if opts.get("below") else []):
            if nid and nid not in known:
                out.append(f"hub references unknown node {nid!r}")
    if layout == "sequence":
        if not spec.get("lanes"):
            out.append("the sequence layout needs lanes")
        lane_ids = {l.get("id") for l in spec.get("lanes", [])}
        for m in spec.get("messages", []):
            for end in ("from", "to"):
                if m.get(end) and m[end] not in lane_ids:
                    out.append(f"message references unknown lane {m[end]!r}")
    if layout in ("state", "layers"):
        if layout == "state" and not spec.get("rows"):
            out.append("the state layout needs rows")
        if layout == "layers" and not spec.get("groups"):
            out.append("the layers layout needs groups")
    size = spec.get("size")
    if size is not None and (not isinstance(size, (list, tuple)) or len(size) != 2):
        out.append("size must be [width, height]")
    return out


def scene_svg(scene, theme=None, mode="light", standalone=True) -> str:
    """Render an already-built scene, with its backdrop when standalone.

    Public because the CLI needs the scene for other things (its size, the PNG
    height) and so used to assemble the standalone SVG itself -- and forgot the
    backdrop, which is invisible on a light theme and produces a white-backed
    dark export.
    """
    if standalone:
        theme = theme or Theme.load("paper")
        return _with_background(
            scene.svg(standalone=True, palette=theme.palette(mode),
                      svg_css=_svg_css()), scene)
    return scene.svg()


def _scene_svg(scene, theme, mode, standalone) -> str:
    return scene_svg(scene, theme, mode, standalone)


def render(spec) -> Scene:
    """Spec (dict or path) -> a fully drawn :class:`~docforge.scene.Scene`."""
    if not isinstance(spec, dict):
        spec = load(spec)
    return layouts.render(spec)


def render_svg(spec, theme=None, mode="light", standalone=False) -> str:
    return _scene_svg(render(spec), theme, mode, standalone)


def _with_background(svg: str, scene) -> str:
    """A standalone .svg opens on any page, so give it its own backdrop."""
    head = svg.index(">", svg.index("<svg")) + 1
    rect = (f'<rect class="d-canvas" x="0" y="0" width="{scene.width:g}" '
            f'height="{scene.height:g}"/>')
    return svg[:head] + rect + svg[head:]


def _svg_css() -> str:
    from .theme import svg_css
    return svg_css()


def check(spec, **kwargs) -> list:
    """Validate one spec's rendered geometry."""
    from . import validate as V
    return V.check_scene(render(spec), **kwargs)
