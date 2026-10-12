"""Tests for the restricted-Markdown parser.

Each test pins one construct of the dialect. The parser is the first stage of a
build, so a wrong block here is a wrong document three layers later -- these
tests assert the *model*, not the strings a particular renderer happens to
produce.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docforge import markdown as md


def material(*lines: str) -> str:
    """Build a material from lines, so fenced blocks stay readable in a test."""
    return "\n".join(lines) + "\n"


class FrontMatterTests(unittest.TestCase):
    def test_scalars_lists_quotes_and_booleans(self):
        doc = md.parse(
            material(
                "---",
                "title: 通用 Agent",
                "empty:",
                "draft: false",
                "quoted: \"a: b\"",
                "tags:",
                "  - 内核",
                "  - 外壳",
                "---",
                "# 标题",
            )
        )

        self.assertEqual(doc.meta["title"], "通用 Agent")
        self.assertEqual(doc.meta["empty"], "")
        self.assertIs(doc.meta["draft"], False)
        self.assertEqual(doc.meta["quoted"], "a: b")
        self.assertEqual(doc.meta["tags"], ["内核", "外壳"])
        self.assertEqual(len(doc.blocks), 1)

    def test_true_is_coerced_to_a_bool(self):
        doc = md.parse(material("---", "dark: yes", "---", "正文"))
        self.assertIs(doc.meta["dark"], True)

    def test_material_without_front_matter_has_no_meta(self):
        doc = md.parse(material("# 标题"))
        self.assertEqual(doc.meta, {})

    def test_unclosed_front_matter_is_not_front_matter(self):
        doc = md.parse(material("---", "title: x", "", "# 标题"))

        self.assertEqual(doc.meta, {})
        self.assertEqual([b.kind for b in doc.blocks], ["rule", "paragraph", "heading"])

    def test_malformed_line_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(material("---", "title without a colon", "---"))

    def test_indented_line_that_is_not_an_item_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(material("---", "title: x", "  stray", "---"))


class HeadingTests(unittest.TestCase):
    def test_five_levels_and_their_ids(self):
        doc = md.parse(
            material("# 一", "## 二", "### 三", "#### 四", "##### 五")
        )

        self.assertEqual([b.level for b in doc.blocks], [1, 2, 3, 4, 5])
        self.assertEqual([b.title for b in doc.blocks], ["一", "二", "三", "四", "五"])
        self.assertEqual([b.id for b in doc.blocks], ["一", "二", "三", "四", "五"])

    def test_six_hashes_is_a_paragraph(self):
        doc = md.parse(material("###### 六级不支持"))
        self.assertEqual([b.kind for b in doc.blocks], ["paragraph"])

    def test_hashtag_without_a_space_is_a_paragraph(self):
        doc = md.parse(material("#标题"))
        self.assertEqual([b.kind for b in doc.blocks], ["paragraph"])

    def test_closing_hashes_are_dropped_but_a_trailing_sharp_is_not(self):
        self.assertEqual(md.parse("# 标题 #").blocks[0].title, "标题")
        self.assertEqual(md.parse("# C#").blocks[0].title, "C#")

    def test_heading_title_keeps_inline_markup_for_the_renderer(self):
        doc = md.parse("# **重点** 标题")
        self.assertEqual(doc.blocks[0].title, "**重点** 标题")
        self.assertEqual(doc.toc[0].title, "重点 标题")


class ParagraphAndCodeTests(unittest.TestCase):
    def test_paragraph_joins_its_lines_and_stops_at_a_blank_line(self):
        doc = md.parse(material("第一行", "第二行", "", "第三段"))

        self.assertEqual([b.kind for b in doc.blocks], ["paragraph", "paragraph"])
        self.assertEqual(doc.blocks[0].text, "第一行\n第二行")
        self.assertEqual(doc.blocks[1].text, "第三段")

    def test_a_heading_interrupts_a_paragraph(self):
        doc = md.parse(material("文字", "# 标题"))
        self.assertEqual([b.kind for b in doc.blocks], ["paragraph", "heading"])

    def test_fenced_code_keeps_its_language_and_bytes(self):
        doc = md.parse(
            material(
                "```python",
                "x = 1 < 2",
                "",
                "y = 3 & 4",
                "```",
            )
        )

        block = doc.blocks[0]
        self.assertEqual(block.kind, "code")
        self.assertEqual(block.lang, "python")
        self.assertEqual(block.code, "x = 1 < 2\n\ny = 3 & 4")

    def test_fence_without_a_language(self):
        block = md.parse(material("```", "plain", "```")).blocks[0]
        self.assertEqual(block.lang, "")
        self.assertEqual(block.code, "plain")

    def test_unclosed_fence_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(material("```python", "x = 1"))


class TableTests(unittest.TestCase):
    def test_head_and_rows(self):
        doc = md.parse(
            material(
                "| 约束 | 要求 |",
                "| --- | :---: |",
                "| 超时 | 10–30 秒 |",
                "| `{status}` | 统一返回 |",
            )
        )

        table = doc.blocks[0]
        self.assertEqual(table.kind, "table")
        self.assertEqual(table.head, ["约束", "要求"])
        self.assertEqual(table.rows, [["超时", "10–30 秒"], ["`{status}`", "统一返回"]])

    def test_rows_are_padded_to_the_header_width(self):
        table = md.parse(
            material("| a | b | c |", "| --- | --- | --- |", "| 1 |", "| 1 | 2 | 3 | 4 |")
        ).blocks[0]

        self.assertEqual(table.rows, [["1", "", ""], ["1", "2", "3"]])

    def test_a_rule_after_a_pipe_line_is_not_a_table(self):
        doc = md.parse(material("包含 | 竖线的段落", "---"))
        self.assertEqual([b.kind for b in doc.blocks], ["paragraph", "rule"])


class ListTests(unittest.TestCase):
    def test_unordered_two_levels(self):
        doc = md.parse(
            material(
                "- 一级",
                "  - 二级",
                "  - 二级二",
                "- 一级二",
            )
        )

        block = doc.blocks[0]
        self.assertEqual(block.kind, "list")
        self.assertFalse(block.ordered)
        self.assertEqual([item.text for item in block.items], ["一级", "一级二"])
        self.assertEqual([i.text for i in block.items[0].sub.items], ["二级", "二级二"])
        self.assertIsNone(block.items[1].sub)

    def test_nested_ordered_list_keeps_its_own_kind(self):
        block = md.parse(
            material(
                "1. 先做",
                "   1. 子步骤",
                "   2. 子步骤二",
                "2. 后做",
            )
        ).blocks[0]

        self.assertTrue(block.ordered)
        self.assertTrue(block.items[0].sub.ordered)
        self.assertEqual(len(block.items[0].sub.items), 2)

    def test_wrapped_line_continues_the_current_item(self):
        block = md.parse(material("- 第一行", "  续行", "- 第二项")).blocks[0]
        self.assertEqual(block.items[0].text, "第一行\n续行")

    def test_blank_line_inside_a_list_keeps_one_list(self):
        block = md.parse(material("- 一", "", "- 二")).blocks[0]
        self.assertEqual([i.text for i in block.items], ["一", "二"])

    def test_a_paragraph_after_a_list_is_not_part_of_it(self):
        doc = md.parse(material("- 一", "", "段落"))
        self.assertEqual([b.kind for b in doc.blocks], ["list", "paragraph"])

    def test_markers_accept_star_plus_and_paren_numbers(self):
        doc = md.parse(material("* a", "+ b", "1) c"))

        self.assertEqual([b.kind for b in doc.blocks], ["list", "list"])
        self.assertEqual([i.text for i in doc.blocks[0].items], ["a", "b"])
        self.assertFalse(doc.blocks[0].ordered)
        self.assertEqual([i.text for i in doc.blocks[1].items], ["c"])
        self.assertTrue(doc.blocks[1].ordered)


class QuoteTests(unittest.TestCase):
    def test_plain_quote_body_blocks(self):
        doc = md.parse(material("> 引用第一行", "> 引用第二行"))
        quote = doc.blocks[0]

        self.assertEqual(quote.kind, "quote")
        self.assertEqual(quote.alert, "")
        self.assertEqual(quote.blocks[0].text, "引用第一行\n引用第二行")

    def test_each_alert_tag_is_recognised(self):
        for tag in ("NOTE", "KEY", "GOAL", "ACCEPT"):
            with self.subTest(tag=tag):
                quote = md.parse(material(f"> [!{tag}]", "> 正文")).blocks[0]
                self.assertEqual(quote.alert, tag)
                self.assertEqual(quote.blocks[0].text, "正文")

    def test_alert_tag_is_case_insensitive(self):
        quote = md.parse(material("> [!note]", "> 正文")).blocks[0]
        self.assertEqual(quote.alert, "NOTE")

    def test_unknown_alert_tag_stays_body_text(self):
        quote = md.parse(material("> [!WARNING]", "> 正文")).blocks[0]
        self.assertEqual(quote.alert, "")
        self.assertEqual(quote.blocks[0].text, "[!WARNING]\n正文")

    def test_quote_can_hold_lists(self):
        quote = md.parse(material("> [!GOAL]", "> - 第一项", "> - 第二项")).blocks[0]
        self.assertEqual(quote.blocks[0].kind, "list")


class FigureTests(unittest.TestCase):
    SPEC = {
        "id": "intent",
        "layout": "branch",
        "title": "意图识别与条件路由",
        "kind": "流转图",
        "caption": "路由表。",
    }

    def test_inline_json_spec_is_extracted(self):
        doc = md.parse(
            material(
                "```figure intent",
                json.dumps(self.SPEC, ensure_ascii=False),
                "```",
            )
        )

        self.assertEqual(len(doc.figures), 1)
        ref = doc.figures[0]
        self.assertEqual(ref.id, "intent")
        self.assertEqual(ref.number, 1)
        self.assertEqual(ref.name, "意图识别与条件路由")
        self.assertEqual(ref.kind, "流转图")
        self.assertEqual(ref.caption, "路由表。")
        self.assertEqual(ref.source, "spec")
        self.assertEqual(ref.spec["layout"], "branch")
        self.assertEqual(doc.blocks[0].kind, "figure")
        self.assertIs(doc.blocks[0].ref, ref)

    def test_path_and_empty_bodies(self):
        doc = md.parse(
            material(
                "```figure arch",
                "@figures/arch.json",
                "```",
                "",
                "```figure flow",
                "```",
            )
        )

        arch, flow = doc.figures
        self.assertEqual(arch.source, "path")
        self.assertEqual(arch.spec_or_path, "figures/arch.json")
        self.assertIsNone(arch.spec)
        self.assertEqual(flow.source, "id")
        self.assertEqual(flow.spec_or_path, "")
        self.assertEqual([ref.number for ref in doc.figures], [1, 2])

    def test_numbers_follow_document_order(self):
        doc = md.parse(
            material(
                "```figure a",
                '{"title": "A"}',
                "```",
                "",
                "段落",
                "",
                "```figure b",
                '{"title": "B"}',
                "```",
            )
        )
        self.assertEqual([(r.id, r.number) for r in doc.figures], [("a", 1), ("b", 2)])

    def test_spec_without_kind_leaves_the_badge_empty(self):
        ref = md.parse(material("```figure a", '{"title": "A"}', "```")).figures[0]
        self.assertEqual(ref.kind, "")
        self.assertEqual(ref.name, "A")

    def test_duplicate_id_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(
                material(
                    "```figure a",
                    "```",
                    "",
                    "```figure a",
                    "```",
                )
            )

    def test_invalid_json_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(material("```figure a", "{ not json", "```"))

    def test_missing_id_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(material("```figure", "```"))

    def test_body_that_is_neither_spec_nor_path_raises(self):
        with self.assertRaises(md.MarkdownError):
            md.parse(material("```figure a", "figures/a.json", "```"))


class InlineTests(unittest.TestCase):
    def test_bold_code_and_link(self):
        self.assertEqual(md.inline("**粗**"), "<strong>粗</strong>")
        self.assertEqual(md.inline("`code`"), "<code>code</code>")
        self.assertEqual(
            md.inline("[文字](https://e.com/a)"),
            '<a href="https://e.com/a">文字</a>',
        )

    def test_inline_forms_nest(self):
        self.assertEqual(
            md.inline("**粗 `code` 体**"),
            "<strong>粗 <code>code</code> 体</strong>",
        )
        self.assertEqual(
            md.inline("[**重点**](u)"),
            '<a href="u"><strong>重点</strong></a>',
        )

    def test_code_span_protects_its_markup(self):
        self.assertEqual(md.inline("`a **b** c`"), "<code>a **b** c</code>")

    def test_angle_brackets_and_ampersands_are_escaped(self):
        self.assertEqual(md.inline("a < b & c"), "a &lt; b &amp; c")
        self.assertEqual(md.inline("**A&B**"), "<strong>A&amp;B</strong>")
        self.assertEqual(md.inline("`<script>`"), "<code>&lt;script&gt;</code>")
        self.assertEqual(
            md.inline("[x](https://e.com/?a=1&b=2)"),
            '<a href="https://e.com/?a=1&amp;b=2">x</a>',
        )

    def test_quotes_are_escaped_so_a_link_cannot_break_out(self):
        self.assertEqual(
            md.inline('[x](https://e.com/?q="onmouseover=1)'),
            '<a href="https://e.com/?q=&quot;onmouseover=1">x</a>',
        )

    def test_unclosed_markers_stay_literal(self):
        self.assertEqual(md.inline("2 ** 3"), "2 ** 3")
        self.assertEqual(md.inline("**未闭合"), "**未闭合")
        self.assertEqual(md.inline("`未闭合"), "`未闭合")


class TocTests(unittest.TestCase):
    def test_entries_are_flat_and_in_document_order(self):
        doc = md.parse(material("# 一", "## 一甲", "# 二", "### 二甲一"))

        self.assertEqual(
            [(e.level, e.id, e.title) for e in doc.toc],
            [
                (1, "一", "一"),
                (2, "一甲", "一甲"),
                (1, "二", "二"),
                (3, "二甲一", "二甲一"),
            ],
        )

    def test_slug_is_deterministic_and_punctuation_becomes_one_dash(self):
        self.assertEqual(md.slugify("总体架构：核心"), "总体架构-核心")
        self.assertEqual(md.slugify("A B/C"), "a-b-c")
        self.assertEqual(md.slugify("!!!"), "section")

    def test_duplicate_titles_get_distinct_ids(self):
        doc = md.parse(material("# 重复", "# 重复", "# 重复"))
        self.assertEqual([e.id for e in doc.toc], ["重复", "重复-2", "重复-3"])

    def test_toc_is_reserved_so_a_heading_cannot_steal_the_anchor(self):
        doc = md.parse(material("# TOC"))
        self.assertEqual(doc.toc[0].id, "toc-2")

    def test_parsing_twice_gives_identical_tocs(self):
        src = material("# 一", "## 一甲：细节", "# 一")
        self.assertEqual(md.parse(src).toc, md.parse(src).toc)

    def test_headings_inside_a_quote_still_reach_the_outline(self):
        doc = md.parse(material("> ## 引用里的小节"))
        self.assertEqual([e.title for e in doc.toc], ["引用里的小节"])


class ModelTests(unittest.TestCase):
    def test_every_block_carries_its_kind_label(self):
        doc = md.parse(
            material(
                "# 标题",
                "段落",
                "",
                "- 项",
                "",
                "> 引用",
                "",
                "| a | b |",
                "| --- | --- |",
                "| 1 | 2 |",
                "",
                "```python",
                "x = 1",
                "```",
                "",
                "---",
                "",
                "```figure f",
                "```",
            )
        )
        self.assertEqual(
            [b.kind for b in doc.blocks],
            ["heading", "paragraph", "list", "quote", "table", "code", "rule", "figure"],
        )

    def test_parse_file_reads_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "material.md"
            path.write_text(material("---", "title: 材料", "---", "# 标题"), encoding="utf-8")
            doc = md.parse_file(path)

        self.assertEqual(doc.meta["title"], "材料")
        self.assertEqual(doc.toc[0].title, "标题")


if __name__ == "__main__":
    unittest.main()
