"""Tests for document assembly.

These pin the two things the document layer is responsible for: the numbering
ladder (exact strings, because authors read them) and the markup shape that
``assets/base.css`` styles. Where the shape matters -- figure cards and alert
callouts -- the assertions are on the literal HTML, not on a fragment of it.
"""

from __future__ import annotations

import re
import unittest

from docforge import markdown as md
from docforge import validate as V
from docforge.document import DocumentError, render
from docforge.markdown import Doc
from docforge.theme import Theme, document_css

THEME = Theme.load("paper")
SVG = '<svg class="dg" viewBox="0 0 10 10" role="img"><text>x</text></svg>'


def material(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def heading_texts(html: str) -> list:
    """The numbered titles of the *sections*, skipping the hero's bare <h1>."""
    return re.findall(r'<h[1-5](?: class="doc")? id="[^"]*">([^<]*)</h[1-5]>', html)


def ids(html: str) -> set:
    return set(re.findall(r'\sid="([^"]+)"', html))


def anchors(html: str) -> set:
    return set(re.findall(r'href="#([^"]+)"', html))


class HeadTests(unittest.TestCase):
    def setUp(self):
        self.doc = md.parse(
            material(
                "---",
                "title: 通用 Agent",
                "eyebrow: Playbook",
                "description: 一句话说明。",
                "---",
                "# 总体架构",
            )
        )
        self.html = render(self.doc, {}, THEME)

    def test_it_is_a_complete_single_file_document(self):
        for fragment in (
            "<!doctype html>",
            '<html lang="zh-CN"',
            '<meta charset="utf-8">',
            '<meta name="viewport"',
            "<title>通用 Agent</title>",
            '<meta name="description" content="一句话说明。">',
            "</body>",
            "</html>",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.html)

    def test_theme_css_is_inlined_verbatim(self):
        self.assertIn("<style>", self.html)
        self.assertIn(document_css(THEME), self.html)
        self.assertIn("--c-indigo", self.html)
        self.assertIn(".fighead", self.html)

    def test_the_material_chooses_the_opening_mode(self):
        """Light unless the material says otherwise, whatever `dark` says."""
        self.assertIn('<html lang="zh-CN" data-theme="light" data-nav="open">', self.html)
        self.assertIn('<html lang="zh-CN" data-theme="light" data-nav="open">',
                      render(self.doc, {}, THEME, dark=False))
        dark_doc = Doc(meta=dict(self.doc.meta, mode="dark"),
                       blocks=self.doc.blocks, figures=[], toc=[])
        self.assertIn('<html lang="zh-CN" data-theme="dark" data-nav="open">',
                      render(dark_doc, {}, THEME))

    def test_dark_selects_whether_the_toggle_is_offered(self):
        self.assertIn('id="themeBtn"', self.html)
        self.assertIn("dsh-doc-theme", self.html)
        self.assertNotIn('id="themeBtn"', render(self.doc, {}, THEME, dark=False))
        self.assertNotIn("dsh-doc-theme", render(self.doc, {}, THEME, dark=False))

    def test_hero_renders_eyebrow_and_lede(self):
        self.assertIn('<span class="eyebrow">Playbook</span>', self.html)
        self.assertIn('<p class="lede">一句话说明。</p>', self.html)
        self.assertIn('<h1>通用 Agent</h1>', self.html)

    def test_meta_chips_come_from_front_matter_when_declared(self):
        doc = md.parse(material("---", "meta:", "  - 13 个阶段", "---", "# 一"))
        self.assertIn('<div class="meta"><span>13 个阶段</span></div>', render(doc, {}, THEME))

    def test_meta_chips_are_derived_when_not_declared(self):
        html = render(self.doc, {}, THEME)
        self.assertIn("<span>1 个章节</span>", html)

    def test_title_falls_back_to_the_first_heading(self):
        html = render(md.parse(material("# 只有标题")), {}, THEME)
        self.assertIn("<title>只有标题</title>", html)

    def test_theme_name_is_accepted_as_well_as_a_theme_object(self):
        self.assertIn(document_css(THEME), render(self.doc, {}, "paper"))

    def test_footer_is_rendered(self):
        self.assertIn('<footer class="doc">', self.html)
        self.assertIn("单文件 HTML，图示为内联 SVG", self.html)


class NumberingTests(unittest.TestCase):
    LADDER = material(
        "# 总体架构",
        "",
        "## 内核层",
        "",
        "### 关键动作",
        "",
        "#### 状态设计",
        "",
        "##### 字段清单",
        "",
        "#### 图与边",
        "",
        "### 第二组",
        "",
        "## 外壳层",
        "",
        "# 工程运维层",
        "",
        "## 部署",
    )

    def test_the_whole_ladder_with_exact_strings(self):
        html = render(md.parse(self.LADDER), {}, THEME)

        self.assertEqual(
            heading_texts(html),
            [
                "一、总体架构",
                "1. 内核层",
                "[1] 关键动作",
                "1.1 状态设计",
                "[1] 字段清单",
                "1.2 图与边",
                "[2] 第二组",
                "2. 外壳层",
                "二、工程运维层",
                "1. 部署",
            ],
        )

    def test_h1_uses_chinese_numerals_and_restarts_nothing(self):
        html = render(md.parse(material(*[f"# 第{i}节" for i in range(1, 13)])), {}, THEME)
        self.assertIn(">一、第1节</h1>", html)
        self.assertIn(">十、第10节</h1>", html)
        self.assertIn(">十一、第11节</h1>", html)
        self.assertIn(">十二、第12节</h1>", html)

    def test_h2_restarts_per_h1_and_h3_restarts_per_h2(self):
        html = render(
            md.parse(
                material(
                    "# 一",
                    "## 甲",
                    "### 子一",
                    "### 子二",
                    "## 乙",
                    "### 子一",
                    "# 二",
                    "## 甲",
                )
            ),
            {},
            THEME,
        )
        self.assertEqual(
            heading_texts(html),
            [
                "一、一",
                "1. 甲",
                "[1] 子一",
                "[2] 子二",
                "2. 乙",
                "[1] 子一",
                "二、二",
                "1. 甲",
            ],
        )

    def test_h4_prefix_comes_from_the_enclosing_h2(self):
        html = render(
            md.parse(material("# 一", "## 甲", "#### 细节", "## 乙", "#### 细节")),
            {},
            THEME,
        )
        self.assertEqual(
            heading_texts(html),
            ["一、一", "1. 甲", "1.1 细节", "2. 乙", "2.1 细节"],
        )

    def test_headings_are_anchored_by_slug(self):
        html = render(md.parse(material("# 总体架构：核心", "## A B/C")), {}, THEME)
        self.assertIn('<h1 class="doc" id="总体架构-核心">', html)
        self.assertIn('<h2 id="a-b-c">', html)

    def test_manual_numbering_emits_titles_verbatim(self):
        html = render(md.parse(self.LADDER), {}, THEME, numbering="manual")

        self.assertEqual(
            heading_texts(html),
            [
                "总体架构",
                "内核层",
                "关键动作",
                "状态设计",
                "字段清单",
                "图与边",
                "第二组",
                "外壳层",
                "工程运维层",
                "部署",
            ],
        )

    def test_unknown_numbering_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            render(md.parse("# 一"), {}, THEME, numbering="sometimes")


class OutlineTests(unittest.TestCase):
    def setUp(self):
        self.doc = md.parse(
            material(
                "---",
                "title: 文档",
                "---",
                "# 总体架构",
                "## 内核层",
                "### 关键动作",
                "## 外壳层",
                "# 工程运维层",
            )
        )
        self.html = render(self.doc, {}, THEME)

    def test_outline_lists_h1_and_h2_with_the_rendered_numbers(self):
        toc = self.html.split('<nav class="toc"', 1)[1].split("</nav>", 1)[0]

        self.assertIn('<a href="#总体架构">一、总体架构</a>', toc)
        self.assertIn('<a href="#内核层">1. 内核层</a>', toc)
        self.assertIn('<a href="#外壳层">2. 外壳层</a>', toc)
        self.assertIn('<a href="#工程运维层">二、工程运维层</a>', toc)
        self.assertIn("<ul>", toc)
        self.assertNotIn("关键动作", toc)

    def topbar_markup(self) -> str:
        return self.html.split('<div class="topbar-in">', 1)[1].split("</div></div>\n", 1)[0]

    def test_topbar_carries_no_heading_links(self):
        """A second copy of the headings up here only fought the title for room."""
        topbar = self.topbar_markup()

        self.assertIn('<span class="brand"><i></i>文档</span>', topbar)
        self.assertIn('id="themeBtn"', topbar)
        self.assertNotIn("<nav>", topbar)
        self.assertNotIn("<a ", topbar, "the topbar must not link anywhere")
        self.assertNotIn('id="navBtn"', topbar, "the outline control lives on the rail")

    def test_the_search_field_is_always_present_not_behind_a_button(self):
        topbar = self.topbar_markup()
        self.assertIn('<input id="finderInput" type="search"', topbar,
                      "searching must not cost a click to reveal the field")
        self.assertIn('id="finderList"', topbar)

    def test_search_can_be_switched_off(self):
        html = render(self.doc, {}, THEME, search=False)
        self.assertNotIn('id="finderInput"', html)
        self.assertNotIn('id="finderList"', html)

    def test_every_anchor_resolves(self):
        self.assertEqual(anchors(self.html) - ids(self.html), set())

    def test_outline_can_be_switched_off(self):
        html = render(self.doc, {}, THEME, toc=False)

        self.assertNotIn('<nav class="toc"', html)
        self.assertNotIn('href="#toc"', html)
        self.assertEqual(anchors(html) - ids(html), set())


class ShellTests(unittest.TestCase):
    """The page shell contract: html[data-nav] + .shell > aside.sidebar, main.content."""

    def setUp(self):
        self.doc = md.parse(
            material(
                "---",
                "title: 文档",
                "---",
                "# 总体架构",
                "## 内核层",
                "# 工程运维层",
            )
        )
        self.html = render(self.doc, {}, THEME)

    def topbar_in(self) -> str:
        return self.html.split('<div class="topbar-in">', 1)[1].split("</div></div>\n", 1)[0]

    def toc_html(self) -> str:
        return self.html.split('<nav class="toc"', 1)[1].split("</nav>", 1)[0]

    def test_the_outline_is_open_by_default(self):
        self.assertIn('data-nav="open"', self.html.split("<head>", 1)[0])

    def test_the_shell_holds_the_sidebar_then_the_content(self):
        shell = self.html.split('<div class="shell">', 1)[1]
        self.assertLess(shell.index('<aside class="sidebar" id="sidebar">'),
                        shell.index('<main class="content">'))
        self.assertIn('<nav class="toc" id="toc">', shell.split("</aside>", 1)[0])

    def test_hero_sections_and_footer_live_inside_the_content_column(self):
        main = self.html.split('<main class="content">', 1)[1].split("</main>", 1)[0]
        self.assertIn('<header class="hero">', main)
        self.assertIn('<h1 class="doc" id="总体架构">', main)
        self.assertIn('<footer class="doc">', main)
        self.assertNotIn('class="sidebar"', main)

    def test_the_outline_keeps_its_anchor_and_points_at_real_headings(self):
        toc = self.toc_html()
        targets = set(re.findall(r'href="#([^"]+)"', toc))
        headings = set(re.findall(r'<h[1-5][^>]*\sid="([^"]+)"', self.html))
        self.assertEqual(set(), targets - headings)
        self.assertIn("总体架构", targets)

    def test_the_outline_rail_is_a_sibling_of_the_sidebar(self):
        """It must sit beside the <aside>, never inside it.

        Collapsing the outline hides the aside; a control nested in there would
        disappear with it, leaving no way to bring the outline back.
        """
        shell = self.html.split('<div class="shell">', 1)[1]
        aside = shell.split("</aside>", 1)[0]
        self.assertNotIn('id="navBtn"', aside)
        self.assertIn('<button class="navrail" id="navBtn" type="button"', shell)
        self.assertIn('aria-controls="sidebar"', shell)
        self.assertLess(shell.index("</aside>"), shell.index('id="navBtn"'),
                        "the rail follows the aside in source order")
        self.assertLess(shell.index('id="navBtn"'), shell.index('<main class="content">'))

    def test_the_rail_glyph_reads_as_collapse_while_open(self):
        shell = self.html.split('<div class="shell">', 1)[1]
        rail = shell.split('id="navBtn"', 1)[1].split("</button>", 1)[0]
        self.assertIn("<svg", rail, "the chevron is drawn, not typed")
        self.assertIn('aria-expanded="true"', rail)
        self.assertIn('aria-label="收起目录"', rail)

    def test_the_choice_is_read_before_the_body_so_it_survives_a_reload(self):
        head = self.html.split("<body>", 1)[0]
        self.assertIn("dsh-doc-nav", head)
        self.assertIn("localStorage", head)
        self.assertIn("dsh-doc-nav", self.html.split("</main>", 1)[1])

    def test_the_opening_state_is_width_aware_and_breakpoint_aware(self):
        """No stored choice -> closed under the drawer breakpoint, open above it.

        The stored choice wins either way, and crossing *into* the drawer
        layout collapses without writing to the store.
        """
        head = self.html.split("<body>", 1)[0]
        self.assertIn("(max-width: 1080px)", head)
        self.assertIn("matchMedia(NARROW).matches", head)
        self.assertIn("setAttribute('data-nav', 'closed')", head)

        body = self.html.split("</main>", 1)[1]
        self.assertIn("addEventListener('change'", body)
        self.assertIn("ev.matches && isOpen()", body)

    def test_no_outline_means_no_sidebar_and_no_toggle(self):
        html = render(self.doc, {}, THEME, toc=False)
        self.assertIn('<div class="shell no-sidebar">', html)
        self.assertIn('<main class="content">', html)
        self.assertNotIn('<aside class="sidebar"', html)
        self.assertNotIn('id="navBtn"', html)
        self.assertNotIn('id="scrim"', html)
        self.assertEqual(anchors(html) - ids(html), set())

    def test_two_shells_render_byte_identically(self):
        self.assertEqual(self.html, render(self.doc, {}, THEME))


class ShellCssTests(unittest.TestCase):
    """The stylesheet side of the shell contract, pinned where it is easy to drift."""

    CSS = document_css(THEME)

    def test_the_grid_is_the_documented_two_column_shape(self):
        self.assertIn("--rail: 288px", self.CSS)
        self.assertIn("grid-template-columns: var(--rail) minmax(0, 1fr)", self.CSS)

    def test_collapsing_drives_the_track_through_the_variable(self):
        """The track is a variable, not a transitioned property.

        ``transition: grid-template-columns`` matched and had the right value
        but the computed columns never moved, so the outline could not be
        collapsed at all on a wide screen.
        """
        self.assertIn('[data-nav="closed"] .shell { --rail: 0px;', self.CSS)
        self.assertNotIn("transition: grid-template-columns", self.CSS)

    def test_a_figure_may_no_longer_force_a_minimum_width(self):
        self.assertNotIn("min-width: 620px", self.CSS)
        self.assertNotIn("min-width: 560px", self.CSS)
        self.assertIn("figure .canvas { padding: 16px 16px 6px; overflow-x: auto; }", self.CSS)

    def test_the_sidebar_is_sticky_and_independently_scrollable(self):
        self.assertIn("position: sticky", self.CSS)
        self.assertIn("height: calc(100vh - var(--topbar-h))", self.CSS)
        self.assertIn("overflow-y: auto", self.CSS)

    def test_the_drawer_breakpoint_and_reduced_motion_are_declared(self):
        self.assertIn("@media (max-width: 1080px)", self.CSS)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.CSS)
        self.assertIn("@media print", self.CSS)


