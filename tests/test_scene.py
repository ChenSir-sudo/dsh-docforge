"""Unit tests for ``docforge.scene``.

A ``Scene`` draws *and* records.  Every test here checks the drawing and the
record against each other, because the validator's whole value proposition is
that the record is the drawing.
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from docforge import text as T
from docforge.geom import Rect, arc_points, rect_from_points
from docforge.scene import KINDS, Scene


def _root(svg: str):
    return ET.fromstring(svg)


def _shapes(svg: str, cls=None):
    out = []
    for el in _root(svg).iter():
        if cls is not None and el.get("class") != cls:
            continue
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("rect", "path", "text"):
            out.append(el)
    return out


def _one_shape(svg: str, cls: str):
    hits = _shapes(svg, cls)
    if len(hits) != 1:
        raise AssertionError(f"expected exactly one {cls!r}, found {len(hits)}")
    return hits[0]


def _num(el, attr):
    return float(el.get(attr))


class PrimitiveRegistrationTest(unittest.TestCase):
    """One primitive -> exactly one Item, of the right kind, same geometry."""

    def setUp(self):
        self.sc = Scene("sc", 400, 300)

    def test_node(self):
        it = self.sc.node(20, 30, 120, 60, "Title", "sub")
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "node")
        self.assertEqual(it.bbox, Rect(20, 30, 120, 60))
        box = _one_shape(self.sc.svg(), "d-box")
        self.assertEqual(_num(box, "x"), 20.0)
        self.assertEqual(_num(box, "y"), 30.0)
        self.assertEqual(_num(box, "width"), 120.0)
        self.assertEqual(_num(box, "height"), 60.0)

    def test_chip_is_a_node_item_with_pill_radius(self):
        it = self.sc.chip(10, 10, 90, 26, "chip")
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "node")
        self.assertEqual(it.bbox, Rect(10, 10, 90, 26))
        self.assertEqual(_num(_one_shape(self.sc.svg(), "d-box"), "rx"), 13.0)

    def test_card(self):
        it = self.sc.card(10, 10, 200, 120, "Title", "Sub", ["a", "b"])
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "card")
        self.assertEqual(it.bbox, Rect(10, 10, 200, 120))
        box = _one_shape(self.sc.svg(), "d-box d-card")
        self.assertEqual(_num(box, "x"), 10.0)
        self.assertEqual(_num(box, "width"), 200.0)
        self.assertEqual(_num(box, "height"), 120.0)

    def test_band(self):
        it = self.sc.band(0, 0, 400, 300, label="Band")
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "band")
        self.assertEqual(it.bbox, Rect(0, 0, 400, 300))
        box = _one_shape(self.sc.svg(), "d-band b-default")
        self.assertEqual(_num(box, "width"), 400.0)
        self.assertEqual(_num(box, "height"), 300.0)

    def test_tag(self):
        it = self.sc.tag(200, 150, "tagged")
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "tag")
        box = _one_shape(self.sc.svg(), "d-tag")
        # the emitted markup rounds to 0.1px; the recorded bbox does not.
        self.assertAlmostEqual(_num(box, "x"), it.bbox.x, delta=0.05)
        self.assertAlmostEqual(_num(box, "y"), it.bbox.y, delta=0.05)
        self.assertAlmostEqual(_num(box, "width"), it.bbox.w, delta=0.05)
        self.assertAlmostEqual(_num(box, "height"), it.bbox.h, delta=0.05)

    def test_text(self):
        it = self.sc.text(50, 60, "hello", fs=12.0)
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "text")
        self.assertEqual(it.bbox.x, 50.0)
        self.assertEqual(it.bbox.y, 54.0)
        self.assertAlmostEqual(it.bbox.w, T.tw("hello", 12.0))
        self.assertEqual(it.bbox.h, 12.0)

    def test_text_with_middle_anchor_is_centred(self):
        it = self.sc.text(200, 150, "hello", anchor="middle", fs=12.0)
        self.assertAlmostEqual(it.bbox.cx, 200.0)
        self.assertAlmostEqual(it.bbox.w, T.tw("hello", 12.0))

    def test_text_with_end_anchor_ends_at_x(self):
        it = self.sc.text(200, 150, "hello", anchor="end", fs=12.0)
        self.assertAlmostEqual(it.bbox.right, 200.0)

    def test_edge(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)]
        it = self.sc.edge(pts)
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "edge")
        self.assertEqual(it.pts, tuple(pts))
        self.assertEqual(it.bbox, Rect(0, 0, 100, 50))
        path = _one_shape(self.sc.svg(), "dg-e e-line")
        self.assertEqual(path.get("d"), "M 0 0 L 89.0 0.0 Q 100 0 100.0 11.0 L 100 50")

    def test_edge_bbox_matches_the_two_point_line_drawn(self):
        it = self.sc.edge([(5, 7), (25, 47)])
        path = _one_shape(self.sc.svg(), "dg-e e-line")
        self.assertEqual(path.get("d"), "M 5 7 L 25 47")
        self.assertEqual(it.bbox, Rect(5, 7, 20, 40))

    def test_arc(self):
        it = self.sc.arc(200, 150, 80, 40, 0, 180)
        self.assertEqual(len(self.sc.items), 1)
        self.assertEqual(it.kind, "arc")
        pts = arc_points(200, 150, 80, 40, 0, 180, 32)
        self.assertEqual(it.pts, tuple(pts))
        self.assertEqual(it.bbox, rect_from_points(pts).inflate(2))

    def test_legend_registers_one_text_item_per_entry(self):
        items = self.sc.legend(20, 20, [("line", "a"), ("teal", "bb")], fs=11.5)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(self.sc.items), 2)
        self.assertTrue(all(i.kind == "text" for i in items))

    def test_lines_registers_several_items(self):
        items = self.sc.lines(20, 20, ["one", "two", "three"])
        self.assertEqual(len(items), 3)
        self.assertEqual(len(self.sc.items), 3)

    def test_every_primitive_together_still_one_item_each(self):
        sc = Scene("all", 600, 400)
        sc.node(10, 10, 100, 40, "n")
        sc.chip(10, 60, 80, 24, "c")
        sc.card(10, 100, 150, 100, "card")
        sc.band(0, 0, 600, 400, label="b")
        sc.tag(300, 60, "t")
        sc.text(300, 100, "txt")
        sc.edge([(200, 200), (300, 200)])
        sc.arc(400, 300, 40, 20, 0, 90)
        self.assertEqual(len(sc.items), 8)
        self.assertEqual([i.kind for i in sc.items],
                         ["node", "node", "card", "band", "tag", "text", "edge", "arc"])


class ItemIdTest(unittest.TestCase):
    def test_duplicate_id_raises(self):
        sc = Scene("dup", 200, 200)
        sc.node(0, 0, 50, 20, "a", id="same")
        with self.assertRaises(ValueError):
            sc.node(60, 0, 50, 20, "b", id="same")

    def test_duplicate_id_across_primitive_kinds_raises(self):
        sc = Scene("dup2", 200, 200)
        sc.node(0, 0, 50, 20, "a", id="same")
        with self.assertRaises(ValueError):
            sc.text(0, 40, "b", id="same")

    def test_auto_ids_are_assigned_and_unique(self):
        sc = Scene("auto", 400, 200)
        ids = [
            sc.node(0, 0, 50, 20, "a").id,
            sc.card(0, 40, 50, 20, "b").id,
            sc.tag(100, 100, "c").id,
            sc.text(0, 80, "d").id,
            sc.edge([(0, 100), (50, 100)]).id,
            sc.arc(100, 100, 10, 10, 0, 90).id,
            sc.band(0, 0, 400, 200).id,
        ]
        self.assertTrue(all(i for i in ids), ids)
        self.assertEqual(len(set(ids)), len(ids), ids)

    def test_auto_ids_include_the_scene_uid(self):
        sc = Scene("myscene", 200, 200)
        self.assertTrue(sc.node(0, 0, 10, 10, "a").id.startswith("myscene-"))

    def test_get_returns_the_item_and_raises_for_unknown(self):
        sc = Scene("g", 200, 200)
        it = sc.node(0, 0, 10, 10, "a", id="node-a")
        self.assertIs(sc.get("node-a"), it)
        with self.assertRaises(KeyError):
            sc.get("nope")


class EdgeSnappingTest(unittest.TestCase):
    """``from_id``/``to_id`` identify the nodes an edge legitimately touches.

    They are *recorded* on the ``Item`` so the validator can exclude those
    nodes, and ``snap=True`` additionally moves the geometry onto the node
    centre.  (INTERFACE.md section 3 still documents the centre snap as the
    default; the implementation makes it opt-in because every layout in
    ``docforge.layouts`` computes exact port coordinates itself.)
    """

    def test_from_id_is_recorded_as_an_endpoint_without_moving_geometry(self):
        sc = Scene("e", 400, 300)
        a = sc.node(20, 20, 100, 60, "A")
        it = sc.edge([(0, 0), (300, 300)], from_id=a.id)
        self.assertEqual(it.endpoints, (a.id, None))
        self.assertEqual(it.pts[0], (0.0, 0.0))
        self.assertEqual(it.pts[-1], (300.0, 300.0))

    def test_to_id_is_recorded_as_an_endpoint_without_moving_geometry(self):
        sc = Scene("e", 400, 300)
        a = sc.node(20, 20, 100, 60, "A")
        it = sc.edge([(0, 0), (300, 300)], to_id=a.id)
        self.assertEqual(it.endpoints, (None, a.id))
        self.assertEqual(it.pts[-1], (300.0, 300.0))

    def test_snap_moves_the_first_point_to_the_node_centre(self):
        sc = Scene("e", 400, 300)
        a = sc.node(20, 20, 100, 60, "A")
        it = sc.edge([(0, 0), (300, 300)], from_id=a.id, snap=True)
        self.assertEqual(it.pts[0], (a.bbox.cx, a.bbox.cy))
        self.assertEqual(it.pts[-1], (300.0, 300.0))

    def test_snap_moves_the_last_point_to_the_node_centre(self):
        sc = Scene("e", 400, 300)
        a = sc.node(20, 20, 100, 60, "A")
        it = sc.edge([(0, 0), (300, 300)], to_id=a.id, snap=True)
        self.assertEqual(it.pts[0], (0.0, 0.0))
        self.assertEqual(it.pts[-1], (a.bbox.cx, a.bbox.cy))

    def test_snap_both_ends_and_records_endpoints(self):
        sc = Scene("e", 400, 300)
        a = sc.node(20, 20, 100, 60, "A")
        b = sc.node(250, 200, 100, 60, "B")
        it = sc.edge([(0, 0), (10, 10), (0, 0)], from_id=a.id, to_id=b.id,
                     snap=True)
        self.assertEqual(it.pts[0], (a.bbox.cx, a.bbox.cy))
        self.assertEqual(it.pts[-1], (b.bbox.cx, b.bbox.cy))
        self.assertEqual(it.endpoints, (a.id, b.id))
        self.assertEqual(it.bbox, rect_from_points(it.pts))

    def test_snap_uses_the_node_bbox_not_the_label(self):
        sc = Scene("e", 400, 300)
        a = sc.node(100, 50, 200, 100, "wide title here")
        it = sc.edge([(0, 0), (0, 0)], from_id=a.id, snap=True)
        self.assertEqual(it.pts[0], (200.0, 100.0))


class LinesAlignmentTest(unittest.TestCase):
    """``meta['lines']`` must stay index aligned with ``text_boxes``."""

    def test_node_with_subtitle(self):
        sc = Scene("n", 400, 300)
        it = sc.node(20, 20, 200, 80, "Title", ["s1", "s2"])
        self.assertEqual(it.meta["lines"], ["Title", "s1", "s2"])
        self.assertEqual(len(it.text_boxes), 3)

    def test_node_with_newline_joined_subtitle(self):
        sc = Scene("n", 400, 300)
        it = sc.node(20, 20, 200, 80, "Title", "s1\ns2")
        self.assertEqual(it.meta["lines"], ["Title", "s1", "s2"])
        self.assertEqual(len(it.text_boxes), 3)

    def test_node_without_subtitle(self):
        sc = Scene("n", 400, 300)
        it = sc.node(20, 20, 200, 80, "Title")
        self.assertEqual(it.meta["lines"], ["Title"])
        self.assertEqual(len(it.text_boxes), 1)

    def test_card(self):
        sc = Scene("c", 400, 300)
        it = sc.card(20, 20, 250, 150, "Title", "Sub", ["a", "b"], accent="3")
        self.assertEqual(it.meta["lines"], ["Title", "3", "Sub", "a", "b"])
        self.assertEqual(len(it.text_boxes), 5)

    def test_card_without_sub_or_accent(self):
        sc = Scene("c", 400, 300)
        it = sc.card(20, 20, 250, 150, "Title", items=["a"])
        self.assertEqual(it.meta["lines"], ["Title", "a"])
        self.assertEqual(len(it.text_boxes), 2)

    def test_band(self):
        sc = Scene("b", 400, 300)
        it = sc.band(0, 0, 400, 300, label="Band", sub="note")
        self.assertEqual(it.meta["lines"], ["Band", "note"])
        self.assertEqual(len(it.text_boxes), 2)

    def test_band_without_label(self):
        sc = Scene("b", 400, 300)
        it = sc.band(0, 0, 400, 300)
        self.assertEqual(it.meta["lines"], [])
        self.assertEqual(it.text_boxes, [])

    def test_tag(self):
        sc = Scene("t", 400, 300)
        it = sc.tag(100, 100, "hello")
        self.assertEqual(it.meta["lines"], ["hello"])
        self.assertEqual(len(it.text_boxes), 1)

    def test_text(self):
        sc = Scene("t", 400, 300)
        it = sc.text(100, 100, "hello")
        self.assertEqual(it.meta["lines"], ["hello"])
        self.assertEqual(len(it.text_boxes), 1)

    def test_edge_with_label(self):
        sc = Scene("e", 400, 300)
        it = sc.edge([(0, 0), (100, 0)], label="go")
        self.assertEqual(it.meta["lines"], ["go"])
        self.assertEqual(len(it.text_boxes), 1)

    def test_edge_without_label(self):
        sc = Scene("e", 400, 300)
        it = sc.edge([(0, 0), (100, 0)])
        self.assertEqual(it.meta["lines"], [])
        self.assertEqual(it.text_boxes, [])

    def test_arc_has_no_text(self):
        sc = Scene("a", 400, 300)
        it = sc.arc(200, 150, 40, 20, 0, 180)
        self.assertEqual(it.text_boxes, [])
        self.assertIsNone(it.text_bbox)


class SvgOutputTest(unittest.TestCase):
    def _scene(self):
        sc = Scene("out", 320, 200, title="A & B", description="d < e")
        a = sc.node(20, 20, 100, 50, "Node & <one>")
        b = sc.node(200, 120, 100, 50, "B")
        sc.edge([(120, 45), (200, 145)], from_id=a.id, to_id=b.id, label="x < y")
        sc.tag(200, 40, "tag")
        return sc

    def test_svg_is_well_formed_xml(self):
        root = _root(self._scene().svg())
        self.assertTrue(root.tag.endswith("svg"))

    def test_svg_carries_the_viewbox_and_class(self):
        root = _root(self._scene().svg(cls="dg-x"))
        self.assertEqual(root.get("viewBox"), "0 0 320 200")
        self.assertEqual(root.get("class"), "dg-x")

    def test_escaping_survives_parsing(self):
        svg = self._scene().svg()
        root = _root(svg)  # would raise if & or < leaked through raw
        text = "".join(el.text or "" for el in root.iter() if el.tag.endswith("text"))
        self.assertIn("x < y", text)
        self.assertIn("Node & <one>", text)

    def test_one_marker_per_kind(self):
        svg = self._scene().svg()
        root = _root(svg)
        markers = [el for el in root.iter() if el.tag.endswith("marker")]
        self.assertEqual(len(markers), len(KINDS))
        self.assertEqual([m.get("id") for m in markers],
                         [f"mout-{k}" for k in KINDS])

    def test_standalone_with_palette_embeds_style(self):
        svg = self._scene().svg(standalone=True,
                                palette={"bg": "#eef1f6", "line": "#333"},
                                svg_css=".dg{fill:none}")
        root = _root(svg)
        styles = [el for el in root.iter() if el.tag.endswith("style")]
        self.assertEqual(len(styles), 1)
        self.assertIn("--bg:#eef1f6;", styles[0].text)
        self.assertIn("--line:#333;", styles[0].text)
        self.assertIn(".dg{fill:none}", styles[0].text)

    def test_not_standalone_has_no_style(self):
        svg = self._scene().svg()
        self.assertNotIn("<style", svg)

    def test_standalone_without_css_has_no_style(self):
        svg = self._scene().svg(standalone=True, palette={"bg": "#fff"})
        self.assertNotIn("<style", svg)

    def test_defs_contain_the_markers(self):
        svg = self._scene().svg()
        self.assertIn("<defs>", svg)
        self.assertIn("</defs>", svg)


class BoundsTest(unittest.TestCase):
    def test_bounds_covers_every_item(self):
        sc = Scene("b", 400, 300)
        sc.node(20, 20, 100, 50, "A")
        sc.node(250, 200, 100, 50, "B")
        sc.edge([(120, 45), (250, 225)])
        sc.tag(200, 150, "t")
        sc.text(30, 280, "footer")
        bounds = sc.bounds()
        for it in sc.items:
            self.assertTrue(bounds.contains_rect(it.bbox),
                            f"{it.kind} {it.id} outside {bounds}")

    def test_bounds_of_empty_scene_is_the_canvas(self):
        self.assertEqual(Scene("b", 400, 300).bounds(), Rect(0, 0, 400, 300))

    def test_bounds_is_the_union_of_item_boxes(self):
        sc = Scene("b", 400, 300)
        a = sc.node(20, 20, 100, 50, "A")
        b = sc.node(250, 200, 100, 50, "B")
        self.assertEqual(sc.bounds(), a.bbox.union(b.bbox))

    def test_bounds_reacts_to_new_items(self):
        sc = Scene("b", 400, 300)
        sc.node(20, 20, 100, 50, "A")
        before = sc.bounds()
        sc.node(300, 250, 60, 40, "B")
        after = sc.bounds()
        self.assertLess(before.area, after.area)
        self.assertTrue(after.contains_rect(before))


class ItemTest(unittest.TestCase):
    def test_text_bbox_is_the_union_of_the_runs(self):
        sc = Scene("i", 400, 300)
        it = sc.node(20, 20, 300, 100, "Title", "sub")
        self.assertEqual(it.text_bbox, it.text_boxes[0].union(it.text_boxes[1]))

    def test_text_bbox_is_none_without_text(self):
        sc = Scene("i", 400, 300)
        self.assertIsNone(sc.band(0, 0, 100, 100).text_bbox)

    def test_as_dict_shape(self):
        sc = Scene("i", 400, 300)
        it = sc.node(20, 30, 100, 50, "Title")
        d = it.as_dict()
        self.assertEqual(d["kind"], "node")
        self.assertEqual(d["id"], it.id)
        self.assertEqual(d["bbox"], {"x": 20.0, "y": 30.0, "w": 100.0, "h": 50.0})
        self.assertEqual(d["label"], "Title")
        self.assertEqual(d["endpoints"], [])

    def test_as_dict_prefers_label_over_title(self):
        sc = Scene("i", 400, 300)
        it = sc.edge([(0, 0), (50, 0)], label="go")
        self.assertEqual(it.as_dict()["label"], "go")


class RawTest(unittest.TestCase):
    def test_raw_markup_is_emitted_but_not_registered(self):
        sc = Scene("r", 200, 200)
        sc.raw('<circle cx="5" cy="5" r="4"/>')
        self.assertEqual(sc.items, [])
        self.assertIn("<circle", sc.svg())
        _root(sc.svg())  # still well formed

    def test_raw_returns_self_for_chaining(self):
        sc = Scene("r", 200, 200)
        self.assertIs(sc.raw("<g/>"), sc)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
