"""Unit tests for ``docforge.text``.

These metrics are the single source of truth for "how wide is this string";
every layout size and every validator verdict comes from them.  The tests
therefore attack the *invariants* (fits, never overflows, never loses text)
rather than a handful of golden strings.
"""

from __future__ import annotations

import unittest

from docforge import text as T


class UnitsTest(unittest.TestCase):
    def test_cjk_counts_one_em_per_character(self):
        self.assertAlmostEqual(T.units("\u4e2d\u6587"), 2.0)
        self.assertAlmostEqual(T.units("\u4e2d"), 1.0)

    def test_latin_counts_narrow_per_character(self):
        self.assertAlmostEqual(T.units("abc"), 3 * 0.55)
        self.assertAlmostEqual(T.units("A"), 0.55)

    def test_mixed_adds_both(self):
        self.assertAlmostEqual(T.units("a\u4e2db"), 0.55 + 1.0 + 0.55)
        self.assertAlmostEqual(
            T.units("ab\u4e2d\u6587c"), T.units("ab") + T.units("\u4e2d\u6587c")
        )

    def test_empty_string_is_zero(self):
        self.assertEqual(T.units(""), 0.0)

    def test_fullwidth_forms_count_as_wide(self):
        # U+FF21 FULLWIDTH LATIN CAPITAL LETTER A sits above CJK_MIN.
        self.assertAlmostEqual(T.units("\uff21"), 1.0)


class TwTest(unittest.TestCase):
    def test_linear_in_font_size(self):
        base = T.tw("hello \u4e16\u754c", 10.0)
        for factor in (2.0, 3.5, 10.0):
            self.assertAlmostEqual(T.tw("hello \u4e16\u754c", 10.0 * factor),
                                   base * factor)

    def test_scales_to_zero(self):
        self.assertEqual(T.tw("anything", 0.0), 0.0)
        self.assertEqual(T.tw("", 42.0), 0.0)

    def test_matches_units_times_size(self):
        self.assertAlmostEqual(T.tw("\u4e2d\u6587 abc", 13.0),
                               T.units("\u4e2d\u6587 abc") * 13.0)


class FitTest(unittest.TestCase):
    CASES = [
        ("hello world", 16.0, 200.0),
        ("hello world", 16.0, 20.0),
        ("\u4e2d\u6587\u6807\u9898\u6587\u5b57", 15.0, 40.0),
        ("supercalifragilistic", 12.0, 33.0),
        ("a", 9.0, 0.4),
        ("", 12.0, 10.0),
    ]

    def test_never_exceeds_cap(self):
        for s, fs, maxw in self.CASES:
            self.assertLessEqual(T.fit(s, fs, maxw), fs + 1e-12, (s, fs, maxw))

    def test_never_overflows_maxw(self):
        for s, fs, maxw in self.CASES:
            got = T.fit(s, fs, maxw)
            self.assertLessEqual(T.tw(s, got), maxw + 1e-9, (s, fs, maxw, got))

    def test_cap_is_used_when_the_text_already_fits(self):
        self.assertEqual(T.fit("hi", 15.0, 1000.0), 15.0)

    def test_empty_text_keeps_the_cap(self):
        self.assertEqual(T.fit("", 15.0, 0.0), 15.0)

    def test_result_is_maximal(self):
        # Bumping the result by 1% must break the constraint (or hit the cap).
        for s, fs, maxw in self.CASES:
            got = T.fit(s, fs, maxw)
            if got >= fs:
                continue
            self.assertGreater(T.tw(s, got * 1.01), maxw)


class TruncateTest(unittest.TestCase):
    def test_short_string_untouched(self):
        self.assertEqual(T.truncate("hi", 12.0, 500.0), "hi")

    def test_single_character_untouched(self):
        self.assertEqual(T.truncate("\u4e2d", 12.0, 12.0), "\u4e2d")

    def test_long_string_is_shortened_and_marked(self):
        out = T.truncate("hello world", 12.0, 30.0)
        self.assertTrue(out.endswith(T.ELLIPSIS), out)
        self.assertTrue("hello world".startswith(out[:-1]), out)
        self.assertLess(len(out), len("hello world"))

    def test_cjk_truncation(self):
        s = "\u4e2d\u6587\u6d4b\u8bd5\u6807\u9898\u5f88\u957f"
        out = T.truncate(s, 14.0, 40.0)
        self.assertTrue(out.endswith(T.ELLIPSIS))
        self.assertTrue(s.startswith(out[:-1]))
        self.assertLessEqual(T.tw(out, 14.0), 40.0)

    def test_never_exceeds_maxw(self):
        strings = [
            "hello world",
            "\u4e2d\u6587\u6d4b\u8bd5\u6807\u9898\u5f88\u957f\u5f88\u957f",
            "mixed \u4e2d\u6587 text",
            "oneverylongunbrokenword",
            "a",
            "",
        ]
        widths = [0.0, 0.5, 1.0, 3.0, 5.0, 6.59, 6.6, 6.61, 12.0, 24.0, 30.0, 79.0]
        for s in strings:
            for maxw in widths:
                out = T.truncate(s, 12.0, maxw)
                self.assertLessEqual(
                    T.tw(out, 12.0), maxw + 1e-9,
                    f"truncate({s!r}, 12, {maxw}) -> {out!r}"
                    f" width {T.tw(out, 12.0)}",
                )

    def test_never_exceeds_maxw_for_cjk_and_big_sizes(self):
        s = "\u4e2d\u6587\u6807\u9898"
        for fs in (8.0, 12.0, 15.0, 40.0):
            for maxw in (0.0, 2.0, 7.0, 13.0, 55.0):
                out = T.truncate(s, fs, maxw)
                self.assertLessEqual(T.tw(out, fs), maxw + 1e-9, (fs, maxw, out))

    def test_custom_ellipsis(self):
        out = T.truncate("abcdefghij", 12.0, 30.0, ellipsis="~")
        self.assertTrue(out.endswith("~"))
        self.assertLessEqual(T.tw(out, 12.0), 30.0 + 1e-9)


