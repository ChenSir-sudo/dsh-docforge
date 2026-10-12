"""Unit tests for ``docforge.geom``.

The validator is only as trustworthy as this module, so the edge cases are the
point: touching boxes, collinear segments, T-junctions, degenerate segments and
segments that come close to a rectangle without touching it.
"""

from __future__ import annotations

import math
import unittest

from docforge.geom import (
    Rect,
    arc_points,
    point_on_polyline,
    polyline_length,
    rect_from_points,
    rounded_path,
    seg_rect_enter,
    seg_rect_hit,
    seg_seg_hit,
)


class RectBasicsTest(unittest.TestCase):
    def test_derived_properties(self):
        r = Rect(10.0, 20.0, 40.0, 60.0)
        self.assertEqual(r.right, 50.0)
        self.assertEqual(r.bottom, 80.0)
        self.assertEqual(r.cx, 30.0)
        self.assertEqual(r.cy, 50.0)
        self.assertEqual(r.area, 2400.0)
        self.assertFalse(r.is_empty)

    def test_empty_rectangles(self):
        self.assertTrue(Rect(0, 0, 0, 10).is_empty)
        self.assertTrue(Rect(0, 0, 10, 0).is_empty)
        self.assertTrue(Rect(0, 0, -3, 5).is_empty)
        self.assertEqual(Rect(0, 0, -3, 5).area, 0.0)

    def test_inflate_shrink_offset(self):
        r = Rect(10, 20, 40, 60)
        self.assertEqual(r.inflate(5), Rect(5, 15, 50, 70))
        self.assertEqual(r.shrink_to(5), Rect(15, 25, 30, 50))
        self.assertEqual(r.offset(3, -4), Rect(13, 16, 40, 60))
        self.assertEqual(r.offset(0, 0), r)

    def test_as_dict_rounds(self):
        self.assertEqual(Rect(1.234, 5.678, 9.876, 4.321).as_dict(),
                         {"x": 1.23, "y": 5.68, "w": 9.88, "h": 4.32})


class RectIntersectsTest(unittest.TestCase):
    R = Rect(0, 0, 10, 10)

    def test_overlapping_rectangles_intersect(self):
        self.assertTrue(self.R.intersects(Rect(5, 5, 10, 10)))
        self.assertTrue(self.R.intersects(Rect(-5, -5, 10, 10)))

    def test_one_inside_the_other(self):
        self.assertTrue(self.R.intersects(Rect(2, 2, 3, 3)))
        self.assertTrue(Rect(2, 2, 3, 3).intersects(self.R))

    def test_touching_edges_do_not_intersect(self):
        self.assertFalse(self.R.intersects(Rect(10, 0, 10, 10)))   # right
        self.assertFalse(self.R.intersects(Rect(-10, 0, 10, 10)))  # left
        self.assertFalse(self.R.intersects(Rect(0, 10, 10, 10)))   # below
        self.assertFalse(self.R.intersects(Rect(0, -10, 10, 10)))  # above
        self.assertFalse(self.R.intersects(Rect(10, 10, 10, 10)))  # corner

    def test_one_pixel_overlap_intersects(self):
        self.assertTrue(self.R.intersects(Rect(9, 0, 10, 10)))
        self.assertTrue(self.R.intersects(Rect(0, 9, 10, 10)))
        self.assertTrue(self.R.intersects(Rect(-9, 0, 10, 10)))
        self.assertTrue(self.R.intersects(Rect(0, -9, 10, 10)))

    def test_one_pixel_gap_does_not_intersect(self):
        self.assertFalse(self.R.intersects(Rect(11, 0, 10, 10)))
        self.assertFalse(self.R.intersects(Rect(0, 11, 10, 10)))

    def test_pad_grows_the_other_rectangle(self):
        far = Rect(13, 0, 10, 10)
        self.assertFalse(self.R.intersects(far))
        self.assertFalse(self.R.intersects(far, pad=3.0))  # lands flush
        self.assertTrue(self.R.intersects(far, pad=4.0))
        self.assertFalse(self.R.intersects(far, pad=2.0))


