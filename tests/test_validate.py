"""Unit tests for ``docforge.validate``.

The package's headline claim is that diagram geometry is *proved* correct
rather than eyeballed.  That claim is worth exactly as much as this file: every
finding code gets a scene that must trigger it **and** a near-miss scene that
must stay silent.
"""

from __future__ import annotations

import unittest

from docforge import text as T
from docforge import validate as V
from docforge.scene import Scene


def _scene(uid, width, height):
    return Scene(uid, width, height)


def codes(scene, **kw):
    return {f.code for f in V.check_scene(scene, **kw)}


def findings(scene, code, **kw):
    return [f for f in V.check_scene(scene, **kw) if f.code == code]


def doc_codes(html, **kw):
    return {f.code for f in V.check_document(html, **kw)}


# --------------------------------------------------------------------------
# text-overflow
# --------------------------------------------------------------------------
class TextOverflowTest(unittest.TestCase):
    LABEL = "Overflow probe title"
    FS = 15.0

    def _scene(self, slack_px):
        """A left-aligned node whose inner width is the label width + slack."""
        sc = _scene("ovf", 400, 200)
        width = 2 * 12.0 + T.tw(self.LABEL, self.FS) + slack_px
        it = sc.node(20, 20, width, 60, self.LABEL, fs=self.FS, align="left")
        return sc, it

    def test_text_exactly_at_the_limit_passes(self):
        sc, it = self._scene(0.0)
        self.assertAlmostEqual(it.text_boxes[0].w, it.inner.w)
        self.assertNotIn("text-overflow", codes(sc))

    def test_text_six_px_over_the_limit_fails(self):
        sc, it = self._scene(-6.0)
        hits = findings(sc, "text-overflow")
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].detail["overflow_x_px"], 6.0, delta=0.01)
        self.assertEqual(hits[0].severity, V.ERROR)
        self.assertEqual(hits[0].item, it.id)
        self.assertEqual(hits[0].figure, sc.uid)

    def test_centred_title_splits_the_overflow_over_both_sides(self):
        sc = _scene("ovf-c", 400, 200)
        sc.node(20, 20, 2 * 12.0 + T.tw(self.LABEL, self.FS) - 6.0, 60,
                self.LABEL, fs=self.FS)  # centred: 3px each side
        hits = findings(sc, "text-overflow")
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].detail["overflow_x_px"], 3.0, delta=0.01)

    def test_vertical_overflow_fails(self):
        sc = _scene("ovf-v", 400, 200)
        sc.node(20, 20, 200, 8, "squashed title", fs=15.0)
        hits = findings(sc, "text-overflow")
        self.assertEqual(len(hits), 1)
        self.assertGreater(hits[0].detail["overflow_x_px"], -1.0)
        self.assertIn("vertically", hits[0].message)

    def test_card_items_overflow(self):
        sc = _scene("ovf-c", 400, 300)
        sc.card(20, 20, 240, 70, "Title", "Sub",
                ["item %d" % i for i in range(6)])
        self.assertIn("text-overflow", codes(sc))

    def test_band_label_is_not_overflow_checked(self):
        # Bands have no inner box: their labels live on the border.
        sc = _scene("ovf-b", 400, 300)
        sc.band(0, 0, 400, 300, label="a band label that is quite long indeed")
        self.assertNotIn("text-overflow", codes(sc))

    def test_small_bleed_is_absorbed_by_the_tolerance(self):
        sc = _scene("ovf-t", 400, 200)
        sc.node(20, 20, 24 + T.tw(self.LABEL, self.FS) - 3.0, 60, self.LABEL,
                fs=self.FS)  # 1.5px of bleed on each side
        self.assertNotIn("text-overflow", codes(sc))
        self.assertIn("text-overflow", codes(sc, overflow_tol=1.0))

    def test_overflow_tolerance_is_configurable(self):
        sc, _ = self._scene(-6.0)
        self.assertIn("text-overflow", codes(sc, overflow_tol=2.0))
        self.assertNotIn("text-overflow", codes(sc, overflow_tol=50.0))


