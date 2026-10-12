"""End-to-end tests: material in, single-file HTML out.

These exercise the whole pipe — material parsing, figure rendering, document
assembly, validation, the CLI — and pin down the properties a caller actually
depends on: deterministic output, a non-zero exit when something is wrong, and a
document that is genuinely self-contained.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from docforge import TEMPLATES, __version__
from docforge import cli, document, markdown, specs
from docforge import validate as V
from docforge.theme import Theme

ROOT = Path(__file__).resolve().parent.parent


def run_cli(*argv):
    """Invoke the CLI in-process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="docforge-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def scaffold(self, template="doc"):
        target = self.tmp / template
        shutil.copytree(TEMPLATES / template, target)
        return target


# --------------------------------------------------------------------------
class BuildPipelineTest(TempDirTest):
    def test_shipped_templates_build_cleanly(self):
        for template in ("doc", "report", "course"):
            with self.subTest(template=template):
                src = self.scaffold(template)
                out = self.tmp / f"{template}.html"
                code, stdout, stderr = run_cli(
                    "build", str(src / "material.md"), "-o", str(out))
                self.assertEqual(0, code, stderr + stdout)
                self.assertTrue(out.is_file())
                self.assertIn("ok — no findings", stdout)

    def test_document_is_self_contained(self):
        src = self.scaffold("doc")
        out = self.tmp / "index.html"
        run_cli("build", str(src / "material.md"), "-o", str(out))
        html = out.read_text()
        self.assertIn("<style>", html)
        self.assertIn("<svg", html)
        # no external fetches: no src=, no @import, no off-site href
        self.assertNotIn("@import", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link rel=\"stylesheet\"", html)
        for match in re.findall(r'(?:src|href)="([^"]+)"', html):
            self.assertTrue(
                match.startswith("#") or match.startswith("mailto:"),
                f"document is not self-contained: {match}",
            )

    def test_build_is_deterministic(self):
        src = self.scaffold("doc")
        a, b = self.tmp / "a.html", self.tmp / "b.html"
        run_cli("build", str(src / "material.md"), "-o", str(a))
        run_cli("build", str(src / "material.md"), "-o", str(b))
        self.assertEqual(a.read_text(), b.read_text(),
                         "two builds of the same material must be byte-identical")

    def test_every_declared_figure_renders(self):
        src = self.scaffold("doc")
        out = self.tmp / "index.html"
        run_cli("build", str(src / "material.md"), "-o", str(out))
        html = out.read_text()
        self.assertEqual(2, len(re.findall(r"<figure[ >]", html)))
        # Diagram SVGs carry class="dg"; the outline rail's chevron is also an
        # <svg>, so a bare count of the tag would depend on unrelated chrome.
        self.assertEqual(2, len(re.findall(r'<svg class="dg"', html)))
        self.assertNotIn("figure-placeholder-error", html)

    def test_figures_render_per_theme(self):
        """Figure colours come from CSS variables, never baked in."""
        src = self.scaffold("doc")
        out = self.tmp / "index.html"
        run_cli("build", str(src / "material.md"), "-o", str(out))
        html = out.read_text()
        svg = html[html.index("<svg"):html.index("</svg>")]
        self.assertNotRegex(svg, r'(?:fill|stroke)="#[0-9a-fA-F]{3,6}"',
                            "no hard-coded colours inside the SVG")


