"""Themes: colour token sets, kept as data so they can be swapped or shipped.

A theme is a JSON file with a ``light`` and a ``dark`` map of CSS custom
properties. The structural stylesheet (``assets/base.css``) never contains a
colour, so changing a theme changes the whole document *and* every inline SVG
inside it.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import ASSETS, THEMES


class ThemeError(Exception):
    pass


class Theme:
    """A named pair of token maps."""

    def __init__(self, name, label, light, dark, description=""):
        self.name = name
        self.label = label
        self.light = dict(light)
        self.dark = dict(dark)
        self.description = description

    # ------------------------------------------------------------ factories
    @classmethod
    def load(cls, ref: str = "paper") -> "Theme":
        """Load a theme by name (from ``themes/``) or by file path."""
        path = Path(ref)
        if not path.exists():
            if not ref.endswith(".json"):
                path = THEMES / f"{ref}.json"
            else:
                path = THEMES / Path(ref).name
        if not path.exists():
            available = ", ".join(t.name for t in cls.available())
            raise ThemeError(f"unknown theme {ref!r} (available: {available})")
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            # A malformed theme is a bad *input*, not a broken program: it has
            # to reach the caller as the documented usage/IO failure.
            raise ThemeError(f"theme {path.name} is not readable JSON: {exc}") from exc
        for key in ("light", "dark"):
            if key not in data:
                raise ThemeError(f"theme {path.name} is missing the {key!r} map")
        return cls(
            name=data.get("name", path.stem),
            label=data.get("label", path.stem),
            description=data.get("description", ""),
            light=data["light"],
            dark=data["dark"],
        )

    @classmethod
    def available(cls) -> list:
        if not THEMES.is_dir():
            return []
        out = []
        for p in sorted(THEMES.glob("*.json")):
            try:
                out.append(cls.load(str(p)))
            except (ThemeError, json.JSONDecodeError):
                continue
        return out

    # ------------------------------------------------------------- accessors
    def tokens(self, mode: str = "light") -> dict:
        return self.light if mode != "dark" else self.dark

    def palette(self, mode: str = "light") -> dict:
        """Token name without the leading ``--``, as SVG/standalone needs it."""
        return {k.lstrip("-"): v for k, v in self.tokens(mode).items()}

    def css_vars(self, mode: str = "light", selector=None) -> str:
        if selector is None:
            selector = ":root" if mode != "dark" else '[data-theme="dark"]'
        body = "".join(f"{k}:{v};" for k, v in self.tokens(mode).items())
        return f"{selector}{{{body}}}"

    def css(self) -> str:
        """Both modes, ready to drop into a ``<style>`` block."""
        return self.css_vars("light") + self.css_vars("dark") + "\n"

    def svg_css(self) -> str:
        """The SVG-only rules, for embedding in a standalone ``.svg`` file."""
        return _read("svg.css")

    def missing(self) -> list:
        """Token names present in one mode but not the other."""
        return sorted(set(self.light) ^ set(self.dark))


# --------------------------------------------------------------------------
# Structural CSS
# --------------------------------------------------------------------------
_BASE_CACHE: dict = {}


def base_css() -> str:
    return _read("base.css")


def svg_css() -> str:
    return _read("svg.css")


def code_css() -> str:
    """Syntax-highlighting and code-block chrome.

    Optional on purpose: a bundle without ``assets/code.css`` still produces a
    working document, it just gets the plain code styling.
    """
    path = ASSETS / "code.css"
    return path.read_text() if path.is_file() else ""


def _read(name: str) -> str:
    if name not in _BASE_CACHE:
        path = ASSETS / name
        if not path.is_file():
            raise ThemeError(f"missing asset: {path}")
        _BASE_CACHE[name] = path.read_text()
    return _BASE_CACHE[name]


def document_css(theme: Theme) -> str:
    """The full stylesheet for a document: tokens, figures, structure, code.

    ``svg_css()`` is in here on purpose. The figure rules used to be duplicated
    into ``base.css`` so an embedded diagram and an exported ``.svg`` each had
    their own copy -- which meant every new figure role had to be added twice,
    and missing one left the class silently unstyled in the page while working
    in the export. One sheet, included by both paths.
    """
    return theme.css() + svg_css() + base_css() + code_css()