class WrapTest(unittest.TestCase):
    LATIN = ("the quick brown fox jumps over the lazy dog and then keeps on "
             "running far past the edge of its little box")
    CJK = ("\u4e2d\u6587\u6362\u884c\u6d4b\u8bd5\u6587\u672c\u5185\u5bb9\u5f88"
           "\u957f\u9700\u8981\u6298\u884c\u800c\u4e14\u8fd8\u4f1a\u7ee7\u7eed"
           "\u5f80\u4e0b\u6392")
    MIXED = "\u4f7f\u7528 docforge \u751f\u6210 HTML \u6587\u6863 ok \u5b8c\u4e86"

    @staticmethod
    def _squash(s):
        return "".join(s.split())

    def _assert_lines_fit(self, lines, fs, maxw):
        for line in lines:
            # A single unbreakable glyph may exceed an absurdly small width;
            # nothing longer than one glyph may.
            if T.units(line) <= 1.0:
                continue
            self.assertLessEqual(T.tw(line, fs), maxw + 1e-9, line)

    def test_long_latin_paragraph(self):
        for maxw in (60.0, 80.0, 120.0, 200.0):
            lines = T.wrap(self.LATIN, 12.0, maxw)
            self.assertGreater(len(lines), 1)
            self._assert_lines_fit(lines, 12.0, maxw)
            self.assertEqual(self._squash("".join(lines)), self._squash(self.LATIN))
            for line in lines:
                self.assertEqual(line, line.strip(), line)

    def test_long_cjk_paragraph(self):
        for maxw in (36.0, 60.0, 96.0):
            lines = T.wrap(self.CJK, 12.0, maxw)
            self.assertGreater(len(lines), 1)
            self._assert_lines_fit(lines, 12.0, maxw)
            self.assertEqual(self._squash("".join(lines)), self._squash(self.CJK))

    def test_mixed_paragraph(self):
        for maxw in (40.0, 70.0, 110.0):
            lines = T.wrap(self.MIXED, 12.0, maxw)
            self._assert_lines_fit(lines, 12.0, maxw)
            self.assertEqual(self._squash("".join(lines)), self._squash(self.MIXED))

    def test_embedded_newline_forces_a_break(self):
        self.assertEqual(T.wrap("first\nsecond", 12.0, 1000.0),
                         ["first", "second"])

    def test_blank_line_is_preserved(self):
        self.assertEqual(T.wrap("a\n\nb", 12.0, 1000.0), ["a", "", "b"])

    def test_short_text_is_one_line(self):
        self.assertEqual(T.wrap("hi", 12.0, 1000.0), ["hi"])

    def test_single_word_longer_than_the_line(self):
        word = "antidisestablishmentarianism"
        for maxw in (30.0, 40.0, 55.0):
            lines = T.wrap(word, 12.0, maxw)
            self.assertGreater(len(lines), 1)
            self._assert_lines_fit(lines, 12.0, maxw)
            self.assertEqual("".join(lines), word)

    def test_never_loses_characters(self):
        samples = [
            self.LATIN,
            self.CJK,
            self.MIXED,
            "well-known hyphen-ated words/paths here",
            "a  b   c",
        ]
        for text in samples:
            for maxw in (20.0, 45.0, 90.0):
                lines = T.wrap(text, 12.0, maxw)
                self.assertEqual(self._squash("".join(lines)), self._squash(text))

    def test_latin_break_prefers_a_space(self):
        lines = T.wrap("alpha beta gamma delta", 12.0, 80.0)
        self.assertNotIn("alphabeta", "".join(lines))

    def test_result_is_a_list_of_strings(self):
        lines = T.wrap("hello", 12.0, 100.0)
        self.assertIsInstance(lines, list)
        self.assertTrue(all(isinstance(x, str) for x in lines))


class LinesNeededTest(unittest.TestCase):
    def test_matches_wrap_length(self):
        for text in (WrapTest.LATIN, WrapTest.CJK, WrapTest.MIXED, "a\n\nb", "hi"):
            for maxw in (30.0, 60.0, 120.0):
                self.assertEqual(T.lines_needed(text, 12.0, maxw),
                                 len(T.wrap(text, 12.0, maxw)))

    def test_empty_text_needs_one_line(self):
        self.assertEqual(T.lines_needed("", 12.0, 80.0), 1)

    def test_long_word_needs_several_lines(self):
        self.assertGreaterEqual(
            T.lines_needed("supercalifragilisticexpialidocious", 12.0, 40.0), 2)

    def test_blank_lines_count(self):
        self.assertEqual(T.lines_needed("a\n\nb", 12.0, 1000.0), 3)

    def test_more_width_needs_fewer_lines(self):
        narrow = T.lines_needed(WrapTest.LATIN, 12.0, 60.0)
        wide = T.lines_needed(WrapTest.LATIN, 12.0, 1000.0)
        self.assertLessEqual(wide, narrow)
        self.assertEqual(wide, 1)


class BlockHeightTest(unittest.TestCase):
    def test_single_row(self):
        self.assertEqual(T.block_height([12.0]), 12.0)

    def test_rows_plus_leading(self):
        self.assertAlmostEqual(T.block_height([15.0, 11.5, 11.5]),
                               15.0 + 11.5 + 11.5 + 2 * 5.0)

    def test_empty_is_zero(self):
        self.assertEqual(T.block_height([]), 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
