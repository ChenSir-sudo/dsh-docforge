#!/usr/bin/env python3
"""Build the sample gallery: one contact sheet per theme, one tile per engine.

The figures existed only as test baselines under ``tests/golden/`` -- so a
project whose whole purpose is drawing diagrams shipped a README with no
diagrams in it. This turns those baselines into something a reader can look at.

Baselines are viewport-height captures (900x2400) with the figure at the top, so
each tile is trimmed back to its own content first.

    python3 tools/gallery.py [--out docs/images] [--width 520]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Reading order matters more than alphabetical here: relate the relational
#: shapes to each other, then the data shapes, then the hierarchy, then nesting.
ORDER = [
    "pipeline.pipeline", "dag.dag", "intent.fan", "layers.layers", "hub.hub",
    "ring.ring", "state.state", "sequence.sequence", "grid.grid", "free.free",
    "matrix.matrix", "timeline.timeline", "funnel.funnel", "tree.tree",
    "nested-figure",
]

COLUMNS = 3
PAD = 18
LABEL_H = 26


def background(theme: str, mode: str) -> tuple:
    """The canvas colour, read from the theme rather than guessed.

    A wrong guess here does not fail loudly -- it just stops trimming, and the
    sheet comes out several thousand pixels tall.
    """
    import json
    spec = json.loads((ROOT / "themes" / f"{theme}.json").read_text(encoding="utf-8"))
    token = spec[mode if mode in spec else "light"]["--bg"].lstrip("#")
    return tuple(int(token[i:i + 2], 16) for i in (0, 2, 4))


def trim(im, background=None):
    """Crop away the margin a viewport-height capture leaves behind.

    Measured against **white**, not against the theme's canvas colour. A
    standalone capture is the SVG centred in a white browser page, so white is
    the margin in both modes -- and in light mode the canvas is white too, so
    keying on the canvas colour would find nothing to trim. The dark canvas is
    dark, so keying on white keeps it and gives the tile its backdrop.
    """
    from PIL import Image, ImageChops
    flat = ImageChops.difference(im.convert("RGB"),
                                 Image.new("RGB", im.size, (255, 255, 255)))
    bbox = flat.getbbox()
    if not bbox:
        return im
    pad = 6
    return im.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                    min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad)))


def label_font(size: int):
    from PIL import ImageFont
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build(theme: str, out: pathlib.Path, width: int, doc_theme: str = "paper") -> pathlib.Path:
    from PIL import Image, ImageDraw

    suffix = "" if theme == "light" else "-dark"
    bg = background(doc_theme, theme)
    tiles = []
    for name in ORDER:
        src = ROOT / "tests" / "golden" / f"{name}{suffix}.png"
        if not src.exists():
            print(f"  missing baseline: {src.name}", file=sys.stderr)
            continue
        im = trim(Image.open(src))
        ratio = width / im.width
        tiles.append((name, im.resize((width, max(1, int(im.height * ratio))),
                                      Image.LANCZOS)))
    if not tiles:
        raise SystemExit("no baselines found; run `sh tools/golden.sh --update`")

    rows = (len(tiles) + COLUMNS - 1) // COLUMNS
    row_h = [0] * rows
    for i, (_, im) in enumerate(tiles):
        row_h[i // COLUMNS] = max(row_h[i // COLUMNS], im.height)

    sheet_w = COLUMNS * width + (COLUMNS + 1) * PAD
    sheet_h = sum(h + LABEL_H for h in row_h) + (rows + 1) * PAD
    sheet = Image.new("RGB", (sheet_w, sheet_h), bg)
    draw = ImageDraw.Draw(sheet)
    ink = (28, 28, 34) if theme == "light" else (228, 228, 236)
    font = label_font(15)

    y = PAD
    for row in range(rows):
        for col in range(COLUMNS):
            i = row * COLUMNS + col
            if i >= len(tiles):
                break
            name, im = tiles[i]
            x = PAD + col * (width + PAD)
            # `intent.fan` is the example named `intent` drawn with the `fan`
            # engine -- the engine is what a reader is looking for, so it leads.
            example, dot, engine = name.partition(".")
            if not dot:                 # `nested-figure` names no engine
                caption = example
            elif example == engine:
                caption = engine
            else:
                caption = f"{engine}  ({example})"
            draw.text((x + 2, y + 4), caption, fill=ink, font=font)
            sheet.paste(im, (x, y + LABEL_H))
        y += row_h[row] + LABEL_H + PAD

    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"engines{suffix}.png"
    sheet.save(dest, optimize=True)
    print(f"  {dest.relative_to(ROOT)}  {sheet.size[0]}x{sheet.size[1]}  "
          f"{len(tiles)} figures")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "docs" / "images"))
    ap.add_argument("--width", type=int, default=520, help="tile width in px")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    print("building the sample gallery")
    for theme in ("light", "dark"):
        build(theme, out, args.width)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