# --------------------------------------------------------------------------
# box-overlap
# --------------------------------------------------------------------------
class BoxOverlapTest(unittest.TestCase):
    def _scene(self, bx):
        sc = _scene("ovl", 500, 200)
        sc.node(20, 20, 100, 60, "A")
        sc.node(bx, 20, 100, 60, "B")
        return sc

    def test_boxes_one_px_apart_pass(self):
        self.assertNotIn("box-overlap", codes(self._scene(121)))

    def test_boxes_that_touch_edges_pass(self):
        self.assertNotIn("box-overlap", codes(self._scene(120)))

    def test_boxes_that_overlap_by_one_px_fail(self):
        hits = findings(self._scene(119), "box-overlap")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)
        self.assertAlmostEqual(hits[0].detail["overlap_area"], 60.0, delta=0.01)

    def test_card_and_tag_are_boxes_too(self):
        sc = _scene("ovl-c", 500, 300)
        sc.card(20, 20, 200, 100, "Card")
        sc.tag(120, 70, "tag")
        self.assertIn("box-overlap", codes(sc))

    def test_a_well_separated_pair_reports_no_overlap(self):
        sc = self._scene(300)
        self.assertNotIn("box-overlap", codes(sc))
        # ...and no errors at all: the two nodes are simply not connected yet.
        self.assertEqual(V.worst(V.check_scene(sc)), V.WARNING)


# --------------------------------------------------------------------------
# edge-through
# --------------------------------------------------------------------------
class EdgeThroughTest(unittest.TestCase):
    def _scene(self, stopper, attach_both=False, from_id=True):
        sc = _scene("eth", 600, 300)
        a = sc.node(20, 140, 80, 40, "A")
        b = sc.node(300, 140, 80, 40, "B")
        sc.edge([(95, 160), (stopper, 160)],
                from_id=a.id if from_id else None,
                to_id=b.id if attach_both else None)
        return sc

    def test_edge_stopping_two_px_short_passes(self):
        self.assertNotIn("edge-through", codes(self._scene(298)))

    def test_edge_stopping_one_px_short_passes(self):
        self.assertNotIn("edge-through", codes(self._scene(299)))

    def test_edge_entering_the_node_fails(self):
        sc = self._scene(340)
        hits = findings(sc, "edge-through")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)
        b = [i for i in sc.items if i.kind == "node"][1]
        self.assertEqual(hits[0].detail["blocked_by"], b.id)

    def test_edge_attached_to_both_endpoints_is_never_reported(self):
        sc = self._scene(340, attach_both=True)
        self.assertNotIn("edge-through", codes(sc))

    def test_edge_attached_to_the_source_only_still_reports_the_target(self):
        sc = self._scene(340, attach_both=False, from_id=True)
        self.assertIn("edge-through", codes(sc))

    def test_edge_with_no_ids_through_both_nodes(self):
        sc = self._scene(340, attach_both=False, from_id=False)
        self.assertEqual(len(findings(sc, "edge-through")), 2)

    def test_edge_outside_a_node_but_sharing_a_coordinate(self):
        # The edge is 90px to the right of the node; its top bend merely
        # shares the y coordinate of the node's (shrunken) top edge.
        sc = _scene("eth-aligned", 400, 400)
        sc.node(100, 60, 60, 40, "B")
        sc.edge([(250, 61), (250, 300)])
        self.assertNotIn("edge-through", codes(sc))

    def test_edge_clear_below_a_node_passes(self):
        sc = _scene("eth-below", 400, 400)
        sc.node(100, 60, 60, 40, "B")          # bottom edge at y = 100
        sc.edge([(150, 130), (150, 200), (60, 200)])
        self.assertNotIn("edge-through", codes(sc))

    def test_edge_through_a_node_between_its_endpoints(self):
        sc = _scene("eth-mid", 600, 300)
        a = sc.node(20, 140, 80, 40, "A")
        m = sc.node(250, 120, 100, 80, "M")
        b = sc.node(480, 140, 80, 40, "B")
        sc.edge([(100, 160), (480, 160)], from_id=a.id, to_id=b.id)
        hits = findings(sc, "edge-through")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail["blocked_by"], m.id)