class NumberingTest(TempDirTest):
    def test_auto_numbering_ladder(self):
        src = self.scaffold("doc")
        out = self.tmp / "index.html"
        run_cli("build", str(src / "material.md"), "-o", str(out))
        html = out.read_text()
        self.assertRegex(html, r"一、\s*背景与目标")
        self.assertRegex(html, r"1\.\s*现状")

    def test_a_title_that_is_already_numbered_is_not_numbered_twice(self):
        material = self.tmp / "m.md"
        material.write_text(
            "---\ntitle: T\nnumbering: auto\n---\n\n"
            "# 一、已经编好号了\n\n"
            "## 2. 也是\n\n"
            "### [1] 还有这个\n\n"
            "正文。\n"
        )
        out = self.tmp / "o.html"
        code, stdout, _ = run_cli("build", str(material), "-o", str(out))
        self.assertEqual(0, code)
        html = out.read_text()
        headings = re.findall(r"<h[1-5][^>]*>([^<]*)</h[1-5]>", html)
        doubled = [h for h in headings if re.match(r"^\s*(\[\d+\]|\d+\.|[一二三四五六七八九十]+、)\s*\1", h)]
        self.assertEqual([], doubled, f"titles numbered twice: {doubled}")
        self.assertIn("已经编好号了", " ".join(headings))
        self.assertFalse([h for h in headings if h.count("已经编好号了") > 1],
                         f"title duplicated: {headings}")

    def test_manual_numbering_is_verbatim(self):
        material = self.tmp / "m.md"
        material.write_text("---\ntitle: T\nnumbering: manual\n---\n\n# 标题原文\n")
        out = self.tmp / "o.html"
        run_cli("build", str(material), "-o", str(out))
        self.assertIn("标题原文", out.read_text())
        self.assertNotIn("一、标题原文", out.read_text())


class FailureModesTest(TempDirTest):
    def test_missing_material_is_a_usage_error(self):
        code, _, err = run_cli("build", str(self.tmp / "nope.md"))
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("no such material", err)

    def test_missing_figure_spec_is_an_error_not_a_crash(self):
        material = self.tmp / "m.md"
        material.write_text(
            "---\ntitle: T\n---\n\n# H\n\n```figure ghost\n@figures/nope.json\n```\n"
        )
        code, stdout, _ = run_cli("build", str(material), "-o", str(self.tmp / "o.html"))
        self.assertEqual(cli.EXIT_VALIDATION, code)
        self.assertIn("figure-spec-missing", stdout)

    def test_broken_figure_spec_does_not_abort_the_build(self):
        material = self.tmp / "m.md"
        material.write_text("---\ntitle: T\n---\n\n# H\n")
        figures = self.tmp / "figures"
        figures.mkdir()
        (figures / "bad.json").write_text('{"id":"bad","layout":"nope","nodes":[]}')
        material.write_text(
            "---\ntitle: T\n---\n\n# H\n\n```figure bad\n@figures/bad.json\n```\n"
        )
        code, stdout, _ = run_cli("build", str(material), "-o", str(self.tmp / "o.html"))
        self.assertEqual(cli.EXIT_VALIDATION, code)
        self.assertIn("figure-spec-invalid", stdout)
        self.assertIn("unknown layout", stdout)
        self.assertTrue((self.tmp / "o.html").is_file(),
                        "a broken figure must still produce a document to look at")

    def test_document_checks_catch_a_dangling_anchor(self):
        html = '<div id="a"><a href="#missing">x</a></div>'
        codes = {f.code for f in V.check_document(html)}
        self.assertIn("dangling-anchor", codes)

    def test_document_checks_catch_an_unresolved_placeholder(self):
        codes = {f.code for f in V.check_document("<!--FIG:x|1|k|n-->")}
        self.assertIn("unresolved-figure", codes)

    def test_fail_on_controls_the_exit_code(self):
        src = self.scaffold("doc")
        for mode, expect in (("error", 0), ("warning", 0), ("none", 0)):
            code, _, _ = run_cli("check", str(src / "material.md"), "--fail-on", mode)
            self.assertEqual(expect, code, f"--fail-on {mode}")