class RectOverlapAreaTest(unittest.TestCase):
    def test_partial_overlap(self):
        self.assertEqual(Rect(0, 0, 10, 10).overlap_area(Rect(5, 5, 10, 10)), 25.0)

    def test_containment(self):
        self.assertEqual(Rect(0, 0, 10, 10).overlap_area(Rect(2, 2, 3, 3)), 9.0)

    def test_touching_is_zero(self):
        self.assertEqual(Rect(0, 0, 10, 10).overlap_area(Rect(10, 0, 10, 10)), 0.0)

    def test_disjoint_is_zero(self):
        self.assertEqual(Rect(0, 0, 10, 10).overlap_area(Rect(50, 50, 10, 10)), 0.0)

    def test_symmetric(self):
        a, b = Rect(0, 0, 10, 10), Rect(3, 4, 10, 10)
        self.assertEqual(a.overlap_area(b), b.overlap_area(a))


class RectContainmentTest(unittest.TestCase):
    R = Rect(0, 0, 10, 10)

    def test_contains_point(self):
        self.assertTrue(self.R.contains_point(0, 0))
        self.assertTrue(self.R.contains_point(10, 10))
        self.assertTrue(self.R.contains_point(5, 5))
        self.assertFalse(self.R.contains_point(10.5, 5))
        self.assertFalse(self.R.contains_point(5, -0.5))

    def test_contains_point_with_pad(self):
        self.assertTrue(self.R.contains_point(12, 5, pad=2.0))
        self.assertFalse(self.R.contains_point(13, 5, pad=2.0))

    def test_contains_rect(self):
        self.assertTrue(self.R.contains_rect(Rect(2, 2, 3, 3)))
        self.assertTrue(self.R.contains_rect(Rect(0, 0, 10, 10)))
        self.assertFalse(self.R.contains_rect(Rect(5, 5, 6, 6)))
        self.assertFalse(self.R.contains_rect(Rect(-1, 0, 10, 10)))

    def test_contains_rect_with_pad(self):
        # inflate(1) turns (0,0,10,10) into (-1,-1,12,12): right/bottom = 11.
        self.assertTrue(self.R.contains_rect(Rect(0, 0, 11, 11), pad=1.0))
        self.assertFalse(self.R.contains_rect(Rect(0, 0, 12, 12), pad=1.0))


class RectUnionIntersectionTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(Rect(0, 0, 10, 10).union(Rect(20, 5, 10, 10)),
                         Rect(0, 0, 30, 15))

    def test_union_with_containment(self):
        self.assertEqual(Rect(0, 0, 10, 10).union(Rect(2, 2, 3, 3)),
                         Rect(0, 0, 10, 10))

    def test_union_is_commutative(self):
        a, b = Rect(0, 0, 10, 10), Rect(20, 5, 10, 10)
        self.assertEqual(a.union(b), b.union(a))

    def test_intersection(self):
        self.assertEqual(Rect(0, 0, 10, 10).intersection(Rect(5, 5, 10, 10)),
                         Rect(5, 5, 5, 5))

    def test_intersection_of_disjoint_is_empty(self):
        got = Rect(0, 0, 10, 10).intersection(Rect(50, 50, 10, 10))
        self.assertTrue(got.is_empty)
        self.assertEqual(got.area, 0.0)

    def test_intersection_of_touching_is_empty(self):
        got = Rect(0, 0, 10, 10).intersection(Rect(10, 0, 10, 10))
        self.assertTrue(got.is_empty)


class RectFromPointsTest(unittest.TestCase):
    def test_bounds_of_points(self):
        self.assertEqual(rect_from_points([(5, 5), (-1, 8), (3, -2)]),
                         Rect(-1, -2, 6, 10))

    def test_single_point_is_empty(self):
        self.assertTrue(rect_from_points([(4, 4)]).is_empty)


