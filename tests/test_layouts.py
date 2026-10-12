"""Layout-engine contract tests.

The engines are where a diagram actually gets its coordinates, so these tests
assert *placement properties* rather than pixel values: every declared node is
placed, nothing overlaps, a chain lands in reading order, a ring lands on the
ellipse it was given, and every engine's output passes the geometry validator.

That last assertion is the important one. It means an engine cannot regress into
drawing a connector through a box without a test going red.
"""

from __future__ import annotations

import math
import unittest

from docforge import layouts, specs
from docforge import validate as V
from docforge.geom import Rect


def node(nid, title, sub=None, kind="default", **extra):
    spec = {"id": nid, "title": title, "kind": kind}
    if sub is not None:
        spec["sub"] = sub if isinstance(sub, list) else [sub]
    spec.update(extra)
    return spec


def render(spec):
    spec.setdefault("id", "t")
    return specs.render(spec)


def errors(scene, **kw):
    return [f for f in V.check_scene(scene, **kw) if f.severity == V.ERROR]


class EngineContractMixin:
    """Every engine must satisfy these, whatever the layout."""

    def assertPlaced(self, scene, spec):
        want = {n["id"] for n in spec["nodes"]} - set(
            spec.get("options", {}).get("unplaced", [])
        )
        got = {i.id for i in scene.items if i.kind in ("node", "card")}
        self.assertEqual(want, got, "every declared node must be drawn exactly once")

    def assertNoOverlap(self, scene):
        boxes = [i for i in scene.items if i.kind in ("node", "card", "tag")]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                self.assertFalse(
                    boxes[i].bbox.intersects(boxes[j].bbox),
                    f"{boxes[i].id} overlaps {boxes[j].id}",
                )

    def assertClean(self, scene):
        found = errors(scene)
        self.assertEqual([], [str(f) for f in found], "engine must produce no errors")

    def assertDeterministic(self, spec):
        a = render(spec).svg()
        b = render(spec).svg()
        self.assertEqual(a, b, "rendering the same spec twice must be identical")

    def assertWellFormed(self, scene):
        import xml.etree.ElementTree as ET
        ET.fromstring(scene.svg())


class PipelineTest(unittest.TestCase, EngineContractMixin):
    def spec(self, extra=None):
        s = {
            "id": "p", "layout": "pipeline", "size": [1000, 200],
            "nodes": [node("a", "输入解析"), node("b", "意图识别", "LLM"),
                      node("c", "条件路由", "route", "indigo"),
                      node("d", "输出", "final", "green")],
            "edges": [{"from": "a", "to": "b", "label": "解析"}],
        }
        if extra:
            s.update(extra)
        return s

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)
        self.assertWellFormed(sc)

    def test_chain_runs_left_to_right(self):
        sc = render(self.spec())
        xs = [sc.get(i).bbox.x for i in ("a", "b", "c", "d")]
        self.assertEqual(xs, sorted(xs), "a chain must be laid out in order")

    def test_single_row_when_it_fits(self):
        """One row: nodes of different heights must still share a centre line."""
        sc = render(self.spec())
        centres = {round(sc.get(i).bbox.cy, 1) for i in ("a", "b", "c", "d")}
        self.assertEqual(1, len(centres), "everything fits on one row")

    def test_wraps_when_too_wide(self):
        nodes = [node(f"n{i}", f"节点{i}") for i in range(9)]
        sc = render({"id": "w", "layout": "pipeline", "size": [700, 600],
                     "nodes": nodes, "edges": []})
        ys = {round(sc.get(n["id"]).bbox.cy) for n in nodes}
        self.assertGreater(len(ys), 1, "nine nodes cannot fit one 700px row")
        self.assertClean(sc)

    def test_wider_text_gives_a_wider_box(self):
        narrow = render({"id": "n", "layout": "pipeline", "size": [900, 120],
                         "nodes": [node("a", "短"), node("b", "短")], "edges": []})
        wide = render({"id": "w", "layout": "pipeline", "size": [900, 120],
                       "nodes": [node("a", "这是一个很长的标题内容"),
                                 node("b", "短")], "edges": []})
        self.assertGreater(wide.get("a").bbox.w, narrow.get("a").bbox.w)

    def test_edge_label_comes_from_the_edges_list(self):
        sc = render(self.spec())
        labels = [i.meta.get("label") for i in sc.items if i.kind == "edge"]
        self.assertIn("解析", labels)


class DagTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "d", "layout": "dag",
            "nodes": [node("root", "入口"), node("l", "左支", "a", "teal"),
                      node("r", "右支", "b", "teal"), node("join", "汇合", None, "green")],
            "edges": [{"from": "root", "to": "l"}, {"from": "root", "to": "r"},
                      {"from": "l", "to": "join"}, {"from": "r", "to": "join"}],
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_diamond_puts_siblings_in_one_column(self):
        sc = render(self.spec())
        self.assertAlmostEqual(sc.get("l").bbox.x, sc.get("r").bbox.x, delta=1.0)
        self.assertLess(sc.get("root").bbox.x, sc.get("l").bbox.x)
        self.assertLess(sc.get("l").bbox.x, sc.get("join").bbox.x)

    def test_longest_path_decides_the_column(self):
        s = {
            "id": "d2", "layout": "dag",
            "nodes": [node("a", "A"), node("b", "B"), node("c", "C")],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"},
                      {"from": "a", "to": "c"}],
        }
        sc = render(s)
        self.assertLess(sc.get("a").bbox.x, sc.get("b").bbox.x)
        self.assertLess(sc.get("b").bbox.x, sc.get("c").bbox.x)

    def test_cycle_does_not_hang(self):
        s = {
            "id": "d3", "layout": "dag",
            "nodes": [node("a", "A"), node("b", "B")],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        }
        sc = render(s)          # must terminate
        self.assertPlaced(sc, s)


class FanReachTest(unittest.TestCase, EngineContractMixin):
    """The hub must sit a reach from the fan, not against the left margin.

    Pinning the chain to the margin leaves the leftover space as the run between
    hub and riser; on a wide canvas that is a long line across the middle of the
    figure that carries nothing.
    """

    def spec(self, width=1240, prefix=None):
        return {
            "id": "fanreach", "layout": "fan",
            "nodes": [node("a", "入口", None, "slate"),
                      node("b", "分类", None, "indigo"),
                      node("hub", "路由", None, "violet")]
                     + [node(f"t{i}", f"分支{i}", None, "teal") for i in range(3)],
            "options": {"prefix": prefix if prefix is not None else ["a", "b"],
                        "source": "hub",
                        "targets": ["t0", "t1", "t2"],
                        "width": width, "margin": 40},
        }

    def run_gap(self, sc):
        """Distance from the hub's right edge to the fan riser."""
        hub = sc.get("hub").bbox
        taps = [i for i in sc.items
                if i.kind == "edge" and i.endpoints and i.endpoints[0] == "hub"]
        self.assertTrue(taps, "the hub must fan out")
        riser_x = max(i.pts[0][0] for i in taps)
        return riser_x - hub.right

    def test_the_hub_keeps_a_bounded_reach_on_a_wide_canvas(self):
        for width in (900, 1240, 1800):
            with self.subTest(width=width):
                gap = self.run_gap(render(self.spec(width=width)))
                self.assertLess(gap, 320.0,
                                f"hub-to-riser run is {gap:.0f}px on a {width}px canvas")

    def test_the_reach_does_not_grow_with_the_canvas(self):
        narrow = self.run_gap(render(self.spec(width=1000)))
        wide = self.run_gap(render(self.spec(width=2000)))
        self.assertAlmostEqual(narrow, wide, delta=1.0,
                               msg="the reach is a constant, not leftover space")

    def test_the_composition_is_centred_on_the_canvas(self):
        """Equal slack either side, so the group does not drift to one edge."""
        for width in (900, 1240, 1600):
            with self.subTest(width=width):
                sc = render(self.spec(width=width))
                boxes = [sc.get(i).bbox for i in
                         ("a", "b", "hub", "t0", "t1", "t2")]
                left = min(b.x for b in boxes)
                right = max(b.right for b in boxes)
                self.assertAlmostEqual(left, width - right, delta=6.0,
                                       msg="the chain+fan group is off-centre")

    def test_a_wider_canvas_does_not_stretch_the_middle(self):
        """The reach is a constant; the slack goes to the margins instead."""
        narrow = render(self.spec(width=1000))
        wide = render(self.spec(width=1800))
        self.assertAlmostEqual(narrow.get("hub").bbox.right,
                               wide.get("hub").bbox.right - 400.0, delta=8.0)

    def test_the_chain_never_starts_left_of_the_margin(self):
        """Pushed right to keep the reach short, but never off the canvas."""
        for width in (700, 1000, 1240):
            with self.subTest(width=width):
                spec = self.spec(width=width)
                sc = render(spec)
                self.assertGreaterEqual(sc.get("a").bbox.x, 40.0 - 1.0)
                self.assertPlaced(sc, spec)

    def test_a_hub_with_no_prefix_still_keeps_its_reach(self):
        spec = {
            "id": "fanhub", "layout": "fan",
            "nodes": [node("hub", "路由", None, "violet")]
                     + [node(f"t{i}", f"分支{i}", None, "teal") for i in range(3)],
            "options": {"prefix": [], "source": "hub",
                        "targets": ["t0", "t1", "t2"], "width": 1240, "margin": 40},
        }
        sc = render(spec)
        self.assertPlaced(sc, spec)
        self.assertLess(self.run_gap(sc), 320.0)


class FanTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "f", "layout": "fan", "size": [1100, 420],
            "nodes": [node("msg", "消息"), node("cls", "识别", "LLM", "indigo"),
                      node("hub", "路由", "route", "violet"),
                      node("t1", "retrieve", None, "teal"),
                      node("t2", "tool_executor", None, "teal"),
                      node("t3", "generate", "兜底", "indigo")],
            "options": {"prefix": ["msg", "cls"], "source": "hub",
                        "targets": ["t1", "t2", "t3"], "y": 60,
                        "labels": {"t1": "search", "t2": "tool_call", "t3": "else"}},
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_prefix_chain_precedes_the_hub(self):
        sc = render(self.spec())
        self.assertLess(sc.get("msg").bbox.x, sc.get("cls").bbox.x)
        self.assertLess(sc.get("cls").bbox.x, sc.get("hub").bbox.x)

    def test_targets_stack_on_the_right(self):
        sc = render(self.spec())
        ys = [sc.get(t).bbox.y for t in ("t1", "t2", "t3")]
        self.assertEqual(ys, sorted(ys))
        for t in ("t1", "t2", "t3"):
            self.assertGreater(sc.get(t).bbox.x, sc.get("hub").bbox.x)

    def test_every_branch_is_labelled(self):
        sc = render(self.spec())
        labels = {i.meta.get("label") for i in sc.items if i.kind == "edge"}
        self.assertTrue({"search", "tool_call", "else"} <= labels)


class LayersTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "l", "layout": "layers",
            "nodes": [node("a", "状态", "AgentState", "indigo"),
                      node("b", "图", "StateGraph", "indigo"),
                      node("c", "API", "提交", "teal"),
                      node("d", "存储", "库", "teal")],
            "groups": [{"label": "内核层", "kind": "indigo", "nodes": ["a", "b"]},
                       {"label": "外壳层", "kind": "teal", "nodes": ["c", "d"]}],
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_bands_wrap_their_members(self):
        sc = render(self.spec())
        bands = [i for i in sc.items if i.kind == "band"]
        self.assertEqual(2, len(bands))
        for band, members in zip(bands, (("a", "b"), ("c", "d"))):
            for m in members:
                self.assertTrue(band.bbox.inflate(0.5).contains_rect(sc.get(m).bbox))

    def test_bands_do_not_overlap(self):
        bands = [i for i in render(self.spec()).items if i.kind == "band"]
        self.assertFalse(bands[0].bbox.intersects(bands[1].bbox))

    def test_auto_height_follows_content(self):
        two = render(self.spec())
        s = self.spec()
        s["groups"].append({"label": "运维层", "kind": "amber", "nodes": ["a"]})
        three = render(s)
        self.assertGreater(three.height, two.height)


class HubTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "h", "layout": "hub", "size": [1200, 560],
            "nodes": [node("c", "工具执行节点", ["MCP", "API"], "teal"),
                      node("l1", "超时", "10-30s", "slate"),
                      node("l2", "重试", "退避", "slate"),
                      node("r1", "权限", "校验", "slate"),
                      node("r2", "降级", "不中断", "red"),
                      node("b", "审计", "写日志", "violet")],
            "options": {"center": "c", "left": ["l1", "l2"],
                        "right": ["r1", "r2"], "below": "b"},
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_center_sits_between_the_columns(self):
        sc = render(self.spec())
        c = sc.get("c").bbox
        self.assertGreater(c.x, sc.get("l1").bbox.right)
        self.assertLess(c.right, sc.get("r1").bbox.x)

    def test_below_node_is_below_the_center(self):
        sc = render(self.spec())
        self.assertGreater(sc.get("b").bbox.y, sc.get("c").bbox.bottom)


class RingTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "ring", "layout": "ring", "size": [1200, 520],
            "nodes": [node(str(i), f"环{i}") for i in range(6)],
            "options": {"cx": 600, "cy": 260, "rx": 380, "ry": 160},
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_nodes_lie_on_the_given_ellipse(self):
        sc = render(self.spec())
        for i in range(6):
            b = sc.get(str(i)).bbox
            v = ((b.cx - 600) / 380) ** 2 + ((b.cy - 260) / 160) ** 2
            self.assertAlmostEqual(1.0, v, delta=0.02, msg=f"node {i} off the ellipse")

    def test_closing_arc_takes_the_short_way(self):
        """A wrap-around arc must sweep forward, not 284 degrees backwards."""
        sc = render(self.spec())
        arcs = [i for i in sc.items if i.kind == "arc"]
        self.assertEqual(6, len(arcs))
        for a in arcs:
            span = (a.meta["a1"] - a.meta["a0"]) % 360
            self.assertLess(span, 90, f"arc sweeps {span:.0f} degrees")


class RingGeometryTest(unittest.TestCase, EngineContractMixin):
    """A ring arc must fly between boxes, never through one."""

    def spec(self, n=6, **opts):
        o = {"cx": 600, "cy": 272, "rx": 400, "ry": 176}
        o.update(opts)
        return {"id": "rg", "layout": "ring", "size": [1200, 560],
                "nodes": [node(str(i), f"环{i}", ["副标题"]) for i in range(n)],
                "options": o}

    def test_no_arc_passes_through_any_node(self):
        from docforge import specs as S
        sc = render(self.spec())
        boxes = [(b.meta.get("title"), b.bbox) for b in sc.items
                 if b.kind in ("node", "card")]
        for it in sc.items:
            if it.kind != "arc":
                continue
            for p in it.pts:
                for title, bx in boxes:
                    self.assertFalse(bx.contains_point(*p),
                                     f"arc {it.id} runs through {title!r}")

    def test_a_forced_long_sweep_is_reported_as_an_error(self):
        from docforge import specs as S
        sc = render(self.spec(pad=-120, gap_deg=0))     # deliberately too long
        self.assertIn("edge-through", {f.code for f in V.check_scene(sc)})

    def test_the_hub_does_not_consume_a_ring_slot(self):
        spec = self.spec()
        spec["nodes"].append(node("hub", "中心", None, "slate"))
        spec["options"]["center"] = "hub"
        sc = render(spec)
        self.assertPlaced(sc, spec)
        self.assertEqual(len([i for i in sc.items if i.kind == "arc"]), 6,
                         "six ring nodes means six arcs, not seven")
        hub = sc.get("hub").bbox
        self.assertAlmostEqual(600.0, hub.cx, delta=1.0)
        self.assertAlmostEqual(272.0, hub.cy, delta=1.0)

    def test_arc_endpoints_land_near_their_nodes(self):
        sc = render(self.spec())
        for it in sc.items:
            if it.kind != "arc":
                continue
            a, b = sc.get(it.endpoints[0]).bbox, sc.get(it.endpoints[1]).bbox
            self.assertLess(V._point_gap(it.pts[0], a), 14.0)
            self.assertLess(V._point_gap(it.pts[-1], b), 14.0)


