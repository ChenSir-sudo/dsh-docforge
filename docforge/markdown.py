"""Materials in, a :class:`Doc` model out.

Why a private dialect instead of a Markdown library: docforge ships as a
single-file generator whose only hard requirement is that a *hand-written*
material comes out as the same polished HTML every time. The material format is
therefore deliberately small -- five heading levels, paragraphs, language-tagged
fences, ``figure`` fences, GFM tables, two-level lists, quotes with alert tags,
and three inline forms. Every construct here exists because the reference
documents use it; anything else is left as plain text rather than guessed at.

The output is deterministic on purpose. No dictionary iteration, no timestamps,
no randomness: the same bytes in give the same bytes out, so a diff of the built
document only ever shows a change the author made.

The block model is also the seam between the two halves of the package. The
text side fills ``Doc.blocks`` with inline Markdown *source*; the document side
calls :func:`inline`, :func:`esc` and the figure layer reads :class:`FigureRef`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from .highlight import family, highlight

__all__ = [
    "MarkdownError",
    "Block",
    "Heading",
    "Paragraph",
    "CodeBlock",
    "FigureBlock",
    "Table",
    "ListBlock",
    "ListItem",
    "Quote",
    "Rule",
    "FigureRef",
    "TocEntry",
    "Doc",
    "parse",
    "parse_file",
    "code_html",
    "inline",
    "esc",
    "plain_text",
    "slugify",
]

ALERTS = ("NOTE", "KEY", "GOAL", "ACCEPT")
"""Quote alert tags the dialect understands. Anything else stays body text."""

_UNORDERED = "-*+"


class MarkdownError(ValueError):
    """A material could not be read as the restricted dialect."""


# --------------------------------------------------------------------------
# Inline layer
# --------------------------------------------------------------------------
def esc(value) -> str:
    """Escape ``& < > "`` so a value can never leave its HTML context."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_INLINE_RE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\[(?P<text>[^\]]*)\]\((?P<href>[^)\s]+)\)",
    re.S,
)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")


def inline(text: str) -> str:
    """Render the inline subset (``**bold**``, `` `code` ``, ``[text](url)``).

    Literal text is escaped as it is copied out, so escaping and formatting are
    one pass and cannot drift apart. A delimiter that never closes is left as
    the plain characters the author typed.
    """
    out: list = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        code = m.group("code")
        if code is not None:
            out.append(f"<code>{esc(code)}</code>")
        elif m.group("bold") is not None:
            out.append(f"<strong>{inline(m.group('bold'))}</strong>")
        else:
            out.append(
                f'<a href="{esc(m.group("href"))}">{inline(m.group("text"))}</a>'
            )
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def plain_text(text: str) -> str:
    """The readable text of an inline string, with markup removed.

    Used for slugs and for the table of contents, both of which want the words
    rather than the markup.
    """
    return _LINK_RE.sub(r"\1", text).replace("**", "").replace("`", "").strip()


_SLUG_DROP = re.compile(r"[^\w\-]+", re.UNICODE)
_SLUG_DASH = re.compile(r"-{2,}")


def slugify(text: str) -> str:
    """A stable anchor id for a title: lowercase, punctuation to a single dash.

    CJK and other word characters survive, so ``总体架构：核心`` becomes
    ``总体架构-核心`` and stays readable in the URL bar. Two titles that differ
    only in punctuation collide here; :func:`parse` de-duplicates them.
    """
    slug = _SLUG_DROP.sub("-", plain_text(text).lower().replace(" ", "-"))
    slug = _SLUG_DASH.sub("-", slug).strip("-")
    return slug or "section"


# --------------------------------------------------------------------------
# Block model
# --------------------------------------------------------------------------
@dataclass
class Block:
    """Base of the block hierarchy.

    ``kind`` is a class constant rather than a field: it labels the node for
    tests and JSON dumps without joining every constructor's argument list.
    """

    kind: ClassVar[str] = "block"


@dataclass
class Heading(Block):
    """``#`` through ``#####``. ``title`` is inline Markdown source."""

    kind: ClassVar[str] = "heading"
    level: int = 1
    id: str = ""
    title: str = ""


@dataclass
class Paragraph(Block):
    """A run of text; ``text`` is inline Markdown source, newline-joined."""

    kind: ClassVar[str] = "paragraph"
    text: str = ""


@dataclass
class CodeBlock(Block):
    """A fenced block. ``lang`` is the fence's info word, or ``""``."""

    kind: ClassVar[str] = "code"
    lang: str = ""
    code: str = ""


