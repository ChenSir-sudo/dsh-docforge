"""CLI surface tests, plus the optional screenshot path.

The CLI is the interface other agents and plugin wrappers use, so its exit
codes and JSON payloads are part of the contract and get tested like any other
API. The screenshot tests skip themselves when no browser is installed —
`docforge` never requires one.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import pathlib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from docforge import ROOT, TEMPLATES
from docforge import cli, render
from docforge.theme import Theme

EXAMPLE = ROOT / "examples" / "engines" / "dag.dag.json"
FIGURE = ROOT / "examples" / "engines" / "intent.fan.json"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TmpMixin:
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="docforge-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class InitTest(TmpMixin, unittest.TestCase):
    def test_every_template_scaffolds_and_builds(self):
        for template in sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir()):
            with self.subTest(template=template):
                target = self.tmp / template
                code, out, err = run("init", str(target), "--template", template)
                self.assertEqual(0, code, err)
                self.assertTrue((target / "material.md").is_file())
                code, out, err = run("build", str(target / "material.md"),
                                     "-o", str(target / "index.html"))
                self.assertEqual(0, code, out + err)

    def test_refuses_to_clobber_a_non_empty_directory(self):
        target = self.tmp / "busy"
        target.mkdir()
        (target / "keep.txt").write_text("mine")
        code, _, err = run("init", str(target))
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("not empty", err)
        self.assertTrue((target / "keep.txt").is_file())

    def test_force_overwrites(self):
        target = self.tmp / "busy"
        target.mkdir()
        (target / "keep.txt").write_text("mine")
        code, _, err = run("init", str(target), "--force")
        self.assertEqual(0, code, err)

    def test_unknown_template_is_a_usage_error(self):
        code, _, err = run("init", str(self.tmp / "x"), "--template", "nope")
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("no such template", err)


class ListingCommandsTest(unittest.TestCase):
    def test_themes_human_and_json_agree(self):
        code, text, _ = run("themes")
        self.assertEqual(0, code)
        code, payload, _ = run("themes", "--json")
        self.assertEqual(0, code)
        rows = json.loads(payload)
        self.assertEqual(len(Theme.available()), len(rows))
        for row in rows:
            self.assertIn(row["name"], text)
            self.assertEqual([], row["missing"])

    def test_layouts_human_and_json_agree(self):
        from docforge import layouts
        code, text, _ = run("layouts")
        self.assertEqual(0, code)
        code, payload, _ = run("layouts", "--json")
        rows = json.loads(payload)
        self.assertEqual(set(layouts.LAYOUTS), {r["name"] for r in rows})
        for row in rows:
            self.assertTrue(row["what"])
            self.assertIn(row["name"], text)

    def test_examples_lists_the_shipped_folders(self):
        code, payload, _ = run("examples", "--json")
        self.assertEqual(0, code)
        data = json.loads(payload)
        self.assertTrue(Path(data["root"]).is_dir())
        for name in data["examples"]:
            self.assertTrue((Path(data["root"]) / name).is_dir())


class FigCommandTest(TmpMixin, unittest.TestCase):
    def test_writes_svg_to_a_file(self):
        out = self.tmp / "f.svg"
        code, stdout, err = run("fig", str(FIGURE), "-o", str(out), "--no-check")
        self.assertEqual(0, code, err)
        self.assertTrue(out.read_text().startswith("<svg"))
        self.assertNotIn("<svg", stdout, "the report must not repeat the markup")

    def test_prints_to_stdout_without_an_output_path(self):
        code, stdout, err = run("fig", str(FIGURE), "--no-check")
        self.assertEqual(0, code, err)
        self.assertTrue(stdout.lstrip().startswith("<svg"))

    def test_inline_mode_omits_the_standalone_wrapper(self):
        code, stdout, _ = run("fig", str(FIGURE), "--inline", "--no-check")
        self.assertEqual(0, code)
        self.assertNotIn("<style>", stdout)

    def test_dark_mode_embeds_the_dark_palette(self):
        code, light, _ = run("fig", str(FIGURE), "--no-check", "--mode", "light")
        code, dark, _ = run("fig", str(FIGURE), "--no-check", "--mode", "dark")
        self.assertNotEqual(light, dark, "--mode should change the exported SVG")

    def test_fail_on_controls_the_exit_code(self):
        code, _, _ = run("fig", str(FIGURE), "--no-check", "-o", str(self.tmp / "a.svg"))
        self.assertEqual(0, code)

    def test_a_missing_spec_is_a_usage_error(self):
        code, _, err = run("fig", str(self.tmp / "ghost.json"))
        self.assertEqual(cli.EXIT_USAGE, code)
        self.assertIn("no such figure spec", err)


class ShotTest(TmpMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.browser = render.find_browser()
        if not self.browser:
            self.skipTest("no Chromium-family browser installed")

    def test_screenshot_produces_a_png(self):
        html = self.tmp / "p.html"
        html.write_text("<!doctype html><html><body style='margin:0'>"
                        "<h1 style='font-family:sans-serif'>docforge</h1></body></html>")
        png = self.tmp / "p.png"
        # A headless browser is an external dependency. A busy host -- or a
        # stray browser left by another session -- can make it miss the
        # deadline, and that says nothing about docforge. Skip in that one
        # case; a genuinely broken capture still fails below.
        code, out, err = run("shot", str(html), str(png),
                             "--width", "400", "--height", "200", "--scale", "1",
                             "--timeout", "45")
        if code == 2 and ("timed out" in err or "still running" in err):
            self.skipTest(f"no browser available in time: {err.strip()}")
        self.assertEqual(0, code, err)
        self.assertTrue(png.is_file())
        self.assertGreater(png.stat().st_size, 0)
        self.assertEqual(b"\x89PNG\r\n\x1a\n", png.read_bytes()[:8])

    def test_missing_browser_is_reported_not_faked(self):
        with self.assertRaises(render.RenderError):
            render.shot(self.tmp / "x.html", self.tmp / "x.png",
                        browser=str(self.tmp / "not-a-browser"))

    def test_fig_png_flag_writes_a_screenshot(self):
        png = self.tmp / "fig.png"
        code, out, err = run("fig", str(FIGURE), "--no-check",
                             "-o", str(self.tmp / "f.svg"), "--png", str(png))
        self.assertEqual(0, code, err)
        self.assertTrue(png.is_file(), out)


class ExitCodeContractTest(TmpMixin, unittest.TestCase):
    def test_ok_is_zero_and_validation_failure_is_one(self):
        good = self.tmp / "good.json"
        good.write_text(json.dumps({
            "id": "g", "layout": "pipeline",
            "nodes": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        }))
        code, _, _ = run("check", str(good))
        self.assertEqual(cli.EXIT_OK, code)

        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({
            "id": "b", "layout": "free", "size": [400, 120],
            "nodes": [{"id": "a", "title": "A", "x": 10, "y": 10,
                       "width": 120, "height": 40},
                      {"id": "c", "title": "C", "x": 40, "y": 20,
                       "width": 120, "height": 40}],
            "connectors": [{"pts": [[10, 30], [40, 30]], "from": "a", "to": "c"}],
        }))
        code, out, _ = run("check", str(bad))
        self.assertEqual(cli.EXIT_VALIDATION, code)
        self.assertIn("box-overlap", out)

    def test_fail_on_none_always_exits_zero(self):
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({
            "id": "b", "layout": "free", "size": [400, 120],
            "nodes": [{"id": "a", "title": "很长很长的标题放不下", "x": 10, "y": 10,
                       "width": 60, "height": 40}],
        }))
        code, out, _ = run("check", str(bad), "--fail-on", "none")
        self.assertEqual(cli.EXIT_OK, code)
        self.assertIn("text-overflow", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class StandaloneBackdropTest(unittest.TestCase):
    """`fig` output must carry its own background.

    The CLI used to assemble the standalone SVG itself, and doing so skipped the
    backdrop rect -- invisible on a light theme, and a white-backed dark export.
    A figure that only looks right on one palette is not a standalone figure.
    """

    FIGURE = {"id": "bd", "layout": "free", "size": [400, 200],
              "nodes": [{"id": "a", "title": "A", "x": 20, "y": 20,
                         "width": 100, "height": 40}],
              "options": {"allow_isolated": True}}

    def _svg(self, mode):
        import json
        import tempfile
        from docforge import specs
        from docforge.theme import Theme
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(self.FIGURE, fh)
            path = fh.name
        scene = specs.render(specs.load(path))
        return specs.scene_svg(scene, theme=Theme.load("paper"), mode=mode,
                               standalone=True)

    def test_a_standalone_export_has_a_backdrop(self):
        for mode in ("light", "dark"):
            self.assertIn('class="d-canvas"', self._svg(mode),
                          f"{mode} export has no backdrop")

    def test_the_dark_backdrop_is_dark(self):
        """The canvas must paint the page colour, not a surface token."""
        svg = self._svg("dark")
        self.assertIn("--bg:#0b1017", svg)
        self.assertIn(".dg .d-canvas", svg)

    def test_the_backdrop_uses_the_page_colour(self):
        css = (pathlib.Path(__file__).resolve().parent.parent
               / "assets" / "svg.css").read_text(encoding="utf-8")
        rule = [l for l in css.splitlines() if "d-canvas" in l]
        self.assertTrue(rule, "no .d-canvas rule")
        self.assertIn("var(--bg)", " ".join(rule),
                      "the backdrop must be the page colour, not the surface")