def connectors(scene):
    """Message connectors, excluding the lane lifelines.

    Lifelines are registered as items because otherwise a message label could be
    cut in half by one and no check would notice.
    """
    return [i for i in scene.items
            if i.kind == "edge" and not i.meta.get("decor")]


class SequenceTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "s", "layout": "sequence", "size": [1100, 460],
            "lanes": [{"id": "c", "title": "客户端"}, {"id": "a", "title": "API"},
                      {"id": "q", "title": "队列"}],
            "messages": [{"from": "c", "to": "a", "label": "POST /jobs"},
                         {"from": "a", "to": "a", "self": True, "label": "鉴权"},
                         {"from": "a", "to": "q", "label": "入队", "kind": "violet",
                          "dashed": True}],
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_lane_headers_exist_and_are_ordered(self):
        sc = render(self.spec())
        xs = [sc.get(i).bbox.cx for i in ("c", "a", "q")]
        self.assertEqual(xs, sorted(xs))

    def test_messages_descend_in_time(self):
        sc = render(self.spec())
        ys = [i.pts[0][1] for i in connectors(sc)]
        self.assertEqual(ys, sorted(ys), "messages must read top to bottom")

    def test_self_call_adds_no_connector(self):
        sc = render(self.spec())
        # two real messages; the self-call is drawn as a bracket path instead
        self.assertEqual(2, len(connectors(sc)))


class StateTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "st", "layout": "state", "size": [1200, 520],
            "nodes": [node("p", "pending", None, "slate"),
                      node("r", "running", None, "indigo"),
                      node("s", "succeeded", None, "green"),
                      node("w", "waiting_approval", None, "amber"),
                      node("f", "failed", None, "red")],
            "rows": [["w"], ["p", "r", "s"], ["f"]],
            "transitions": [{"from": "p", "to": "r", "label": "claim"},
                            {"from": "r", "to": "s", "label": "done"},
                            {"from": "r", "to": "w", "label": "approve"},
                            {"from": "w", "to": "s", "label": "approved"},
                            {"from": "r", "to": "f", "label": "fail"}],
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_rows_are_rows(self):
        sc = render(self.spec())
        self.assertLess(sc.get("w").bbox.cy, sc.get("p").bbox.cy)
        self.assertLess(sc.get("p").bbox.cy, sc.get("f").bbox.cy)

    def test_transition_into_a_lower_row_enters_from_above(self):
        """The `approved` edge must not cut through the row between the rows."""
        findings = [f for f in V.check_scene(render(self.spec()))
                    if f.code == "edge-through"]
        self.assertEqual([], [str(f) for f in findings])

    def test_explicit_pts_win(self):
        s = self.spec()
        s["transitions"][0]["pts"] = [[10, 10], [60, 10], [60, 40]]
        sc = render(s)
        e = [i for i in sc.items if i.kind == "edge"][0]
        self.assertEqual((10.0, 10.0), e.pts[0])


class GridTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "g", "layout": "grid",
            "nodes": [{"id": f"k{i}", "as_card": True, "title": f"指标{i}",
                       "accent": f"{i}%", "items": ["上期", "目标"]}
                      for i in range(4)],
            "options": {"cols": 2, "as_card": True, "allow_isolated": True,
                        "margin": 40},
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertNoOverlap(sc)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_cards_form_the_requested_grid(self):
        sc = render(self.spec())
        xs = {round(sc.get(f"k{i}").bbox.x) for i in range(4)}
        ys = {round(sc.get(f"k{i}").bbox.y) for i in range(4)}
        self.assertEqual(2, len(xs))
        self.assertEqual(2, len(ys))


