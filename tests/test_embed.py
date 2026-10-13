"""Nesting: a node that holds a whole other figure.

Two properties carry this feature, and both are easy to lose:

* the child is drawn 1:1 in its own coordinate space -- never scaled, because
  scaling a figure scales its type with it;
* the child is still *validated*, in its own right, with findings labelled by
  the path they came from. A nested figure must not be a way to get a broken
  diagram past the checker.
"""

from __future__ import annotations

import re
import unittest

from docforge import specs
from docforge import validate as V
from docforge.layouts import EMBED_DEPTH


def inner(size=(420, 110), layout="pipeline", **extra):
    """A small, valid figure to nest."""
    spec = {
        "id": "inner", "layout": layout, "size": list(size),
        "nodes": [{"id": "p", "title": "A"}, {"id": "q", "title": "B"}],
        "edges": [{"from": "p", "to": "q"}],
    }
    spec.update(extra)
    return spec


def host(sub=None, **node):
    """A one-host figure, plus a plain node so the canvas has a second thing."""
    node = {"id": "host", "title": "子系统", "sub_spec": sub or inner(),
            "x": 40, "y": 40, **node}
    return {
        "id": "outer", "layout": "free", "size": [900, 520],
        "nodes": [node, {"id": "plain", "title": "普通", "x": 40, "y": 330,
                         "width": 160, "height": 54}],
        "options": {"allow_isolated": True},
    }


class EmbedContractTest(unittest.TestCase):
    def test_a_host_is_sized_to_fit_the_figure_it_holds(self):
        sc = specs.render(host())
        box = sc.get("host").bbox
        self.assertGreater(box.w, 420, "the host must be at least as wide as its child")
        self.assertGreater(box.h, 110, "and at least as tall")

    def test_the_child_is_recorded_on_the_parent(self):
        sc = specs.render(host())
        self.assertEqual(["host"], list(sc.children))
        child = sc.children["host"]
        self.assertEqual("outer/host", child.uid, "the child's uid is its path")

    def test_the_output_has_one_svg_not_two(self):
        """A nested <svg> opens a viewport and would scale the child."""
        svg = specs.render(host()).svg(standalone=False)
        self.assertEqual(1, svg.count("<svg"))
        self.assertIn("<g transform=", svg)

    def test_sibling_markers_cannot_collide(self):
        spec = host()
        spec["nodes"].append({"id": "host2", "title": "另一个子系统",
                              "sub_spec": inner(), "x": 40, "y": 430})
        svg = specs.render(spec).svg(standalone=False)
        ids = re.findall(r'<marker id="([^"]+)"', svg)
        self.assertEqual(len(ids), len(set(ids)), f"marker ids collide: {ids}")
        namespaces = {i.rsplit("-", 1)[0] for i in ids}
        self.assertEqual(3, len(namespaces), "parent plus two children")

    def test_a_top_level_figure_keeps_readable_marker_ids(self):
        """Existing documents must not churn just because nesting exists."""
        spec = host()
        spec.pop("nodes")           # a plain figure, no nesting
        spec["nodes"] = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
        spec["edges"] = [{"from": "a", "to": "b"}]
        svg = specs.render(spec).svg(standalone=False)
        self.assertIn('id="mouter-indigo"', svg)

    def test_nesting_is_deterministic(self):
        spec = host()
        self.assertEqual(specs.render(spec).svg(), specs.render(spec).svg())

    def test_the_same_spec_can_be_rendered_twice_without_stale_children(self):
        spec = host()
        first = specs.render(spec).children["host"].uid
        second = specs.render(spec).children["host"].uid
        self.assertEqual(first, second)