class FigureTests(unittest.TestCase):
    DOC = material(
        "```figure intent",
        '{"layout": "branch", "title": "意图识别", "kind": "流转图", "caption": "兜底分支必须存在。"}',
        "```",
    )

    def test_figure_card_shape_matches_the_stylesheet(self):
        html = render(md.parse(self.DOC), {"intent": SVG}, THEME)

        self.assertIn(
            '<figure id="fig-intent"><div class="fighead">'
            '<span class="num">图 1</span><span class="name">意图识别</span>'
            '<span class="kind">流转图</span></div>'
            f'<div class="canvas">{SVG}</div>'
            "<figcaption>兜底分支必须存在。</figcaption></figure>",
            html,
        )

    def test_figures_are_numbered_in_document_order(self):
        doc = md.parse(
            material(
                "```figure a",
                '{"title": "A"}',
                "```",
                "",
                "```figure b",
                '{"title": "B"}',
                "```",
            )
        )
        html = render(doc, {"a": SVG, "b": SVG}, THEME)

        self.assertIn('<span class="num">图 1</span><span class="name">A</span>', html)
        self.assertIn('<span class="num">图 2</span><span class="name">B</span>', html)

    def test_spec_text_is_escaped_and_inline_markup_is_rendered(self):
        doc = md.parse(
            material(
                "```figure a",
                '{"title": "A <b>", "caption": "见 **文档** & 图"}',
                "```",
            )
        )
        html = render(doc, {"a": SVG}, THEME)

        self.assertIn('<span class="name">A &lt;b&gt;</span>', html)
        self.assertIn("<figcaption>见 <strong>文档</strong> &amp; 图</figcaption>", html)

    def test_a_figure_without_a_kind_still_renders_a_badge(self):
        html = render(md.parse(material("```figure a", "```")), {"a": SVG}, THEME)
        self.assertIn('<span class="kind">图示</span>', html)
        self.assertIn('<span class="name">a</span>', html)

    def test_unused_entries_in_the_figure_map_are_ignored(self):
        html = render(md.parse(self.DOC), {"intent": SVG, "extra": SVG}, THEME)
        self.assertNotIn("<figure id=\"fig-extra\">", html)

    def test_missing_figure_gets_a_visible_placeholder(self):
        html = render(md.parse(self.DOC), {}, THEME)

        self.assertIn("<!-- FIG:intent unresolved -->", html)
        self.assertIn('<div class="fig-missing" data-figure="intent"', html)
        self.assertIn("缺少渲染结果", html)
        self.assertNotIn('<figure id="fig-intent">', html)

    def test_missing_figure_is_caught_by_the_document_checker(self):
        html = render(md.parse(self.DOC), {}, THEME)
        codes = {f.code for f in V.check_document(html, figure_ids=["intent"])}

        self.assertIn("unresolved-figure", codes)
        self.assertIn("figure-missing", codes)

    def test_a_complete_document_has_no_findings(self):
        html = render(md.parse(self.DOC), {"intent": SVG}, THEME)

        self.assertEqual(V.check_document(html, figure_ids=["intent"]), [])

    def test_path_reference_placeholder_names_the_file(self):
        doc = md.parse(material("```figure arch", "@figures/arch.json", "```"))
        html = render(doc, {}, THEME)

        self.assertIn("来源 figures/arch.json", html)