# --------------------------------------------------------------------------
# label-collision
# --------------------------------------------------------------------------
class LabelCollisionTest(unittest.TestCase):
    def test_label_one_px_clear_passes(self):
        sc = _scene("lbl-ok", 500, 300)
        sc.node(20, 20, 240, 60, "A")          # bottom edge at y = 80
        sc.text(30, 87, "label", fs=12.0)      # box top at y = 81
        self.assertNotIn("label-collision", codes(sc))

    def test_label_touching_a_box_fails(self):
        sc = _scene("lbl-bad", 500, 300)
        sc.node(20, 20, 240, 60, "A")
        sc.text(30, 80, "label", fs=12.0)
        hits = findings(sc, "label-collision")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)

    def test_edge_label_over_a_box_fails(self):
        sc = _scene("lbl-edge", 500, 300)
        sc.node(100, 100, 100, 60, "A")
        sc.edge([(50, 130), (250, 130)], label="ee")
        sc.node(150, 110, 80, 40, "B")
        self.assertIn("label-collision", codes(sc))

    def test_edge_label_in_open_space_passes(self):
        sc = _scene("lbl-edge-ok", 500, 300)
        sc.node(20, 20, 80, 60, "A")
        sc.node(400, 200, 80, 60, "B")
        sc.edge([(100, 50), (400, 230)], label="clear")
        self.assertNotIn("label-collision", codes(sc))

    def test_two_labels_over_each_other_fail(self):
        sc = _scene("lbl-lbl", 500, 300)
        sc.text(30, 100, "one", fs=12.0)
        sc.text(35, 100, "two", fs=12.0)
        hits = findings(sc, "label-collision")
        self.assertEqual(len(hits), 1)
        self.assertIn("overlap each other", hits[0].message)

    def test_two_labels_far_apart_pass(self):
        sc = _scene("lbl-far", 500, 300)
        sc.text(30, 100, "one", fs=12.0)
        sc.text(30, 200, "two", fs=12.0)
        self.assertNotIn("label-collision", codes(sc))

    def test_a_tags_own_text_is_not_a_label(self):
        sc = _scene("lbl-tag", 500, 300)
        sc.tag(200, 150, "just a tag")
        self.assertNotIn("label-collision", codes(sc))


# --------------------------------------------------------------------------
# out-of-canvas
# --------------------------------------------------------------------------
class OutOfCanvasTest(unittest.TestCase):
    def test_item_flush_with_the_canvas_edge_passes(self):
        sc = _scene("oob", 200, 100)
        sc.node(0, 0, 200, 100, "A")
        self.assertNotIn("out-of-canvas", codes(sc))

    def test_sub_pixel_bleed_is_within_tolerance(self):
        sc = _scene("oob-t", 200, 100)
        sc.node(-0.5, 0, 200, 100, "A")
        self.assertNotIn("out-of-canvas", codes(sc))

    def test_item_outside_the_canvas_fails(self):
        sc = _scene("oob-bad", 200, 100)
        it = sc.node(-5, 0, 200, 100, "A")
        hits = findings(sc, "out-of-canvas")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)
        self.assertEqual(hits[0].item, it.id)
        self.assertAlmostEqual(hits[0].detail["overflow_px"], 5.0, delta=0.01)

    def test_item_hanging_off_the_bottom_fails(self):
        sc = _scene("oob-b", 200, 100)
        sc.node(0, 80, 200, 100, "A")
        self.assertIn("out-of-canvas", codes(sc))

    def test_text_item_off_canvas_fails(self):
        sc = _scene("oob-txt", 200, 100)
        sc.text(-10, 50, "hangs off")
        self.assertIn("out-of-canvas", codes(sc))

    def test_edge_off_canvas_fails(self):
        sc = _scene("oob-edge", 200, 100)
        sc.edge([(10, 50), (300, 50)])
        self.assertIn("out-of-canvas", codes(sc))

    def test_bands_are_exempt(self):
        sc = _scene("oob-band", 200, 100)
        sc.band(-40, -40, 300, 200, label="bleeding band")
        self.assertNotIn("out-of-canvas", codes(sc))