class CliSurfaceTest(unittest.TestCase):
    def test_skill_info_json_is_complete_and_parseable(self):
        code, out, _ = run_cli("skill-info", "--json")
        self.assertEqual(0, code)
        payload = json.loads(out)
        self.assertEqual("docforge", payload["name"])
        self.assertEqual(__version__, payload["version"])
        self.assertTrue(payload["layouts"])
        self.assertTrue(payload["themes"])
        for key in ("commands", "exit_codes", "validation", "materials"):
            self.assertIn(key, payload)
        # every registered engine must be advertised
        from docforge import layouts
        self.assertEqual(set(layouts.LAYOUTS),
                         {l["name"] for l in payload["layouts"]})

    def test_layouts_json_matches_the_registry(self):
        from docforge import layouts
        code, out, _ = run_cli("layouts", "--json")
        self.assertEqual(0, code)
        self.assertEqual(set(layouts.LAYOUTS),
                         {row["name"] for row in json.loads(out)})

    def test_themes_json_lists_every_theme_with_parity(self):
        code, out, _ = run_cli("themes", "--json")
        self.assertEqual(0, code)
        for row in json.loads(out):
            self.assertEqual([], row["missing"],
                             f"theme {row['name']} lacks token parity")

    def test_check_json_is_machine_readable(self):
        src = Path(ROOT / "examples" / "engines" / "intent.fan.json")
        code, out, _ = run_cli("check", str(src), "--format", "json")
        self.assertEqual(0, code)
        payload = json.loads(out)
        self.assertEqual("ok", payload["summary"]["status"])
        self.assertIsInstance(payload["findings"], list)

    def test_fig_writes_standalone_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "f.svg"
            code, _, err = run_cli(
                "fig", str(ROOT / "examples/engines/intent.fan.json"),
                "-o", str(out), "--no-check")
            self.assertEqual(0, code, err)
            svg = out.read_text()
            self.assertTrue(svg.startswith("<svg"))
            self.assertIn("<style>", svg, "standalone SVG needs its own styles")
            self.assertIn("d-canvas", svg, "standalone SVG needs a backdrop")
            import xml.etree.ElementTree as ET
            ET.fromstring(svg)

    def test_unknown_command_exits_non_zero(self):
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                cli.build_parser().parse_args(["nonsense"])


class ExampleEnginesTest(unittest.TestCase):
    def test_shipped_engine_examples_render_clean(self):
        folder = ROOT / "examples" / "engines"
        specs_found = sorted(folder.glob("*.json"))
        self.assertTrue(specs_found, "expected at least one example spec")
        for path in specs_found:
            with self.subTest(figure=path.name):
                findings = V.check_scene(specs.render(specs.load(path)))
                self.assertEqual(
                    [], [str(f) for f in findings if f.severity == V.ERROR],
                    f"{path.name} must render without errors")