class CalloutTests(unittest.TestCase):
    def render_quote(self, tag: str) -> str:
        doc = md.parse(material(f"> [!{tag}]", "> 正文。"))
        return render(doc, {}, THEME)

    def test_note_maps_to_the_note_class(self):
        self.assertIn('<blockquote class="note"><p>正文。</p>', self.render_quote("NOTE"))

    def test_key_maps_to_a_plain_blockquote(self):
        self.assertIn("<blockquote><p>正文。</p>", self.render_quote("KEY"))

    def test_goal_maps_to_the_goal_div_with_its_mark(self):
        html = self.render_quote("GOAL")

        self.assertIn('<div class="goal"><span class="mark">目标</span>', html)
        self.assertIn('<div class="body"><p>正文。</p>', html)

    def test_accept_maps_to_the_accept_div_with_its_mark(self):
        html = self.render_quote("ACCEPT")

        self.assertIn('<div class="accept"><span class="mark">验收</span>', html)
        self.assertIn('<div class="body"><p>正文。</p>', html)

    def test_plain_quote_has_no_alert_class(self):
        html = render(md.parse(material("> 正文。")), {}, THEME)
        self.assertIn("<blockquote><p>正文。</p>", html)


class BlockMarkupTests(unittest.TestCase):
    def test_table_is_wrapped_for_horizontal_scrolling(self):
        doc = md.parse(
            material(
                "| 约束 | 要求 |",
                "| --- | --- |",
                "| 超时 | `10–30` 秒 |",
            )
        )
        html = render(doc, {}, THEME)

        self.assertIn(
            '<div class="tw"><table><thead><tr><th>约束</th><th>要求</th></tr></thead>'
            "<tbody><tr><td>超时</td><td><code>10–30</code> 秒</td></tr></tbody></table></div>",
            html,
        )

    def test_lists_render_two_levels(self):
        html = render(
            md.parse(material("- 一级", "  - 二级", "", "1. 有序")), {}, THEME
        )

        self.assertIn("<ul><li>一级<ul><li>二级</li></ul></li></ul>", html)
        self.assertIn("<ol><li>有序</li></ol>", html)

    def test_code_fence_keeps_its_language_class(self):
        html = render(md.parse(material("```python", "x = 1 < 2", "```")), {}, THEME)

        self.assertIn(
            '<div class="code-block fam-code" data-lang="python">'
            '<button class="code-copy" type="button" aria-label="复制代码"'
            ' title="复制代码">python</button>'
            '<pre><code class="lang-python">'
            'x <span class="tok-op">=</span> <span class="tok-num">1</span> '
            '<span class="tok-op">&lt;</span> <span class="tok-num">2</span>'
            "</code></pre></div>",
            html,
        )

    def test_the_language_badge_is_the_copy_button(self):
        """One label, so the tag shown and the code copied cannot disagree."""
        html = render(md.parse(material("```json", '{"a": 1}', "```")), {}, THEME)
        button = html.split('<button class="code-copy"', 1)[1].split("</button>", 1)[0]
        self.assertIn('type="button"', button)
        self.assertIn(">json</button>", button + "</button>")
        self.assertIn('data-lang="json"', html)

    def test_a_code_fence_is_chromed_and_escaped_whatever_its_language(self):
        """The chrome is unconditional; the body survives untagged or unknown."""
        cases = (
            ("```\na < b\n```", "text", "a &lt; b"),
            ("```nope\nc & d\n```", "nope", "c &amp; d"),
        )
        for fence, lang, escaped in cases:
            with self.subTest(lang=lang):
                html = render(md.parse(material(*fence.split("\n"))), {}, THEME)
                attrs, rest = html.split('<div class="code-block', 1)[1].split(">", 1)
                body = rest.split("</div>", 1)[0]
                body = body.split("</button>", 1)[-1]      # drop the copy badge

                self.assertRegex(attrs, r'^ fam-\w+" data-lang="' + lang + '"$')
                self.assertEqual(escaped, re.sub(r"<[^>]+>", "", body).strip())

    def test_headings_and_text_are_escaped(self):
        html = render(
            md.parse(
                material(
                    "# 标题 <b> & 更多",
                    "",
                    "段落 <script>alert(1)</script> & 结束",
                )
            ),
            {},
            THEME,
        )

        self.assertIn(">一、标题 &lt;b&gt; &amp; 更多</h1>", html)
        self.assertIn("<p>段落 &lt;script&gt;alert(1)&lt;/script&gt; &amp; 结束</p>", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<b>", html)

    def test_sections_are_separated_by_one_rule(self):
        html = render(md.parse(material("# 一", "", "正文", "", "# 二")), {}, THEME)
        self.assertEqual(html.count("<hr>"), 1)

    def test_an_explicit_rule_is_not_doubled(self):
        html = render(md.parse(material("# 一", "", "---", "", "# 二")), {}, THEME)
        self.assertEqual(html.count("<hr>"), 1)


class DeterminismTests(unittest.TestCase):
    DOC = material(
        "---",
        "title: 确定性",
        "---",
        "# 一",
        "## 甲",
        "",
        "- 项",
        "  - 子项",
        "",
        "> [!ACCEPT]",
        "> 通过。",
        "",
        "```figure f",
        '{"title": "图", "kind": "架构图"}',
        "```",
    )

    def test_two_renders_are_byte_identical(self):
        doc = md.parse(self.DOC)
        figures = {"f": SVG}
        self.assertEqual(render(doc, figures, THEME), render(doc, figures, THEME))

    def test_rendering_is_independent_of_figure_map_insertion_order(self):
        doc = md.parse(self.DOC)
        first = render(doc, {"f": SVG, "unused": ""}, THEME)
        second = render(doc, {"unused": "", "f": SVG}, THEME)
        self.assertEqual(first, second)


class SelfCheckTests(unittest.TestCase):
    def colliding_doc(self) -> md.Doc:
        """A hand-built Doc whose heading steals the outline's anchor id."""
        return md.Doc(
            meta={"title": "碰撞"},
            blocks=[md.Heading(level=1, id="toc", title="toc")],
            figures=[],
            toc=[md.TocEntry(level=1, id="toc", title="toc")],
        )

    def test_a_duplicate_id_raises(self):
        with self.assertRaises(DocumentError):
            render(self.colliding_doc(), {}, THEME)

    def test_the_check_can_be_waived(self):
        html = render(self.colliding_doc(), {}, THEME, validate=False)
        self.assertIn('<h1 class="doc" id="toc">', html)

    def test_the_parser_keeps_headings_away_from_the_outline_anchor(self):
        html = render(md.parse(material("# TOC")), {}, THEME)
        self.assertEqual(anchors(html) - ids(html), set())


if __name__ == "__main__":
    unittest.main()