class SegSegHitTest(unittest.TestCase):
    def test_proper_crossing(self):
        self.assertEqual(seg_seg_hit((0, 0), (10, 10), (0, 10), (10, 0)), (5.0, 5.0))

    def test_proper_crossing_orthogonal(self):
        self.assertEqual(seg_seg_hit((0, 5), (10, 5), (5, 0), (5, 10)), (5.0, 5.0))

    def test_parallel_disjoint(self):
        self.assertIsNone(seg_seg_hit((0, 0), (10, 0), (0, 5), (10, 5)))

    def test_parallel_collinear_disjoint(self):
        self.assertIsNone(seg_seg_hit((0, 0), (10, 0), (20, 0), (30, 0)))
        self.assertIsNone(seg_seg_hit((20, 0), (30, 0), (0, 0), (10, 0)))

    def test_collinear_overlap_reports_a_shared_point(self):
        got = seg_seg_hit((0, 0), (10, 0), (5, 0), (20, 0))
        self.assertIsNotNone(got)
        self.assertEqual(got[1], 0.0)
        self.assertGreaterEqual(got[0], 5.0)
        self.assertLessEqual(got[0], 10.0)

    def test_collinear_containment_reports_an_inner_endpoint(self):
        got = seg_seg_hit((2, 0), (8, 0), (0, 0), (10, 0))
        self.assertIsNotNone(got)
        self.assertGreaterEqual(got[0], 2.0)
        self.assertLessEqual(got[0], 8.0)

    def test_collinear_touching_endpoints(self):
        self.assertEqual(seg_seg_hit((0, 0), (10, 0), (10, 0), (20, 0)), (10.0, 0.0))

    def test_t_junction(self):
        self.assertEqual(seg_seg_hit((0, 0), (10, 0), (5, 0), (5, 10)), (5.0, 0.0))
        self.assertEqual(seg_seg_hit((5, 0), (5, 10), (0, 0), (10, 0)), (5.0, 0.0))

    def test_shared_endpoint(self):
        self.assertEqual(seg_seg_hit((0, 0), (10, 0), (10, 0), (10, 10)),
                         (10.0, 0.0))

    def test_shared_endpoint_of_collinear_stubs(self):
        got = seg_seg_hit((0, 0), (10, 0), (10, 0), (10, 10))
        self.assertEqual(got, (10.0, 0.0))

    def test_disjoint_but_on_the_extension_of_a_line(self):
        # b0 sits on the *line* through a, but far outside the segment a.
        self.assertIsNone(seg_seg_hit((0, 0), (10, 0), (20, 0), (20, 10)))
        self.assertIsNone(seg_seg_hit((0, 0), (10, 0), (-20, 0), (-20, 10)))
        self.assertIsNone(seg_seg_hit((20, 0), (20, 10), (0, 0), (10, 0)))

    def test_disjoint_far_apart(self):
        self.assertIsNone(seg_seg_hit((0, 0), (10, 0), (20, 30), (30, 40)))
        self.assertIsNone(seg_seg_hit((0, 0), (10, 10), (20, 0), (30, 10)))

    def test_zero_length_segment_on_the_other_segment(self):
        self.assertEqual(seg_seg_hit((5, 5), (5, 5), (0, 0), (10, 10)), (5.0, 5.0))
        self.assertEqual(seg_seg_hit((5, 0), (5, 0), (0, 0), (10, 0)), (5.0, 0.0))

    def test_zero_length_segment_off_the_other_segment(self):
        self.assertIsNone(seg_seg_hit((5, 5), (5, 5), (0, 0), (10, 0)))
        self.assertIsNone(seg_seg_hit((5, 5), (5, 5), (20, 20), (30, 30)))

    def test_two_zero_length_segments(self):
        self.assertEqual(seg_seg_hit((5, 5), (5, 5), (5, 5), (5, 5)), (5.0, 5.0))
        self.assertIsNone(seg_seg_hit((5, 5), (5, 5), (6, 6), (6, 6)))


