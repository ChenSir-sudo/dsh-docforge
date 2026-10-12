"""Overlap rules: the failures that look fine to every other check.

Each of these reproduces a defect that shipped: three edges stacked on one
channel so the diagram showed a single arrow where it meant three, and a
connector running through a label that belonged to something else.
"""

from __future__ import annotations

import re
import unittest

from docforge import specs
from docforge import validate as V

from .test_layouts import EngineContractMixin, node, render


def codes(spec):
    return {f.code for f in V.check_scene(specs.render(spec))}


def free_spec(nodes, connectors, size=(800, 400)):
    return {"id": "ov", "layout": "free", "size": list(size),
            "nodes": nodes, "connectors": connectors,
            "options": {"allow_isolated": True}}


def box(nid, x, y, w=120, h=60):
    return node(nid, nid, None, "default") | {"x": x, "y": y,
                                             "width": w, "height": h}


class EdgeOverlapTest(unittest.TestCase):
    def test_two_connectors_on_one_channel_are_reported(self):
        spec = free_spec(
            [box("a", 40, 40), box("b", 40, 260),
             box("c", 560, 40), box("d", 560, 260)],
            [
                {"pts": [[160, 70], [400, 70], [400, 290], [560, 290]],
                 "from": "a", "to": "d", "label": "第一条"},
                {"pts": [[160, 70], [400, 70], [400, 260], [560, 260]],
                 "from": "b", "to": "c", "label": "第二条"},
            ])
        self.assertIn("edge-overlap", codes(spec))

    def test_a_shared_trunk_from_one_node_is_not_reported(self):
        """Fan-out from a single node is a bus, not a mistake."""
        spec = free_spec(
            [box("src", 40, 160), box("t1", 600, 40), box("t2", 600, 300)],
            [
                {"pts": [[160, 190], [400, 190], [400, 70], [600, 70]],
                 "from": "src", "to": "t1"},
                {"pts": [[160, 190], [400, 190], [400, 330], [600, 330]],
                 "from": "src", "to": "t2"},
            ])
        self.assertNotIn("edge-overlap", codes(spec))


class EdgeOverLabelTest(unittest.TestCase):
    def test_a_connector_cutting_a_foreign_label_is_an_error(self):
        spec = free_spec(
            [box("a", 40, 40), box("b", 600, 40),
             box("c", 40, 280), box("e", 320, 10, 120, 50)],
            [
                # a flat connector whose label sits in the middle
                {"pts": [[160, 70], [600, 70]], "from": "a", "to": "b",
                 "label": "被压住的标签", "lx": 380, "ly": 54},
                # a vertical connector that runs straight through that label
                {"pts": [[380, 300], [380, 30]], "from": "c", "to": "e"},
            ])
        self.assertIn("edge-over-label", codes(spec))

    def test_a_label_on_its_own_connector_is_fine(self):
        spec = free_spec(
            [box("a", 40, 40), box("b", 600, 40)],
            [{"pts": [[160, 70], [600, 70]], "from": "a", "to": "b",
              "label": "自己的标签", "lx": 380, "ly": 54}])
        self.assertNotIn("edge-over-label", codes(spec))


class LabelClearanceTest(unittest.TestCase):
    def test_a_label_touching_a_box_is_reported(self):
        spec = free_spec(
            [box("a", 40, 40, 200, 80), box("b", 600, 180)],
            [{"pts": [[140, 120], [600, 210]], "from": "a", "to": "b",
              "label": "挤住了", "lx": 140, "ly": 129}])
        self.assertIn("label-clearance", codes(spec))

    def test_a_label_with_room_is_not_reported(self):
        spec = free_spec(
            [box("a", 40, 40, 200, 80), box("b", 600, 200)],
            [{"pts": [[240, 80], [600, 230]], "from": "a", "to": "b",
              "label": "有空间", "lx": 420, "ly": 150}])
        self.assertNotIn("label-clearance", codes(spec))


class ConvergingPortTest(unittest.TestCase, EngineContractMixin):
    """Edges meeting at one node must not stack their arrowheads."""

    def spec(self):
        return {
            "id": "conv", "layout": "dag",
            "nodes": [node("split", "起", None, "indigo"),
                      node("a", "A", None, "teal"),
                      node("b", "B", None, "teal"),
                      node("c", "C", None, "teal"),
                      node("join", "汇合", None, "violet")],
            "edges": [{"from": "split", "to": n} for n in ("a", "b", "c")]
                     + [{"from": n, "to": "join"} for n in ("a", "b", "c")],
            "options": {"center_sinks": True},
        }

    def test_every_edge_into_one_node_gets_its_own_port(self):
        sc = render(self.spec())
        ends = [i.pts[-1] for i in sc.items
                if i.kind == "edge" and i.endpoints[1] == "join"]
        self.assertEqual(3, len(ends))
        self.assertEqual(3, len(set(ends)),
                         f"arrowheads are stacked: {ends}")

    def test_distinct_ports_stay_inside_the_target_box(self):
        sc = render(self.spec())
        target = sc.get("join").bbox
        for it in sc.items:
            if it.kind != "edge" or it.endpoints[1] != "join":
                continue
            x, y = it.pts[-1]
            self.assertGreaterEqual(y, target.y - 1)
            self.assertLessEqual(y, target.bottom + 1)

    def test_crossings_can_be_declared(self):
        spec = self.spec()
        spec["options"]["allow_crossing"] = True
        sc = specs.render(spec)
        self.assertTrue(getattr(sc, "allow_crossing", False))
        self.assertNotIn("edge-crossing", {f.code for f in V.check_scene(sc)})