@dataclass
class Table(Block):
    """A GFM table. Cells are inline Markdown source, one list per row."""

    kind: ClassVar[str] = "table"
    head: list = field(default_factory=list)
    rows: list = field(default_factory=list)


@dataclass
class FigureBlock(Block):
    """A ``figure`` fence in the block stream, carrying its :class:`FigureRef`."""

    kind: ClassVar[str] = "figure"
    ref: "FigureRef | None" = None


@dataclass
class ListItem:
    """One bullet, plus the list nested directly under it (one extra level)."""

    text: str = ""
    sub: "ListBlock | None" = None


@dataclass
class ListBlock(Block):
    """A list. ``ordered`` follows the first marker seen in the block."""

    kind: ClassVar[str] = "list"
    ordered: bool = False
    items: list = field(default_factory=list)


@dataclass
class Quote(Block):
    """A ``>`` block. ``alert`` is one of :data:`ALERTS`, or ``""``."""

    kind: ClassVar[str] = "quote"
    blocks: list = field(default_factory=list)
    alert: str = ""


@dataclass
class Rule(Block):
    """A thematic break: ``---``, ``***`` or ``___`` on its own line."""

    kind: ClassVar[str] = "rule"


@dataclass
class FigureRef:
    """A ``figure`` fence, resolved as far as text alone can resolve it.

    ``spec_or_path`` is the inline JSON spec when the fence body was JSON, the
    path (without the ``@``) when the body was ``@path``, and ``""`` when the
    body was empty -- meaning "the caller looks the spec up by :attr:`id`".
    Use :attr:`source` or :attr:`spec` instead of sniffing that string.
    """

    id: str
    number: int = 0
    kind: str = ""
    name: str = ""
    spec_or_path: str = ""
    caption: str = ""

    @property
    def source(self) -> str:
        """``"spec"`` (inline JSON), ``"path"`` (``@file``) or ``"id"``."""
        body = self.spec_or_path.strip()
        if not body:
            return "id"
        return "spec" if body.startswith("{") else "path"

    @property
    def spec(self):
        """The parsed inline spec, or ``None`` for a path/id reference."""
        if self.source != "spec":
            return None
        return json.loads(self.spec_or_path)


@dataclass
class TocEntry:
    """One heading, in document order. ``title`` is plain text, not markup."""

    level: int
    id: str
    title: str


@dataclass
class Doc:
    """A parsed material: metadata, blocks, figure references and the outline."""

    meta: dict = field(default_factory=dict)
    blocks: list = field(default_factory=list)
    figures: list = field(default_factory=list)
    toc: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Front matter
# --------------------------------------------------------------------------
def _scalar(value: str):
    """Coerce a front-matter scalar. Booleans are the only magic."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    return value


def _parse_front_matter(lines: list) -> dict:
    meta: dict = {}
    key = None
    for lineno, raw in enumerate(lines, start=2):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line[0].isspace():
            if key is None or not line.lstrip().startswith("- "):
                raise MarkdownError(
                    f"front matter line {lineno}: expected a nested '- item'"
                )
            if not isinstance(meta[key], list):
                if meta[key] != "":
                    raise MarkdownError(
                        f"front matter line {lineno}: {key!r} already has a value"
                    )
                meta[key] = []
            meta[key].append(_scalar(line.lstrip()[2:].strip()))
            continue
        name, sep, value = line.partition(":")
        if not sep or not name.strip():
            raise MarkdownError(
                f"front matter line {lineno}: expected 'key: value', got {line!r}"
            )
        key = name.strip()
        value = value.strip()
        meta[key] = _scalar(value) if value else []
    return {name: ("" if isinstance(v, list) and not v else v) for name, v in meta.items()}


def _split_front_matter(text: str):
    """Return ``(meta, body_lines)``. An unclosed ``---`` stays in the body."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, lines
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return _parse_front_matter(lines[1:i]), lines[i + 1:]
    return {}, lines


# --------------------------------------------------------------------------
# Block layer
# --------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,5})(?:\s+(.*))?$")
_RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_TASK_RE = re.compile(r"^\[[ xX]\]\s*")

_LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_ALERT_RE = re.compile(r"^\[!([A-Za-z]+)\]$")
_SEP_CELL_RE = re.compile(r"^:?-+:?$")
_CLOSING_HASHES_RE = re.compile(r"\s+#+$")


def _fence_open(line: str):
    """``(n_backticks, info)`` when the line opens a fence, else ``None``."""
    stripped = line.strip()
    if not stripped.startswith("```"):
        return None
    n = len(stripped) - len(stripped.lstrip("`"))
    return n, stripped[n:].strip()


