"""docforge — materials in, a polished single-file HTML document out.

The API is the modules, not a re-export shim:

    docforge.specs       material + figure specs -> rendered SVG and HTML
    docforge.validate    geometry and document findings
    docforge.theme       token sets and stylesheet assembly
    docforge.cli         the command line, one function per subcommand

Import what you need from those directly; ``docforge.cli.main`` is the entry
point for shells and other agents.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "1.0.0"
SCHEMA_VERSION = 1

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
THEMES = ROOT / "themes"
TEMPLATES = ROOT / "templates"

__all__ = ["__version__", "SCHEMA_VERSION", "ROOT", "ASSETS", "THEMES", "TEMPLATES"]