# --------------------------------------------------------------------------
# degenerate-edge
# --------------------------------------------------------------------------
class DegenerateEdgeTest(unittest.TestCase):
    def test_zero_length_edge_fails(self):
        sc = _scene("deg", 300, 200)
        it = sc.edge([(50, 50), (50, 50)])
        hits = findings(sc, "degenerate-edge")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)
        self.assertEqual(hits[0].item, it.id)

    def test_edge_shorter_than_two_px_fails(self):
        sc = _scene("deg1", 300, 200)
        sc.edge([(50, 50), (51.9, 50)])
        self.assertIn("degenerate-edge", codes(sc))

    def test_two_px_edge_passes(self):
        sc = _scene("deg2", 300, 200)
        sc.edge([(50, 50), (52, 50)])
        self.assertNotIn("degenerate-edge", codes(sc))

    def test_single_point_edge_fails(self):
        sc = _scene("deg3", 300, 200)
        sc.edge([(50, 50)])
        hits = findings(sc, "degenerate-edge")
        self.assertEqual(len(hits), 1)
        self.assertIn("< 2 points", hits[0].message)

    def test_a_real_arc_is_not_a_degenerate_edge(self):
        sc = _scene("arc", 500, 400)
        sc.arc(200, 150, 80, 40, 0, 180)
        self.assertNotIn("degenerate-edge", codes(sc))

    def test_a_zero_radius_arc_is_degenerate(self):
        sc = _scene("arc0", 500, 400)
        sc.arc(200, 150, 0, 0, 0, 180)
        self.assertIn("degenerate-edge", codes(sc))

    def test_the_scene_records_the_edge_length(self):
        sc = _scene("len", 300, 200)
        it = sc.edge([(50, 50), (50, 130)])
        self.assertEqual(it.meta["length"], 80.0)

    def test_a_long_arc_produces_no_findings(self):
        sc = _scene("arc-clean", 500, 400)
        sc.arc(250, 200, 120, 60, 0, 180)
        self.assertEqual(V.check_scene(sc), [])