class ValidationContractTest(unittest.TestCase):
    """The document-level checks must fire on real breakage."""

    def test_clean_document_has_no_findings(self):
        src = Path(ROOT / "templates" / "doc")
        doc = markdown.parse_file(src / "material.md")
        theme = Theme.load("paper")
        figures = {}
        for ref in doc.figures:
            spec = specs.load(src / ref.spec_or_path)
            figures[ref.id] = specs.render(spec).svg()
        html = document.render(doc, figures, theme)
        ids = [r.id for r in doc.figures]
        self.assertEqual([], [str(f) for f in V.check_document(html, figure_ids=ids)])

    def test_connector_pointing_at_nothing_is_reported(self):
        """The arrow end must land on the node it claims to join."""
        from docforge.scene import Scene

        def scene(end_x):
            sc = Scene("det", 400, 300)
            a = sc.node(40, 40, 140, 60, "源", id="a")
            b = sc.node(240, 160, 140, 60, "的", id="b")
            sc.edge([(a.bbox.right, a.bbox.cy), (end_x, b.bbox.cy)],
                    from_id="a", to_id="b")
            return sc

        self.assertIn("connector-detached",
                      {f.code for f in V.check_scene(scene(200))})   # 40px short
        self.assertNotIn("connector-detached",
                         {f.code for f in V.check_scene(scene(238))})  # 2px short

    def test_the_from_end_is_not_checked(self):
        """A fan-out's taps start on a shared trunk, not on the source box."""
        from docforge.scene import Scene
        sc = Scene("det2", 600, 300)
        src = sc.node(20, 120, 120, 60, "源", id="s")
        t1 = sc.node(420, 40, 140, 60, "一", id="t1")
        t2 = sc.node(420, 180, 140, 60, "二", id="t2")
        # both leave the source and go through a riser in mid-air
        sc.edge([(300, 150), (400, 150), (400, t1.bbox.cy), (t1.bbox.x, t1.bbox.cy)],
                from_id="s", to_id="t1")
        sc.edge([(300, 150), (400, 150), (400, t2.bbox.cy), (t2.bbox.x, t2.bbox.cy)],
                from_id="s", to_id="t2")
        codes = {f.code for f in V.check_scene(sc)}
        self.assertNotIn("connector-detached", codes)

    def test_sequence_lanes_opt_out(self):
        """In a sequence diagram the endpoints name a lane, not a header box."""
        from docforge import specs
        spec = {
            "id": "seq", "layout": "sequence",
            "lanes": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            "messages": [{"from": "a", "to": "b", "label": "call"}],
        }
        codes = {f.code for f in V.check_scene(specs.render(spec))}
        self.assertNotIn("connector-detached", codes)

    def test_short_connector_is_reported(self):
        """Boxes may be legal and still too close for the arrow between them."""
        from docforge.scene import Scene

        def scene(gap):
            sc = Scene("short", 400, 300)
            a = sc.node(40, 40, 140, 60, "上")
            b = sc.node(40, 40 + 60 + gap, 140, 60, "下")
            sc.edge([(a.bbox.cx, a.bbox.bottom), (b.bbox.cx, b.bbox.y)],
                    from_id=a.id, to_id=b.id)
            return sc

        codes = {f.code for f in V.check_scene(scene(5))}
        self.assertIn("short-connector", codes)

        codes = {f.code for f in V.check_scene(scene(24))}
        self.assertNotIn("short-connector", codes)

    def test_short_connector_does_not_double_report_an_overlap(self):
        from docforge.scene import Scene
        sc = Scene("short2", 400, 300)
        a = sc.node(40, 40, 140, 60, "上")
        b = sc.node(40, 90, 140, 60, "下")      # 10px of actual overlap
        sc.edge([(a.bbox.cx, a.bbox.bottom), (b.bbox.cx, b.bbox.y)],
                from_id=a.id, to_id=b.id)
        codes = {f.code for f in V.check_scene(sc)}
        self.assertIn("box-overlap", codes)
        self.assertNotIn("short-connector", codes,
                         "an overlap is already reported; do not also call it short")

    def test_the_rule_can_be_switched_off(self):
        from docforge.scene import Scene
        sc = Scene("short3", 400, 300)
        a = sc.node(40, 40, 140, 60, "上")
        b = sc.node(40, 105, 140, 60, "下")
        sc.edge([(a.bbox.cx, a.bbox.bottom), (b.bbox.cx, b.bbox.y)],
                from_id=a.id, to_id=b.id)
        self.assertEqual([], V.check_scene(sc, check_short=False))

    def test_toc_anchor_with_no_heading_is_reported(self):
        html = "<h1 id='a'>A</h1>"
        codes = {f.code for f in V.check_document(html, toc_ids=["a", "ghost"])}
        self.assertIn("toc-anchor-missing", codes)
        self.assertNotIn("toc-anchor-missing",
                         {f.code for f in V.check_document(html, toc_ids=["a"])})

    def test_figure_count_mismatch_is_reported(self):
        html = "<figure id='fig-a'></figure>"
        codes = {f.code for f in V.check_document(html, figure_ids=["a", "b"])}
        self.assertIn("figure-count", codes)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