class SegRectHitTest(unittest.TestCase):
    R = Rect(0, 0, 10, 10)

    def test_crossing_the_rect(self):
        self.assertTrue(seg_rect_hit((-5, 5), (15, 5), self.R))
        self.assertTrue(seg_rect_hit((5, -5), (5, 15), self.R))

    def test_fully_inside(self):
        self.assertTrue(seg_rect_hit((2, 2), (8, 8), self.R))

    def test_endpoint_inside(self):
        self.assertTrue(seg_rect_hit((5, 5), (50, 50), self.R))

    def test_entirely_outside(self):
        self.assertFalse(seg_rect_hit((20, 0), (20, 10), self.R))
        self.assertFalse(seg_rect_hit((-5, -5), (-1, -1), self.R))
        self.assertFalse(seg_rect_hit((50, 50), (60, 60), self.R))

    def test_outside_but_aligned_with_a_corner_line(self):
        # The segment shares y == rect.top and x == rect.left lines with the
        # rectangle, yet never comes near it.
        self.assertFalse(seg_rect_hit((20, 0), (20, 50), self.R))
        self.assertFalse(seg_rect_hit((-20, 10), (-20, 50), self.R))
        self.assertFalse(seg_rect_hit((-20, 0), (-5, 0), self.R))

    def test_stopping_one_pixel_short(self):
        self.assertFalse(seg_rect_hit((20, 5), (11, 5), self.R))
        self.assertFalse(seg_rect_hit((-20, 5), (-1, 5), self.R))

    def test_running_exactly_along_an_edge(self):
        self.assertTrue(seg_rect_hit((0, 0), (10, 0), self.R))
        self.assertTrue(seg_rect_hit((-5, 0), (15, 0), self.R))
        self.assertTrue(seg_rect_hit((0, -5), (0, 15), self.R))

    def test_stopping_exactly_on_the_boundary(self):
        self.assertTrue(seg_rect_hit((20, 5), (10, 5), self.R))

    def test_grazing_a_corner_still_hits(self):
        self.assertTrue(seg_rect_hit((-5, -5), (5, 5), self.R))
        self.assertTrue(seg_rect_hit((-5, 5), (5, -5), self.R))

    def test_missing_a_corner_does_not_hit(self):
        self.assertFalse(seg_rect_hit((-5, -1), (-1, -5), self.R))

    def test_empty_rect_never_hits(self):
        self.assertFalse(seg_rect_hit((0, 0), (10, 10), Rect(5, 5, 0, 0)))

    def test_pad_widens_the_target(self):
        self.assertFalse(seg_rect_hit((14, 5), (20, 5), self.R))
        self.assertTrue(seg_rect_hit((14, 5), (20, 5), self.R, pad=5.0))


class SegRectEnterTest(unittest.TestCase):
    def test_entry_point(self):
        self.assertEqual(seg_rect_enter((-5, 5), (15, 5), Rect(0, 0, 10, 10)),
                         (0.0, 5.0))

    def test_start_inside(self):
        self.assertEqual(seg_rect_enter((4, 4), (15, 15), Rect(0, 0, 10, 10)),
                         (4.0, 4.0))

    def test_no_entry(self):
        self.assertIsNone(seg_rect_enter((20, 20), (30, 30), Rect(0, 0, 10, 10)))


class RoundedPathTest(unittest.TestCase):
    def test_fewer_than_two_points_is_empty(self):
        self.assertEqual(rounded_path([]), "")
        self.assertEqual(rounded_path([(1, 2)]), "")

    def test_two_points_is_a_straight_line(self):
        self.assertEqual(rounded_path([(0, 0), (10, 10)]), "M 0 0 L 10 10")
        self.assertNotIn("Q", rounded_path([(0, 0), (10, 10)]))

    def test_three_point_elbow(self):
        self.assertEqual(rounded_path([(0, 0), (100, 0), (100, 100)], 11.0),
                         "M 0 0 L 89.0 0.0 Q 100 0 100.0 11.0 L 100 100")

    def test_elbow_clamps_radius_to_half_the_short_segment(self):
        # The first leg is only 10 long, so the radius must clamp to 5.
        self.assertEqual(rounded_path([(0, 0), (10, 0), (10, 100)], 11.0),
                         "M 0 0 L 5.0 0.0 Q 10 0 10.0 5.0 L 10 100")

    def test_elbow_clamps_to_half_the_shorter_leg_either_way(self):
        self.assertEqual(rounded_path([(0, 0), (100, 0), (100, 10)], 11.0),
                         "M 0 0 L 95.0 0.0 Q 100 0 100.0 5.0 L 100 10")

    def test_zero_radius_is_sharp(self):
        self.assertEqual(rounded_path([(0, 0), (100, 0), (100, 100)], 0.0),
                         "M 0 0 L 100.0 0.0 Q 100 0 100.0 0.0 L 100 100")

    def test_four_point_s_shape(self):
        d = rounded_path([(0, 0), (100, 0), (100, 100), (0, 100)], 11.0)
        self.assertTrue(d.startswith("M 0 0 "))
        self.assertTrue(d.endswith("L 0 100"))
        self.assertEqual(d.count("Q"), 2)
        self.assertEqual(d.count("M"), 1)

    def test_five_point_path_has_three_corners(self):
        d = rounded_path([(0, 0), (100, 0), (100, 50), (200, 50), (200, 100)], 8.0)
        self.assertEqual(d.count("Q"), 3)

    def test_duplicate_consecutive_points_do_not_crash(self):
        d = rounded_path([(0, 0), (100, 0), (100, 0), (100, 100)], 11.0)
        self.assertTrue(d.startswith("M 0 0 "))