# --------------------------------------------------------------------------
# edge-crossing
# --------------------------------------------------------------------------
class EdgeCrossingTest(unittest.TestCase):
    def test_two_crossing_edges_warn(self):
        sc = _scene("x", 400, 300)
        a = sc.edge([(10, 100), (300, 100)])
        sc.edge([(150, 20), (150, 200)])
        hits = findings(sc, "edge-crossing")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.WARNING)
        self.assertEqual(hits[0].item, a.id)
        self.assertAlmostEqual(hits[0].detail["at"][0], 150.0, delta=0.01)
        self.assertAlmostEqual(hits[0].detail["at"][1], 100.0, delta=0.01)

    def test_edges_that_miss_each_other_do_not_warn(self):
        sc = _scene("x-ok", 400, 300)
        sc.edge([(10, 100), (140, 100)])
        sc.edge([(200, 20), (200, 200)])
        self.assertNotIn("edge-crossing", codes(sc))

    def test_parallel_edges_do_not_warn(self):
        sc = _scene("x-par", 400, 300)
        sc.edge([(10, 100), (300, 100)])
        sc.edge([(10, 140), (300, 140)])
        self.assertNotIn("edge-crossing", codes(sc))

    def test_edges_fanning_out_of_the_same_node_do_not_warn(self):
        sc = _scene("x-fan", 500, 300)
        n = sc.node(200, 120, 80, 60, "N")
        a = sc.node(20, 20, 80, 40, "A")
        b = sc.node(400, 20, 80, 40, "B")
        sc.edge([(n.bbox.cx, n.bbox.cy), (a.bbox.cx, a.bbox.cy)],
                from_id=n.id, to_id=a.id)
        sc.edge([(n.bbox.cx, n.bbox.cy), (b.bbox.cx, b.bbox.cy)],
                from_id=n.id, to_id=b.id)
        self.assertNotIn("edge-crossing", codes(sc))

    def test_edges_fanning_from_the_same_raw_point_do_not_warn(self):
        sc = _scene("x-fan2", 400, 300)
        sc.edge([(200, 150), (50, 20)])
        sc.edge([(200, 150), (350, 20)])
        self.assertNotIn("edge-crossing", codes(sc))

    def test_t_junction_does_not_warn(self):
        sc = _scene("x-t", 400, 300)
        sc.edge([(50, 120), (300, 120)])
        sc.edge([(150, 40), (150, 120)])
        self.assertNotIn("edge-crossing", codes(sc))

    def test_edges_sharing_an_endpoint_node_do_not_warn(self):
        sc = _scene("x-chain", 600, 300)
        n1 = sc.node(20, 120, 80, 60, "n1")
        n2 = sc.node(250, 120, 80, 60, "n2")
        n3 = sc.node(480, 120, 80, 60, "n3")
        sc.edge([(n1.bbox.cx, n1.bbox.cy), (n2.bbox.cx, n2.bbox.cy)],
                from_id=n1.id, to_id=n2.id)
        sc.edge([(n2.bbox.cx, n2.bbox.cy), (n3.bbox.cx, n3.bbox.cy)],
                from_id=n2.id, to_id=n3.id)
        self.assertNotIn("edge-crossing", codes(sc))

    def test_crossings_can_be_switched_off(self):
        sc = _scene("x-off", 400, 300)
        sc.edge([(10, 100), (300, 100)])
        sc.edge([(150, 20), (150, 200)])
        self.assertNotIn("edge-crossing", codes(sc, check_crossings=False))

    def test_crossing_is_only_a_warning(self):
        sc = _scene("x-sev", 400, 300)
        sc.edge([(10, 100), (300, 100)])
        sc.edge([(150, 20), (150, 200)])
        self.assertEqual(V.worst(V.check_scene(sc)), V.WARNING)
        self.assertFalse(V.should_fail(V.check_scene(sc)))
        self.assertTrue(V.should_fail(V.check_scene(sc), fail_on="warning"))


# --------------------------------------------------------------------------
# isolated-node
# --------------------------------------------------------------------------
class IsolatedNodeTest(unittest.TestCase):
    def test_node_without_connectors_warns(self):
        sc = _scene("iso", 300, 200)
        it = sc.node(20, 20, 100, 60, "lonely")
        hits = findings(sc, "isolated-node")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.WARNING)
        self.assertEqual(hits[0].item, it.id)

    def test_connected_nodes_do_not_warn(self):
        sc = _scene("iso-ok", 500, 200)
        a = sc.node(20, 70, 100, 60, "A")
        b = sc.node(350, 70, 100, 60, "B")
        sc.edge([(120, 100), (350, 100)], from_id=a.id, to_id=b.id)
        self.assertNotIn("isolated-node", codes(sc))

    def test_card_without_connectors_warns(self):
        sc = _scene("iso-card", 300, 300)
        sc.card(20, 20, 200, 100, "Card")
        self.assertIn("isolated-node", codes(sc))

    def test_isolated_check_can_be_switched_off(self):
        sc = _scene("iso-off", 300, 200)
        sc.node(20, 20, 100, 60, "lonely")
        self.assertNotIn("isolated-node", codes(sc, check_isolated=False))

    def test_scene_allow_isolated_suppresses_the_warning(self):
        sc = _scene("iso-allow", 300, 200)
        it = sc.node(20, 20, 100, 60, "lonely")
        sc.allow_isolated = {it.id}
        self.assertNotIn("isolated-node", codes(sc))

    def test_scene_allow_isolated_does_not_leak_to_other_nodes(self):
        sc = _scene("iso-allow2", 400, 200)
        a = sc.node(20, 20, 100, 60, "A")
        b = sc.node(200, 20, 100, 60, "B")
        sc.allow_isolated = {a.id}
        hits = findings(sc, "isolated-node")
        self.assertEqual([f.item for f in hits], [b.id])