def _split_row(line: str) -> list:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _is_sep_row(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(_SEP_CELL_RE.match(cell) for cell in cells)


def _is_table_start(lines: list, i: int) -> bool:
    """A header row has to be followed by a matching ``---`` delimiter row."""
    if "|" not in lines[i] or i + 1 >= len(lines):
        return False
    head = _split_row(lines[i])
    sep = _split_row(lines[i + 1])
    return len(head) > 1 and len(head) == len(sep) and _is_sep_row(lines[i + 1])


class _Parser:
    """Mutable state for one pass: figure numbering, slugs, outline."""

    def __init__(self) -> None:
        self.figures: list = []
        self.toc: list = []
        # ``toc`` is reserved: the document chrome anchors the outline there, so
        # a heading called "TOC" must not steal the id.
        self._slugs: dict = {"toc": 1}

    # -------------------------------------------------------------- helpers
    def _slug(self, title: str) -> str:
        base = slugify(title)
        seen = self._slugs.get(base, 0) + 1
        self._slugs[base] = seen
        return base if seen == 1 else f"{base}-{seen}"

    @staticmethod
    def _starts_block(lines: list, i: int) -> bool:
        line = lines[i]
        stripped = line.strip()
        if _fence_open(line) or _HEADING_RE.match(stripped) or _RULE_RE.match(stripped):
            return True
        if stripped.startswith(">") or _LIST_RE.match(line):
            return True
        return _is_table_start(lines, i)

    # --------------------------------------------------------------- blocks
    def blocks(self, lines: list) -> list:
        out: list = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue

            fence = _fence_open(line)
            if fence is not None:
                block, i = self._fence(lines, i, fence)
                out.append(block)
                continue

            heading = _HEADING_RE.match(stripped)
            if heading:
                out.append(self._heading(heading))
                i += 1
                continue

            if _RULE_RE.match(stripped):
                out.append(Rule())
                i += 1
                continue

            if _LIST_RE.match(line):
                block, i = self._list(lines, i)
                out.append(block)
                continue

            if stripped.startswith(">"):
                block, i = self._quote(lines, i)
                out.append(block)
                continue

            if _is_table_start(lines, i):
                block, i = self._table(lines, i)
                out.append(block)
                continue

            para = [stripped]
            i += 1
            while i < n and lines[i].strip() and not self._starts_block(lines, i):
                para.append(lines[i].strip())
                i += 1
            out.append(Paragraph(text="\n".join(para)))
        return out

    def _heading(self, match) -> Heading:
        level = len(match.group(1))
        title = _CLOSING_HASHES_RE.sub("", (match.group(2) or "").strip()).strip()
        sid = self._slug(title)
        self.toc.append(TocEntry(level=level, id=sid, title=plain_text(title)))
        return Heading(level=level, id=sid, title=title)

    def _fence(self, lines: list, i: int, fence) -> tuple:
        width, info = fence
        close = re.compile(r"^`{%d,}$" % width)
        body_lines: list = []
        j = i + 1
        while j < len(lines) and not close.match(lines[j].strip()):
            body_lines.append(lines[j])
            j += 1
        if j >= len(lines):
            raise MarkdownError(
                f"unclosed ``` fence opened on line {i + 1} of the material"
            )
        body = "\n".join(body_lines)
        if info == "figure" or info.startswith("figure "):
            return self._figure(info, body, i + 1), j + 1
        return CodeBlock(lang=info.split()[0] if info else "", code=body), j + 1

    def _figure(self, info: str, body: str, lineno: int) -> FigureBlock:
        parts = info.split(None, 1)
        fid = parts[1].strip() if len(parts) > 1 else ""
        if not fid:
            raise MarkdownError(
                f"figure fence on line {lineno}: expected ```figure <id>"
            )
        if fid in {ref.id for ref in self.figures}:
            raise MarkdownError(f"figure {fid!r} is declared twice")
        body = body.strip()
        ref = FigureRef(id=fid, number=len(self.figures) + 1)
        if not body:
            pass
        elif body.startswith("@"):
            ref.spec_or_path = body[1:].strip()
            if not ref.spec_or_path:
                raise MarkdownError(f"figure {fid!r}: '@' names no file")
        elif body.startswith("{"):
            try:
                spec = json.loads(body)
            except json.JSONDecodeError as exc:
                raise MarkdownError(
                    f"figure {fid!r}: body starts with '{{' but is not JSON: {exc}"
                ) from exc
            if not isinstance(spec, dict):
                raise MarkdownError(f"figure {fid!r}: spec must be a JSON object")
            ref.spec_or_path = body
            ref.kind = str(spec.get("kind") or "")
            ref.name = str(spec.get("title") or "")
            ref.caption = str(spec.get("caption") or "")
        else:
            raise MarkdownError(
                f"figure {fid!r}: body must be an inline JSON spec, '@path', or empty"
            )
        self.figures.append(ref)
        return FigureBlock(ref=ref)

    def _table(self, lines: list, i: int) -> tuple:
        head = _split_row(lines[i])
        rows: list = []
        i += 2
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            row = _split_row(lines[i])
            row = (row + [""] * len(head))[: len(head)]
            rows.append(row)
            i += 1
        return Table(head=head, rows=rows), i

    def _list(self, lines: list, i: int) -> tuple:
        n = len(lines)
        match = _LIST_RE.match(lines[i])
        base = len(match.group(1).expandtabs(4))
        top = ListBlock(ordered=match.group(2)[0].isdigit())
        sub = None
        while i < n:
            item = _LIST_RE.match(lines[i])
            if item:
                indent = len(item.group(1).expandtabs(4))
                marker, text = item.group(2), item.group(3).strip()
                # `- [ ] done?` is a GFM task list. The brackets are syntax; a
                # reader should never see them as literal text.
                text = _TASK_RE.sub("", text, count=1).strip()
                if indent <= base:
                    if marker[0].isdigit() != top.ordered:
                        break  # a different list starts here; let the caller see it
                    top.items.append(ListItem(text=text))
                    sub = None
                else:
                    if not top.items:
                        top.items.append(ListItem())
                    if sub is None:
                        sub = ListBlock(ordered=marker[0].isdigit())
                        top.items[-1].sub = sub
                    sub.items.append(ListItem(text=text))
                i += 1
                continue
            if not lines[i].strip():
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and _LIST_RE.match(lines[j]):
                    i = j
                    continue
                break
            if lines[i][0].isspace() and top.items:
                target = sub.items[-1] if sub is not None and sub.items else top.items[-1]
                target.text += "\n" + lines[i].strip()
                i += 1
                continue
            break
        return top, i

    def _quote(self, lines: list, i: int) -> tuple:
        inner: list = []
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            rest = lines[i].lstrip()[1:]
            inner.append(rest[1:] if rest.startswith(" ") else rest)
            i += 1
        alert = ""
        if inner:
            marker = _ALERT_RE.match(inner[0].strip())
            if marker and marker.group(1).upper() in ALERTS:
                alert = marker.group(1).upper()
                inner = inner[1:]
        return Quote(blocks=self.blocks(inner), alert=alert), i


# --------------------------------------------------------------------------
# Fence rendering
# --------------------------------------------------------------------------
def code_html(block: CodeBlock) -> str:
    """Render a fenced :class:`CodeBlock` as highlighted, chromed HTML.

    This is the single seam a fence crosses on its way out: it is what turns the
    parsed ``lang`` plus the fence body into the markup ``assets/code.css``
    styles. The three rules it exists to keep are that *every* fence gets the
    chrome -- an untagged, an empty and an unknown-language block included --
    that the body is highlighted with the language tag it was written with or
    left as escaped plain text, never dropped, and that the accent family is a
    pure function of that tag, so a shell transcript and a JSON payload are
    distinguishable before a single token is read.
    """
    lang = block.lang or "text"
    cls = f' class="lang-{esc(block.lang)}"' if block.lang else ""
    return (
        f'<div class="code-block fam-{family(lang)}" data-lang="{esc(lang)}">'
        # The badge is the copy control: the language tag is already the thing a
        # reader aims at, so it earns the click instead of a second button.
        f'<button class="code-copy" type="button" aria-label="复制代码"'
        f' title="复制代码">{esc(lang)}</button>'
        f"<pre><code{cls}>{highlight(block.code, lang)}</code></pre>"
        "</div>\n"
    )


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------
def parse(text: str) -> Doc:
    """Parse a material. Pure: the same text always gives the same :class:`Doc`."""
    meta, lines = _split_front_matter(text)
    parser = _Parser()
    blocks = parser.blocks(lines)
    return Doc(meta=meta, blocks=blocks, figures=parser.figures, toc=parser.toc)


def parse_file(path) -> Doc:
    """Read a material from disk (UTF-8, BOM tolerated) and parse it."""
    return parse(Path(path).read_text(encoding="utf-8-sig"))
