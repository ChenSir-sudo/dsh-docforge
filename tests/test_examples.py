"""Shipped examples must stay faithful to what they claim to be.

`docforge check` validates figure geometry and document structure. It cannot
tell whether the prose was transcribed faithfully, whether a code block lost its
line breaks, or whether a section was quietly dropped. For the flagship example
that matters: it exists to be a reference.

So each example carries a `manifest.json` recording the structure it was ported
from, and this test proves the material still matches. A future edit that
flattens a code block or drops a table fails here rather than shipping.
"""

from __future__ import annotations

import json
import re
import pathlib
import unittest

from docforge import specs
from docforge import validate as V
from pathlib import Path

from docforge import ROOT

EXAMPLES = ROOT / "examples"


def count_material(text: str) -> dict:
    fences = re.findall(r"^```([A-Za-z][\w-]*)", text, re.M)
    code = [f for f in fences if f.lower() != "figure"]
    return {
        "h1": len(re.findall(r"^# ", text, re.M)),
        "h2": len(re.findall(r"^## ", text, re.M)),
        "h3": len(re.findall(r"^### ", text, re.M)),
        "h4": len(re.findall(r"^#### ", text, re.M)),
        "figures": fences.count("figure"),
        "tables": len(re.findall(r"^\|[\s:|-]+\|$", text, re.M)),
        "code_blocks": len(code),
    }


class ExampleManifestTest(unittest.TestCase):
    def manifests(self):
        found = []
        for material in sorted(EXAMPLES.glob("*/material.md")):
            manifest = material.parent / "manifest.json"
            if manifest.is_file():
                found.append((material, json.loads(manifest.read_text())))
        return found

    def test_every_shipped_example_declares_its_shape(self):
        materials = sorted(EXAMPLES.glob("*/material.md"))
        self.assertTrue(materials, "no example materials found")
        for material in materials:
            with self.subTest(example=material.parent.name):
                self.assertTrue((material.parent / "manifest.json").is_file(),
                                f"{material.parent.name} has no manifest.json")

    def test_material_matches_its_manifest(self):
        for material, manifest in self.manifests():
            counted = count_material(material.read_text())
            for key, want in manifest["expected"].items():
                if key == "code_languages":
                    continue
                with self.subTest(example=material.parent.name, field=key):
                    self.assertEqual(
                        want, counted[key],
                        f"{material.parent.name}: {key} is {counted[key]}, "
                        f"manifest says {want}",
                    )

    def test_code_blocks_keep_their_language(self):
        for material, manifest in self.manifests():
            want = manifest["expected"].get("code_languages") or {}
            if not want:
                continue
            from collections import Counter
            have = Counter(f.lower() for f in
                           re.findall(r"^```([A-Za-z][\w-]*)", material.read_text(), re.M)
                           if f.lower() != "figure")
            with self.subTest(example=material.parent.name):
                self.assertEqual({k.lower(): v for k, v in want.items()}, dict(have),
                                 f"{material.parent.name}: code block languages drifted")

    def test_no_code_was_flattened_into_a_paragraph(self):
        """A signature that appears mid-sentence means a fence was lost."""
        markers = ("class AgentState(TypedDict):",
                   "def route_by_intent(state):",
                   "def should_refine(state):",
                   "workflow = StateGraph(AgentState)")
        for material, _ in self.manifests():
            lines = material.read_text().splitlines()
            for marker in markers:
                hits = [l for l in lines if marker in l]
                for line in hits:
                    with self.subTest(example=material.parent.name, marker=marker):
                        self.assertEqual(
                            marker, line.strip(),
                            f"{material.parent.name}: {marker!r} is embedded in a "
                            f"paragraph — a code fence was lost",
                        )

    def test_code_blocks_are_not_empty(self):
        for material, _ in self.manifests():
            body = material.read_text()
            for lang, content in re.findall(
                    r"^```([A-Za-z][\w-]*)\n(.*?)^```$", body, re.M | re.S):
                if lang.lower() == "figure":
                    continue
                with self.subTest(example=material.parent.name, lang=lang):
                    self.assertTrue(content.strip(), "empty code block")


class ShippedExamplesAreValidTest(unittest.TestCase):
    def test_every_example_material_checks_clean(self):
        from docforge import markdown, specs
        from docforge import validate as V
        for material in sorted(EXAMPLES.glob("*/material.md")):
            with self.subTest(example=material.parent.name):
                doc = markdown.parse_file(material)
                findings = []
                for ref in doc.figures:
                    spec = specs.load(material.parent / ref.spec_or_path)
                    findings += V.check_scene(specs.render(spec))
                errors = [str(f) for f in findings if f.severity == V.ERROR]
                self.assertEqual([], errors)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class NestedFigureTest(unittest.TestCase):
    """The shipped nesting example must stay valid, and stay nested."""

    ROOT = pathlib.Path(__file__).resolve().parent.parent

    def test_it_checks_clean(self):
        spec = specs.load(self.ROOT / "examples" / "nested-figure.json")
        self.assertEqual([], V.check_scene(specs.render(spec)))

    def test_it_actually_nests_two_figures(self):
        spec = specs.load(self.ROOT / "examples" / "nested-figure.json")
        sc = specs.render(spec)
        self.assertEqual(2, len(sc.children),
                         "the example exists to demonstrate nesting")

    def test_the_shipped_markdown_documents_it(self):
        skill = (self.ROOT / "SKILL.md").read_text()
        self.assertIn("sub_spec", skill)