# --------------------------------------------------------------------------
# band-overlap
# --------------------------------------------------------------------------
class BandOverlapTest(unittest.TestCase):
    def test_bands_one_px_apart_pass(self):
        sc = _scene("band-ok", 500, 300)
        sc.band(0, 0, 100, 100, label="a")
        sc.band(101, 0, 100, 100, label="b")
        self.assertNotIn("band-overlap", codes(sc))

    def test_bands_touching_pass(self):
        sc = _scene("band-touch", 500, 300)
        sc.band(0, 0, 100, 100, label="a")
        sc.band(100, 0, 100, 100, label="b")
        self.assertNotIn("band-overlap", codes(sc))

    def test_overlapping_bands_warn(self):
        sc = _scene("band-bad", 500, 300)
        sc.band(0, 0, 100, 100, label="a")
        sc.band(95, 0, 100, 100, label="b")
        hits = findings(sc, "band-overlap")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.WARNING)


# --------------------------------------------------------------------------
# scene level reporting
# --------------------------------------------------------------------------
class CleanSceneTest(unittest.TestCase):
    def _clean(self):
        sc = _scene("clean", 480, 200)
        a = sc.node(20, 70, 120, 60, "A")
        b = sc.node(340, 70, 120, 60, "B")
        sc.edge([(140, 100), (340, 100)], from_id=a.id, to_id=b.id, label="go")
        return sc

    def test_a_clean_scene_has_zero_findings(self):
        self.assertEqual(V.check_scene(self._clean()), [])

    def test_a_clean_scene_summarizes_as_ok(self):
        stats = V.summarize(V.check_scene(self._clean()))
        self.assertEqual(stats, {"status": "ok", "total": 0, "errors": 0,
                                 "warnings": 0, "by_code": {}})
        self.assertEqual(V.worst([]), "ok")
        self.assertFalse(V.should_fail([]))
        self.assertFalse(V.should_fail([], fail_on="warning"))
        self.assertIn("ok", V.format_text([]))

    def test_a_node_moved_off_canvas_breaks_it(self):
        sc = self._clean()
        sc.node(-40, 70, 120, 60, "C", id="intruder")
        self.assertIn("out-of-canvas", codes(sc))

    def test_findings_are_sorted_errors_first(self):
        sc = self._clean()
        sc.text(-10, 100, "off canvas")
        sc.node(200, 20, 40, 30, "isolated", id="extra")
        out = V.check_scene(sc)
        severities = [f.severity for f in out]
        self.assertEqual(severities, sorted(severities,
                                             key=lambda s: {"error": 0, "warning": 1}.get(s, 9)))

    def test_finding_as_dict(self):
        sc = _scene("d", 200, 100)
        it = sc.node(-10, 0, 100, 50, "A")
        f = findings(sc, "out-of-canvas")[0]
        d = f.as_dict()
        self.assertEqual(d["code"], "out-of-canvas")
        self.assertEqual(d["severity"], "error")
        self.assertEqual(d["figure"], "d")
        self.assertEqual(d["item"], it.id)
        self.assertIn("bbox", d["detail"])

    def test_summarize_counts_by_code(self):
        sc = _scene("sum", 200, 100)
        sc.node(-10, 0, 100, 50, "A")
        stats = V.summarize(V.check_scene(sc))
        self.assertEqual(stats["status"], "error")
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["warnings"], 1)
        self.assertEqual(stats["by_code"],
                         {"isolated-node": 1, "out-of-canvas": 1})

    def test_should_fail_modes(self):
        sc = _scene("sf", 200, 100)
        sc.node(-10, 0, 100, 50, "A")
        out = V.check_scene(sc)
        self.assertTrue(V.should_fail(out))
        self.assertTrue(V.should_fail(out, fail_on="warning"))
        self.assertFalse(V.should_fail(out, fail_on="none"))

    def test_format_text_mentions_the_codes(self):
        sc = _scene("fmt", 200, 100)
        sc.node(-10, 0, 100, 50, "A")
        text = V.format_text(V.check_scene(sc))
        self.assertIn("out-of-canvas", text)
        self.assertIn("1 error(s)", text)


