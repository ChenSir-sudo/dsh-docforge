"""Documentation-sync tests.

A skill is only reusable if its instructions are true. These tests fail the
build when the code and the documents drift apart: a new layout engine with no
description, a new validation code nobody documented, a CLI command missing from
the reference, or a directory listing that no longer matches reality.

They are cheap, and they are the reason the docs can be trusted six months from
now.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from docforge import ROOT, TEMPLATES, layouts
from docforge import validate as V
from docforge.cli import LAYOUT_DOC

SKILL = (ROOT / "SKILL.md").read_text()
README = (ROOT / "README.md").read_text()
INTERFACE = (ROOT / "INTERFACE.md").read_text()
ALL_DOCS = SKILL + README + INTERFACE


class LayoutsAreDocumentedTest(unittest.TestCase):
    def test_every_engine_has_a_description(self):
        for name in layouts.LAYOUTS:
            self.assertIn(name, LAYOUT_DOC, f"{name} has no LAYOUT_DOC entry")
            self.assertTrue(LAYOUT_DOC[name].strip(), f"{name}'s description is empty")

    def test_skill_md_lists_every_engine(self):
        for name in layouts.LAYOUTS:
            self.assertRegex(
                SKILL, rf"`{re.escape(name)}`",
                f"SKILL.md never mentions the {name!r} layout",
            )

    def test_no_description_for_an_engine_that_does_not_exist(self):
        for name in LAYOUT_DOC:
            self.assertIn(name, layouts.LAYOUTS, f"LAYOUT_DOC documents ghost {name!r}")


class DocumentedExamplesAreRealTest(unittest.TestCase):
    """Every layout name used in a doc example must be a real engine."""

    def test_layouts_named_in_examples_exist(self):
        from docforge import layouts as L
        named = set()
        for text in (SKILL, README, INTERFACE):
            named |= set(re.findall(r'"layout"\s*:\s*"([a-z]+)"', text))
            named |= set(re.findall(r"^layout:\s*([a-z]+)", text, re.M))
        self.assertTrue(named, "no layout examples found in the docs at all")
        self.assertEqual(set(), named - set(L.LAYOUTS),
                         f"docs name engines that do not exist: "
                         f"{sorted(named - set(L.LAYOUTS))}")

    def test_cli_flags_named_in_the_contract_exist(self):
        from docforge.cli import build_parser
        parser = build_parser()
        subs = None
        for action in parser._actions:
            if hasattr(action, "choices") and isinstance(action.choices, dict):
                subs = action.choices
        for name, sub in subs.items():
            declared = set(re.findall(rf"docforge {name}\s+.*?(?=\ndocforge|\Z)",
                                      INTERFACE, re.S))
            flags_in_doc = set(re.findall(r"(--[a-z][a-z-]+)", " ".join(declared)))
            real = {o for a in sub._actions for o in a.option_strings}
            real |= {f"--{a.dest.replace('_', '-')}"
                     for a in sub._actions if not a.option_strings}
            bogus = {f for f in flags_in_doc if f not in real}
            self.assertEqual(set(), bogus,
                             f"INTERFACE.md invents flags for `{name}`: {sorted(bogus)}")


class CodesAreDocumentedTest(unittest.TestCase):
    def test_every_validation_code_appears_in_skill_md(self):
        missing = [c for c in V.ALL_CODES if f"`{c}`" not in SKILL]
        self.assertEqual([], missing,
                         f"these codes are emitted but undocumented in SKILL.md: {missing}")

    def test_every_code_has_a_severity(self):
        for code in V.ERROR_CODES:
            self.assertNotIn(code, V.WARNING_CODES)
        self.assertEqual(len(V.ALL_CODES), len(set(V.ALL_CODES)), "duplicate code")

    def test_interface_md_lists_the_code_tables(self):
        for code in ("text-overflow", "edge-through", "label-collision",
                     "figure-render-failed"):
            self.assertIn(code, INTERFACE)

    def test_skill_info_reports_the_same_codes(self):
        from docforge import cli
        self.assertEqual(list(V.ERROR_CODES), list(cli.V.ERROR_CODES))


class CommandsAreDocumentedTest(unittest.TestCase):
    def setUp(self):
        self.commands = sorted(cli_subparsers())

    def test_docs_document_every_command(self):
        for name in self.commands:
            with self.subTest(command=name, doc="SKILL.md"):
                self.assertIn(name, SKILL,
                              f"SKILL.md does not document `docforge {name}`")
            with self.subTest(command=name, doc="README.md"):
                self.assertIn(name, README,
                              f"README.md does not document `docforge {name}`")

    def test_skill_info_advertises_every_command(self):
        from docforge import cli
        advertised = set(cli_skill_info_commands())
        self.assertEqual(set(self.commands), advertised,
                         "skill-info and the parser disagree about the commands")


def cli_subparsers():
    """The registered sub-command names, straight from the parser."""
    from docforge.cli import build_parser
    for action in build_parser()._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            return list(action.choices)
    return []


def cli_skill_info_commands():
    from docforge import cli
    import io
    import json
    from contextlib import redirect_stdout
    out = io.StringIO()
    with redirect_stdout(out):
        cli.main(["skill-info", "--json"])
    return json.loads(out.getvalue())["commands"].keys()


class TreeMatchesRealityTest(unittest.TestCase):
    """README's layout listing must match the files on disk."""

    def test_every_module_is_listed(self):
        pkg = ROOT / "docforge"
        for path in sorted(pkg.glob("*.py")):
            if path.name in ("__init__.py", "__main__.py"):
                continue
            self.assertIn(path.name, README,
                          f"{path.name} is missing from the README tree")

    def test_every_top_level_dir_is_listed(self):
        for name in ("assets", "themes", "templates", "examples", "tests", "tools"):
            self.assertTrue((ROOT / name).is_dir(), f"{name}/ is missing")
            self.assertIn(name, README, f"{name}/ is missing from the README tree")

    def test_every_template_is_advertised_and_scaffoldable(self):
        """`--template` takes any folder under templates/, and the help lists them."""
        from docforge.cli import build_parser
        help_text = None
        for action in build_parser()._actions:
            if hasattr(action, "choices") and isinstance(action.choices, dict):
                for sub in action.choices.values():
                    for a in getattr(sub, "_actions", []):
                        if a.dest == "template":
                            help_text = a.help or ""
        self.assertIsNotNone(help_text, "the init command lost its --template option")
        for folder in sorted(p for p in TEMPLATES.iterdir() if p.is_dir()):
            with self.subTest(template=folder.name):
                self.assertIn(folder.name, help_text,
                              f"{folder.name}/ is not offered in --help")
                self.assertTrue((folder / "material.md").is_file())

    def test_every_template_has_a_buildable_material(self):
        for folder in sorted(TEMPLATES.iterdir()):
            if folder.is_dir():
                with self.subTest(template=folder.name):
                    self.assertTrue((folder / "material.md").is_file())