class EmbedValidationTest(unittest.TestCase):
    """The checker sees inside, and names where it looked."""

    def broken_child(self):
        return {"id": "inner", "layout": "free", "size": [420, 200],
                "nodes": [{"id": "a", "as": "cell", "x": 20, "y": 20,
                           "width": 60, "height": 40, "value": "一个绝对放不下的值"},
                          {"id": "b", "as": "cell", "x": 40, "y": 40,
                           "width": 160, "height": 90, "value": "重叠"}],
                "options": {"allow_isolated": True}}

    def test_a_finding_inside_a_nested_figure_surfaces(self):
        found = V.check_scene(specs.render(host(self.broken_child())))
        codes = {f.code for f in found}
        self.assertIn("text-overflow", codes)
        self.assertIn("box-overlap", codes)

    def test_the_finding_carries_the_path_it_came_from(self):
        found = V.check_scene(specs.render(host(self.broken_child())))
        self.assertTrue(found)
        for f in found:
            self.assertEqual("outer/host", f.figure,
                             "a nested finding must name where it lives")

    def test_a_clean_child_leaves_the_parent_clean(self):
        self.assertEqual([], V.check_scene(specs.render(host())))

    def test_a_host_too_small_for_its_child_is_reported(self):
        spec = host()
        spec["nodes"][0]["width"] = 200       # far narrower than the 420px child
        spec["nodes"][0]["height"] = 80
        codes = {f.code for f in V.check_scene(specs.render(spec))}
        self.assertIn("embed-overflow", codes)

    def test_an_embed_is_a_box_for_the_parent_checks(self):
        spec = host()
        spec["nodes"].append({"id": "clash", "title": "压上去",
                              "x": 60, "y": 60, "width": 160, "height": 54})
        codes = {f.code for f in V.check_scene(specs.render(spec))}
        self.assertIn("box-overlap", codes)


class EmbedDepthTest(unittest.TestCase):
    def nested(self, levels):
        """A chain of figures, each hosting the next."""
        node = {"id": f"leaf{levels}", "title": "叶子"}
        spec = {"id": f"lvl{levels}", "layout": "free", "size": [400, 300],
                "nodes": [node], "options": {"allow_isolated": True}}
        for depth in range(levels - 1, -1, -1):
            spec = {"id": f"lvl{depth}", "layout": "free", "size": [900, 500],
                    "nodes": [{"id": f"sub{depth}", "title": "层",
                               "sub_spec": spec, "x": 30, "y": 30}],
                    "options": {"allow_isolated": True}}
        return spec

    def test_nesting_up_to_the_limit_is_fine(self):
        specs.render(self.nested(EMBED_DEPTH))     # must not raise

    def test_nesting_past_the_limit_is_an_error_not_a_hang(self):
        with self.assertRaises(ValueError) as caught:
            specs.render(self.nested(EMBED_DEPTH + 2))
        self.assertIn("nested deeper than", str(caught.exception))


class EveryEngineDeclaresASizeTest(unittest.TestCase):
    """`render` requires plan.size. An engine that forgets must fail loudly."""

    def test_render_says_so_when_an_engine_forgets(self):
        from docforge import layouts
        from docforge.layouts import Plan

        saved = layouts.LAYOUTS["free"]

        def forgetful(spec):
            return Plan()          # places nothing, declares nothing

        layouts.LAYOUTS["free"] = forgetful
        try:
            with self.assertRaises(ValueError) as caught:
                specs.render({"id": "x", "layout": "free", "size": [400, 200],
                              "nodes": []})
            self.assertIn("did not declare a size", str(caught.exception))
        finally:
            layouts.LAYOUTS["free"] = saved

    def test_every_shipped_engine_declares_one(self):
        from docforge import layouts
        from docforge.layouts import Plan

        for name in sorted(layouts.LAYOUTS):
            with self.subTest(engine=name):
                original = layouts.LAYOUTS[name]
                seen = {}

                def spy(spec, _o=original, _n=name):
                    plan = _o(spec)
                    seen[_n] = bool(plan.size)
                    return plan

                layouts.LAYOUTS[name] = spy
                try:
                    specs.render(specs.load(
                        f"examples/engines/{'intent' if name == 'fan' else name}"
                        f".{name}.json"))
                except FileNotFoundError:
                    continue
                finally:
                    layouts.LAYOUTS[name] = original
                self.assertTrue(seen.get(name), f"{name} did not set plan.size")


if __name__ == "__main__":
    unittest.main()