# --------------------------------------------------------------------------
# document level
# --------------------------------------------------------------------------
CLEAN_DOC = """<!doctype html>
<html><body>
<h1 id="top">Title</h1>
<figure id="fig-a"><svg viewBox="0 0 10 10"><rect width="1" height="1"/></svg></figure>
<div><p>text</p></div>
</body></html>"""


class CheckDocumentTest(unittest.TestCase):
    def test_clean_document_has_zero_findings(self):
        self.assertEqual(V.check_document(CLEAN_DOC, figure_ids=["a"],
                                         toc_ids=["top"]), [])

    def test_clean_document_without_ids(self):
        self.assertEqual(V.check_document(CLEAN_DOC), [])

    def test_unresolved_figure_placeholder(self):
        html = CLEAN_DOC.replace("<h1", "<!--FIG:intent--><h1")
        hits = [f for f in V.check_document(html) if f.code == "unresolved-figure"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)

    def test_unresolved_template_token(self):
        html = CLEAN_DOC.replace("<p>text</p>", "<p>{{ title }}</p>")
        hits = [f for f in V.check_document(html) if f.code == "unresolved-token"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)

    def test_balanced_document_is_silent(self):
        self.assertNotIn("tag-imbalance", doc_codes(CLEAN_DOC))

    def test_unclosed_div(self):
        hits = [f for f in V.check_document(CLEAN_DOC.replace("</div>", ""))
                if f.code == "tag-imbalance"]
        self.assertEqual(len(hits), 1)
        self.assertIn("<div>", hits[0].message)

    def test_unclosed_paragraph(self):
        html = CLEAN_DOC.replace("<p>text</p>", "<p>text")
        self.assertIn("tag-imbalance", doc_codes(html))

    def test_unclosed_figure(self):
        html = CLEAN_DOC.replace("</figure>", "")
        self.assertIn("tag-imbalance", doc_codes(html))

    def test_dangling_anchor(self):
        html = CLEAN_DOC.replace("<p>text</p>", '<p><a href="#nope">x</a></p>')
        hits = [f for f in V.check_document(html) if f.code == "dangling-anchor"]
        self.assertEqual(len(hits), 1)
        self.assertIn("#nope", hits[0].message)

    def test_anchor_that_exists_is_fine(self):
        html = CLEAN_DOC.replace("<p>text</p>", '<p><a href="#top">x</a></p>')
        self.assertNotIn("dangling-anchor", doc_codes(html))

    def test_duplicate_id(self):
        html = CLEAN_DOC.replace('<h1 id="top">', '<h1 id="top"><span id="top"></span>')
        hits = [f for f in V.check_document(html) if f.code == "duplicate-id"]
        self.assertEqual(len(hits), 1)
        self.assertIn("top", hits[0].message)

    def test_distinct_ids_are_fine(self):
        html = CLEAN_DOC.replace('<h1 id="top">', '<h1 id="top"><span id="sub"></span>')
        self.assertNotIn("duplicate-id", doc_codes(html))

    def test_declared_figure_count_mismatch(self):
        hits = [f for f in V.check_document(CLEAN_DOC, figure_ids=["a", "b"])
                if f.code == "figure-count"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, V.ERROR)
        self.assertIn("1 figures", hits[0].message)

    def test_matching_figure_count_is_silent(self):
        self.assertNotIn("figure-count",
                         doc_codes(CLEAN_DOC, figure_ids=["a"]))

    def test_declared_figure_not_in_document(self):
        self.assertIn("figure-missing", doc_codes(CLEAN_DOC, figure_ids=["zzz"]))

    def test_declared_figure_present_by_id(self):
        self.assertNotIn("figure-missing", doc_codes(CLEAN_DOC, figure_ids=["a"]))

    def test_no_svg_warns(self):
        html = CLEAN_DOC.replace(
            '<svg viewBox="0 0 10 10"><rect width="1" height="1"/></svg>', "")
        self.assertIn("no-figures", doc_codes(html))

    def test_placeholder_regex_needs_the_fig_marker(self):
        html = CLEAN_DOC.replace("<p>text</p>", "<!-- just a comment --><p>text</p>")
        self.assertNotIn("unresolved-figure", doc_codes(html))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