class InterfaceMatchesCodeTest(unittest.TestCase):
    def test_public_functions_are_named_in_the_contract(self):
        names = ["check_scene", "check_document", "should_fail", "summarize",
                 "format_text", "load", "normalize", "render", "render_svg",
                 "parse", "parse_file", "document_css", "svg_css", "Theme"]
        for name in names:
            self.assertIn(name, INTERFACE,
                          f"INTERFACE.md does not mention {name}")

    def test_every_theme_token_listed_in_the_contract_round_trips(self):
        from docforge.theme import Theme
        for theme in Theme.available():
            self.assertEqual([], theme.missing(),
                             f"theme {theme.name} lost token parity")


class SkillFrontmatterTest(unittest.TestCase):
    def test_required_keys_are_present(self):
        m = re.match(r"^---\n(.*?)\n---\n", SKILL, re.S)
        self.assertIsNotNone(m, "SKILL.md must start with YAML frontmatter")
        keys = {l.split(":", 1)[0] for l in m.group(1).splitlines()
                if l and not l[0].isspace()}
        self.assertIn("name", keys)
        self.assertIn("description", keys)
        self.assertLessEqual(keys, {"name", "description", "whenToUse", "metadata",
                                    "disable-model-invocation", "user-invocable"})

    def test_frontmatter_name_matches_the_package(self):
        m = re.match(r"^---\n(.*?)\n---\n", SKILL, re.S)
        self.assertIn("name: docforge", m.group(1))

    def test_the_description_says_when_to_use_it(self):
        m = re.match(r"^---\n(.*?)\n---\n", SKILL, re.S)
        fm = m.group(1)
        desc = next(l for l in fm.splitlines() if l.startswith("description:"))
        self.assertGreater(len(desc), 80, "the description is too thin to route on")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