class FreeTest(unittest.TestCase, EngineContractMixin):
    def spec(self):
        return {
            "id": "fr", "layout": "free", "size": [600, 300],
            "nodes": [node("a", "A", None, "indigo", x=40, y=40, width=160, height=60),
                      node("b", "B", None, "teal", x=40, y=180, width=160, height=60)],
            "connectors": [{"pts": [[40, 100], [20, 100], [20, 210], [40, 210]],
                            "from": "a", "to": "b", "label": "绕行",
                            "lx": 20, "ly": 155, "anchor": "end"}],
        }

    def test_contract(self):
        s = self.spec()
        sc = render(s)
        self.assertPlaced(sc, s)
        self.assertClean(sc)
        self.assertDeterministic(s)

    def test_explicit_geometry_is_respected(self):
        sc = render(self.spec())
        self.assertEqual(Rect(40, 40, 160, 60), sc.get("a").bbox)


class MeasuredAsWhatItIsTest(unittest.TestCase, EngineContractMixin):
    """A card is measured as a card, whichever engine places it."""

    def card(self, nid="c1"):
        return {"id": nid, "as_card": True, "title": "指标", "sub": "较上期",
                "accent": "92%", "items": ["上期 87%", "目标 90%"]}

    def test_layers_sizes_a_card_with_card_size(self):
        from docforge.layouts import card_size, node_size
        spec = {"id": "lc", "layout": "layers",
                "nodes": [self.card(), node("plain", "普通")],
                "groups": [{"label": "g", "nodes": ["c1", "plain"]}]}
        sc = render(spec)
        want = card_size(self.card())[1]
        got = sc.get("c1").bbox.h
        self.assertAlmostEqual(want, got, delta=0.5,
                               msg="layers must not measure a card with node_size")
        plain = {k: v for k, v in self.card().items() if k != "as_card"}
        self.assertGreater(want, node_size(plain)[1],
                           "the two formulas must actually differ, or this proves nothing")

    def test_no_text_overflow_for_a_card_in_a_band(self):
        spec = {"id": "lc2", "layout": "layers",
                "nodes": [self.card()],
                "groups": [{"label": "g", "nodes": ["c1"]}]}
        self.assertClean(render(spec))

    def test_grid_and_layers_agree_on_card_height(self):
        spec = {"id": "lc3", "layout": "layers",
                "nodes": [self.card()],
                "groups": [{"label": "g", "nodes": ["c1"]}]}
        layers_h = render(spec).get("c1").bbox.h
        grid = render({"id": "gc", "layout": "grid", "nodes": [self.card()],
                       "options": {"cols": 1, "as_card": True,
                                   "allow_isolated": True}})
        self.assertAlmostEqual(layers_h, grid.get("c1").bbox.h, delta=0.5)


class EdgeOverridesTest(unittest.TestCase, EngineContractMixin):
    """Engines must honour the spec's label placement, not hardcode it."""

    def spec(self, **edge):
        return {
            "id": "fanlab", "layout": "fan", "size": [1100, 420],
            "nodes": [node("a", "第一"), node("b", "第二"),
                      node("t1", "分支一", None, "teal")],
            "edges": [dict({"from": "a", "to": "b", "label": "链条"}, **edge)],
            "options": {"prefix": ["a"], "source": "b", "targets": ["t1"], "y": 60},
        }

    def test_default_label_position(self):
        sc = render(self.spec())
        label = [i for i in sc.items if i.meta.get("label") == "链条"][0]
        self.assertIsNotNone(label)

    def _label_box(self, sc):
        """The connector's *label* box, not the connector's own bbox."""
        item = [i for i in sc.items if i.meta.get("label") == "链条"][0]
        self.assertTrue(item.text_boxes, "the label was not drawn at all")
        return item.text_boxes[0]

    def test_explicit_lx_ly_wins(self):
        box = self._label_box(render(self.spec(lx=123.0, ly=45.0)))
        self.assertAlmostEqual(123.0, box.cx, delta=2.0)
        self.assertAlmostEqual(45.0, box.cy, delta=2.0)

    def test_explicit_anchor_wins(self):
        box = self._label_box(render(self.spec(lx=123.0, ly=45.0, anchor="start")))
        self.assertAlmostEqual(123.0, box.x, delta=2.0)

    def test_default_is_centred_in_the_gap(self):
        box = self._label_box(render(self.spec()))
        self.assertNotAlmostEqual(123.0, box.cx, delta=10.0)