class ArcPointsTest(unittest.TestCase):
    def test_count(self):
        self.assertEqual(len(arc_points(0, 0, 10, 5, 0, 90, 8)), 9)

    def test_minimum_steps(self):
        self.assertEqual(len(arc_points(0, 0, 10, 5, 0, 90, 1)), 3)
        self.assertEqual(len(arc_points(0, 0, 10, 5, 0, 90, 0)), 3)

    def test_endpoints(self):
        pts = arc_points(100, 50, 40, 20, 0, 90, 4)
        self.assertAlmostEqual(pts[0][0], 140.0)
        self.assertAlmostEqual(pts[0][1], 50.0)
        self.assertAlmostEqual(pts[-1][0], 100.0)
        self.assertAlmostEqual(pts[-1][1], 70.0)

    def test_sampled_points_lie_on_the_ellipse(self):
        cx, cy, rx, ry = 30.0, -12.0, 25.0, 9.0
        for p in arc_points(cx, cy, rx, ry, 15.0, 250.0, 24):
            norm = ((p[0] - cx) / rx) ** 2 + ((p[1] - cy) / ry) ** 2
            self.assertAlmostEqual(norm, 1.0, places=9)

    def test_full_circle_returns_to_the_start(self):
        pts = arc_points(0, 0, 10, 10, 0, 360, 16)
        self.assertAlmostEqual(pts[0][0], pts[-1][0], places=9)
        self.assertAlmostEqual(pts[0][1], pts[-1][1], places=9)


class PolylineTest(unittest.TestCase):
    def test_length(self):
        self.assertEqual(polyline_length([(0, 0), (3, 4)]), 5.0)
        self.assertEqual(polyline_length([(0, 0), (10, 0), (10, 10)]), 20.0)

    def test_point_at_zero(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        self.assertEqual(point_on_polyline(pts, 0.0), (0.0, 0.0))

    def test_point_at_half(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        x, y = point_on_polyline(pts, 0.5)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 0.0)

    def test_point_at_one(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        x, y = point_on_polyline(pts, 1.0)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 10.0)

    def test_point_at_quarter_and_three_quarters(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        x, y = point_on_polyline(pts, 0.25)
        self.assertAlmostEqual(x, 5.0)
        self.assertAlmostEqual(y, 0.0)
        x, y = point_on_polyline(pts, 0.75)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 5.0)

    def test_zero_length_polyline(self):
        self.assertEqual(point_on_polyline([(3, 3), (3, 3)], 0.5), (3.0, 3.0))

    def test_t_is_clamped(self):
        pts = [(0, 0), (10, 0)]
        self.assertEqual(point_on_polyline(pts, -1.0), (0.0, 0.0))
        self.assertEqual(point_on_polyline(pts, 2.0), (10.0, 0.0))

    def test_single_segment_midpoint(self):
        x, y = point_on_polyline([(0, 0), (10, 10)], 0.5)
        self.assertAlmostEqual(x, 5.0)
        self.assertAlmostEqual(y, 5.0)

    def test_diagonal_length(self):
        self.assertAlmostEqual(polyline_length([(0, 0), (3, 4), (3, 4)]),
                               5.0 + math.hypot(0, 0))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