class LabelOverBandTest(unittest.TestCase, EngineContractMixin):
    """A note dropped on a band used to collide with nothing the checker saw."""

    def spec(self, note_y):
        return {
            "id": "bandnote", "layout": "layers", "size": [900, 420],
            "nodes": [node("n1", "甲", None, "indigo"), node("n2", "乙", None, "indigo")],
            "groups": [{"label": "第一层", "sub": "副标题", "kind": "indigo",
                        "cols": 2, "nodes": ["n1", "n2"]}],
            "options": {"margin": 30, "allow_isolated": True},
            "notes": [{"type": "text", "x": 30, "y": note_y, "text": "放在层上的注释"}],
        }

    def test_a_note_inside_a_band_is_reported(self):
        self.assertIn("label-collision", codes(self.spec(40)))

    def test_a_note_in_its_own_strip_is_clean(self):
        self.assertNotIn("label-collision", codes(self.spec(8)))


class FigureStylesTest(unittest.TestCase, EngineContractMixin):
    """Every class a figure emits must be styled by the document stylesheet.

    The figure rules used to live in two sheets -- one for the exported .svg,
    one for the embedded page -- so a class could work in the export and be
    silently unstyled in the actual document. Asserting the *rendered* markup
    against the composed sheet is what makes that impossible.
    """

    def spec(self):
        """A figure that exercises the less common roles."""
        return {
            "id": "roles", "layout": "free", "size": [900, 420],
            "nodes": [
                box("a", 40, 60, 200, 110) | {
                    "as_card": True, "title": "甲", "sub": "说明",
                    "items": ["field_one", "field_two"], "item_code": True,
                    "kind": "indigo"},
                box("b", 320, 60, 180, 70) | {"as_chip": True, "title": "chip"},
            ],
            "connectors": [
                {"pts": [[240, 100], [316, 100]], "from": "a", "to": "b",
                 "label": "连线", "lx": 278, "ly": 84},
            ],
            "bands": [{"x": 20, "y": 200, "w": 400, "h": 120,
                       "label": "分层", "sub": "副标题", "kind": "teal"}],
            "notes": [
                {"type": "text", "x": 40, "y": 260, "text": "图注", "cls": "d-fig-t"},
                {"type": "text", "x": 40, "y": 286, "text": "次级注", "cls": "d-sub"},
                {"type": "tag", "x": 300, "y": 260, "text": "标签"},
                {"type": "legend", "x": 40, "y": 340,
                 "entries": [["teal", "图例项"]]},
            ],
            "options": {"allow_isolated": True},
        }

    def used_classes(self):
        from docforge import specs as S
        svg = S.render_svg(S.load(self._written()), standalone=False)
        found = set()
        for attr in re.findall(r'class="([^"]+)"', svg):
            found.update(attr.split())
        return found, svg

    def _written(self):
        import json, tempfile, pathlib as pl
        f = pl.Path(tempfile.mkdtemp()) / "roles.json"
        f.write_text(json.dumps(self.spec(), ensure_ascii=False))
        return f

    def test_every_emitted_class_is_defined_in_the_document_sheet(self):
        from docforge.theme import Theme, document_css
        css = document_css(Theme.load("paper"))
        classes, _ = self.used_classes()
        self.assertTrue(classes, "the fixture rendered nothing")
        defined = set()
        for sel in re.findall(r'([^{}]+)\{', css):
            for part in sel.split(","):
                defined.update(re.findall(r'\.([A-Za-z][\w-]*)', part))
        # Grouping hooks the renderer emits but no rule targets: `nd` wraps a
        # node, `tg` a tag group, and the default kind deliberately has no
        # modifier rule. Everything else must resolve to a selector.
        HOOKS = {"nd", "tg", "k-default", "k-line"}
        truly_missing = sorted(classes - defined - HOOKS)
        self.assertEqual([], truly_missing,
                         f"rendered but unstyled in the document: {truly_missing}")

    def test_the_export_and_the_page_share_one_sheet(self):
        """No rule may exist in only one of the two paths."""
        from docforge.theme import document_css, svg_css, Theme
        page = document_css(Theme.load("paper"))
        standalone = svg_css()
        figure_rules = [s.strip() for s in re.findall(r'^(\.dg [^{]+)\{',
                                                      standalone, re.M)]
        self.assertTrue(figure_rules)
        for sel in figure_rules:
            self.assertIn(sel, page, f"{sel} is missing from the document sheet")


class LifelineVisibilityTest(unittest.TestCase, EngineContractMixin):
    """A lane lifeline is an item, so it cannot silently cut a label."""

    def test_lifelines_are_registered_as_items(self):
        spec = {"id": "lifeline", "layout": "sequence", "size": [900, 400],
                "lanes": [node("l1", "左", None, "default"),
                          node("l2", "右", None, "default")],
                "messages": [{"from": "l1", "to": "l2", "label": "一次调用"}]}
        sc = render(spec)
        decor = [i for i in sc.items if i.meta.get("decor")]
        self.assertEqual(2, len(decor), "one lifeline per lane")
        self.assertTrue(all(i.kind == "edge" for i in decor))
        for it in decor:
            self.assertGreater(it.meta.get("length", 0), 0)

    def test_a_lifeline_crossing_a_label_is_reported(self):
        spec = free_spec(
            [box("a", 40, 40), box("b", 600, 40),
             box("c", 40, 280), box("e", 320, 10, 120, 50)],
            [{"pts": [[160, 70], [600, 70]], "from": "a", "to": "b",
              "label": "被切断", "lx": 380, "ly": 54},
             {"pts": [[380, 300], [380, 30]], "from": "c", "to": "e"}])
        found = {f.code for f in V.check_scene(specs.render(spec))}
        self.assertIn("edge-over-label", found)


if __name__ == "__main__":
    unittest.main()