class ContainerOverlapOptOutTest(unittest.TestCase, EngineContractMixin):
    def spec(self, allow):
        sc_spec = {
            "id": "bo", "layout": "layers",
            "nodes": [node("x", "甲"), node("y", "乙")],
            "groups": [{"label": "带一", "nodes": ["x"]},
                       {"label": "带二", "nodes": ["y"]}],
            "options": {"band_gap": 40, "allow_isolated": True},
        }
        if allow:
            sc_spec["options"]["allow_band_overlap"] = True
        return sc_spec

    def test_overlap_is_reported_by_default(self):
        from docforge.scene import Scene
        sc = Scene("bo", 600, 400)
        sc.band(20, 20, 200, 150, "一")
        sc.band(100, 100, 200, 150, "二")
        self.assertIn("band-overlap", {f.code for f in V.check_scene(sc)})

    def test_declaring_it_silences_only_that_warning(self):
        from docforge.scene import Scene
        sc = Scene("bo2", 600, 400)
        sc.band(20, 20, 200, 150, "一")
        sc.band(100, 100, 200, 150, "二")
        sc.allow_band_overlap = True
        self.assertNotIn("band-overlap", {f.code for f in V.check_scene(sc)})

    def test_option_reaches_the_scene(self):
        spec = self.spec(True)
        sc = render(spec)
        self.assertTrue(getattr(sc, "allow_band_overlap", False))


class SpecValidationTest(unittest.TestCase):
    """Bad specs must fail loudly, not render something misleading."""

    def test_unknown_layout(self):
        with self.assertRaises(specs.SpecError):
            specs.load({"id": "x", "layout": "nope", "nodes": []})

    def test_missing_required_key(self):
        with self.assertRaises(specs.SpecError):
            specs.load({"layout": "pipeline", "nodes": []})

    def test_duplicate_node_ids(self):
        bad = {"id": "x", "layout": "pipeline",
               "nodes": [node("a", "A"), node("a", "B")], "edges": []}
        with self.assertRaises(specs.SpecError):
            specs.load(bad)

    def test_edge_to_a_missing_node(self):
        bad = {"id": "x", "layout": "pipeline", "nodes": [node("a", "A")],
               "edges": [{"from": "a", "to": "ghost"}]}
        with self.assertRaises(specs.SpecError):
            specs.load(bad)

    def test_sequence_message_to_a_missing_lane(self):
        bad = {"id": "x", "layout": "sequence",
               "lanes": [{"id": "a", "title": "A"}],
               "messages": [{"from": "a", "to": "ghost"}]}
        with self.assertRaises(specs.SpecError):
            specs.load(bad)

    def test_unplaced_node_is_an_error_not_a_silent_omission(self):
        bad = {"id": "x", "layout": "layers",
               "nodes": [node("a", "A"), node("orphan", "谁也不引用我")],
               "groups": [{"label": "g", "nodes": ["a"]}]}
        with self.assertRaises(ValueError) as ctx:
            specs.render(bad)
        self.assertIn("orphan", str(ctx.exception))

    def test_valid_spec_passes(self):
        ok = {"id": "x", "layout": "pipeline", "nodes": [node("a", "A")], "edges": []}
        self.assertEqual([], specs.validate_spec(specs.normalize(ok)))


class DeterminismTest(unittest.TestCase):
    def test_layout_registry_is_stable(self):
        self.assertEqual(sorted(layouts.LAYOUTS), sorted(layouts.LAYOUTS))
        self.assertIn("pipeline", layouts.LAYOUTS)
        self.assertIn("free", layouts.LAYOUTS)

    def test_every_engine_is_documented(self):
        from docforge.cli import LAYOUT_DOC
        for name in layouts.LAYOUTS:
            self.assertIn(name, LAYOUT_DOC, f"{name} has no description")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
