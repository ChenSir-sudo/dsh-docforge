"""Document assembly: a :class:`~docforge.markdown.Doc` plus rendered figures
become one self-contained HTML file.

Why this is a separate layer from :mod:`docforge.markdown`: the figure layer
runs *between* the two. ``render`` is handed a mapping of figure id to
already-rendered SVG markup and never imports a layout, so a document can be
assembled from figures produced by any engine -- or from no figures at all,
which is exactly what the missing-figure placeholder is for.

Why the output is deterministic: a built document is meant to be committed and
diffed. Nothing here reads the clock, iterates a set, or depends on dictionary
insertion order that the caller did not control. The same ``Doc`` and the same
figure strings always produce the same bytes.

The class vocabulary comes from ``assets/base.css``; this module owns the
*shape* of the document (topbar, sidebar, hero, sections, figure cards,
footer) and the numbering ladder, and nothing else.

The outline lives in ``<aside class="sidebar" id="sidebar">`` beside
``<main class="content">`` inside one ``.shell`` grid. ``<html data-nav>`` --
``"open"`` unless the reader collapsed it -- is the *only* piece of state the
layout reads: the wide grid collapses the first column to zero, and the narrow
layout turns the same element into an off-canvas drawer. The toggle button and
the stored key (``dsh-doc-nav``) are the only way that attribute changes, so
the two layouts can never disagree about whether the outline is showing.
"""

from __future__ import annotations

import re

from . import validate as V
from .markdown import (
    Block,
    CodeBlock,
    Doc,
    FigureBlock,
    FigureRef,
    Heading,
    ListBlock,
    ListItem,
    Paragraph,
    Quote,
    Rule,
    Table,
    code_html,
    esc,
    inline,
)
from .theme import Theme, document_css

__all__ = ["DocumentError", "render", "cn_number"]

#: Ladder levels: h1 -> h2 -> h3 -> h4 -> h5.
MAX_LEVEL = 5

_CN_DIGITS = "零一二三四五六七八九"

#: Findings from :mod:`docforge.validate` that mean *this renderer* is broken.
#: Author-level findings (a figure with no SVG) are reported through the
#: placeholder and are deliberately not fatal.
_STRUCTURAL_CODES = ("duplicate-id", "dangling-anchor", "tag-imbalance")

_SCRIPT = """<script>
(function () {
  var KEY = 'dsh-doc-theme';
  var root = document.documentElement;
  var btn = document.getElementById('themeBtn');
  function apply(theme) {
    root.setAttribute('data-theme', theme);
    if (btn) { btn.textContent = theme === 'dark' ? '浅色' : '深色'; }
  }
  var saved = null;
  try { saved = window.localStorage.getItem(KEY); } catch (e) { saved = null; }
  apply(saved || root.getAttribute('data-theme') || 'light');
  if (btn) {
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      apply(next);
      try { window.localStorage.setItem(KEY, next); } catch (e) {}
    });
  }
})();
</script>"""

#: The outline's opening state, decided *before* the first paint -- otherwise a
#: reopened document flashes the wrong layout and drops it. The stored choice
#: wins in both directions, read exactly the way the theme script reads its own
#: key; a store that is missing or inaccessible (``file://`` under some
#: policies) falls through instead of failing. With no stored choice the
#: viewport decides: beside the article on a wide screen, but *over* it on a
#: narrow one, so a first-time narrow visitor gets the document, not a drawer.
_NAV_BOOT = """<script>
(function () {
  var NARROW = '(max-width: 1080px)';
  var saved = null;
  try { saved = window.localStorage.getItem('dsh-doc-nav'); } catch (e) { saved = null; }
  if (saved === 'open' || saved === 'closed') {
    document.documentElement.setAttribute('data-nav', saved);
  } else if (window.matchMedia && window.matchMedia(NARROW).matches) {
    document.documentElement.setAttribute('data-nav', 'closed');
  }
})();
</script>"""

#: The outline toggle itself. Persisting the choice mirrors the theme toggle;
#: the backdrop and Escape are the two ways out of the narrow-screen drawer.
_NAV_SCRIPT = r"""<script>
(function () {
  var KEY = 'dsh-doc-nav';
  var NARROW = '(max-width: 1080px)';
  var root = document.documentElement;
  var btn = document.getElementById('navBtn');
  var scrim = document.getElementById('scrim');
  function isOpen() { return root.getAttribute('data-nav') !== 'closed'; }
  function apply(nav) {
    root.setAttribute('data-nav', nav);
    if (btn) {
      // The chevron's flip is pure CSS ([data-nav]); only the words change here.
      var open = nav === 'open';
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      var label = open ? '\u6536\u8d77\u76ee\u5f55' : '\u5c55\u5f00\u76ee\u5f55';
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', label);
    }
  }
  function remember(nav) {
    try { window.localStorage.setItem(KEY, nav); } catch (e) {}
  }
  function close() { apply('closed'); remember('closed'); }
  // The pre-paint boot script may already have flipped data-nav; make the
  // button agree with what is actually on screen before anything is clicked.
  apply(isOpen() ? 'open' : 'closed');
  if (btn) {
    btn.addEventListener('click', function () {
      var next = isOpen() ? 'closed' : 'open';
      apply(next);
      remember(next);
    });
  }
  if (scrim) {
    scrim.addEventListener('click', function () {
      close();
      if (btn) { btn.focus(); }
    });
  }
  document.addEventListener('keydown', function (ev) {
    var narrow = window.matchMedia && window.matchMedia(NARROW).matches;
    if (ev.key === 'Escape' && narrow && isOpen()) {
      close();
      if (btn) { btn.focus(); }
    }
  });
  // Crossing *into* the drawer layout must not leave it covering the article
  // (a rotate, or a window dragged narrower). This is the layout adapting, not
  // the reader choosing, so it is deliberately not written to the store: the
  // wide-screen preference survives the trip.
  if (window.matchMedia) {
    var mq = window.matchMedia(NARROW);
    var onChange = function (ev) { if (ev.matches && isOpen()) { apply('closed'); } };
    if (mq.addEventListener) { mq.addEventListener('change', onChange); }
    else if (mq.addListener) { mq.addListener(onChange); }
  }
})();
</script>"""

#: Search and copy. Both are pure enhancements over a document that already
#: reads correctly without them, so every entry point bails out quietly when its
#: markup is absent (a --no-toc build, an older skin) instead of throwing.
_UI_SCRIPT = r"""<script>
(function () {
  // ---------------------------------------------------------------- copy
  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:-1000px;left:-1000px;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
  // The synchronous path goes first on purpose: navigator.clipboard needs a
  // focused, secure document, and on file:// its promise can simply never
  // settle -- which would leave the button stuck on its original label.
  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; reject(new Error('clipboard timed out')); }
      }, ms);
      promise.then(function (v) {
        if (!done) { done = true; clearTimeout(timer); resolve(v); }
      }, function (e) {
        if (!done) { done = true; clearTimeout(timer); reject(e); }
      });
    });
  }
  function writeText(text) {
    if (legacyCopy(text)) { return Promise.resolve(); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      // Guarded: a browser that neither grants the permission nor rejects can
      // leave this promise pending forever, stranding the button mid-label.
      return withTimeout(navigator.clipboard.writeText(text), 1500);
    }
    return Promise.reject(new Error('no clipboard available'));
  }
  document.addEventListener('click', function (ev) {
    var btn = ev.target && ev.target.closest && ev.target.closest('.code-copy');
    if (!btn) { return; }
    var block = btn.closest('.code-block');
    var code = block && block.querySelector('code');
    if (!code) { return; }
    var lang = block.getAttribute('data-lang') || 'text';
    function settle(ok) {
      btn.textContent = ok ? '\u5df2\u590d\u5236' : '\u590d\u5236\u5931\u8d25';
      if (ok) { btn.setAttribute('data-copied', '1'); }
      setTimeout(function () {
        btn.textContent = lang;
        btn.removeAttribute('data-copied');
      }, 1300);
    }
    writeText(code.textContent).then(function () { settle(true); },
                                     function () { settle(false); });
  });

  // -------------------------------------------------------------- search
  var input = document.getElementById('finderInput');
  var list = document.getElementById('finderList');
  var article = document.querySelector('.content');
  if (!input || !list || !article) { return; }
  var box = input.parentNode;

  var index = null, hits = [], active = -1, timer = null, lastHit = null;

  function build() {
    index = [];
    var nodes = article.querySelectorAll('h1,h2,h3,h4,h5,p,li,td,th,pre');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var text = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (text.length < 2) { continue; }
      index.push({
        el: el, text: text, low: text.toLowerCase(),
        where: (el.closest('figure') ? '图示'
               : /^H[1-5]$/.test(el.tagName) ? '\u6807\u9898' : '\u6b63\u6587')
      });
    }
  }

  function terms(q) {
    return q.toLowerCase().split(/\s+/).filter(function (t) { return t.length > 0; });
  }

  function matches(entry, ts) {
    for (var i = 0; i < ts.length; i++) {
      if (entry.low.indexOf(ts[i]) < 0) { return false; }
    }
    return true;
  }

  function snippet(entry, ts) {
    var at = entry.low.indexOf(ts[0]);
    if (at < 0) { at = 0; }
    var from = Math.max(0, at - 34);
    var to = Math.min(entry.text.length, at + 86);
    return (from > 0 ? '…' : '') + entry.text.slice(from, to)
         + (to < entry.text.length ? '…' : '');
  }

  function mark(text, ts) {
    var frag = document.createDocumentFragment();
    var low = text.toLowerCase(), at = 0;
    while (at < text.length) {
      var best = -1, len = 0;
      for (var i = 0; i < ts.length; i++) {
        var found = low.indexOf(ts[i], at);
        if (found >= 0 && (best < 0 || found < best ||
            (found === best && ts[i].length > len))) {
          best = found; len = ts[i].length;
        }
      }
      if (best < 0) { frag.appendChild(document.createTextNode(text.slice(at))); break; }
      if (best > at) { frag.appendChild(document.createTextNode(text.slice(at, best))); }
      var m = document.createElement('mark');
      m.textContent = text.slice(best, best + len);
      frag.appendChild(m);
      at = best + len;
    }
    return frag;
  }

  function render(ts) {
    list.textContent = '';
    hits = []; active = -1;
    if (!ts.length) { return; }
    for (var i = 0; i < index.length && hits.length < 40; i++) {
      if (!matches(index[i], ts)) { continue; }
      var entry = index[i];
      var row = document.createElement('button');
      row.type = 'button'; row.className = 'finder-row';
      var where = document.createElement('span');
      where.className = 'finder-where'; where.textContent = entry.where;
      var snip = document.createElement('span');
      snip.className = 'finder-snip';
      snip.appendChild(mark(snippet(entry, ts), ts));
      row.appendChild(where); row.appendChild(snip);
      // IIFE, not `var at`: var is function-scoped, so all rows would share
      // one binding and every click would jump to the final result.
      row.addEventListener('click', (function (idx) {
        return function () { go(idx); };
      })(hits.length));
      list.appendChild(row);
      hits.push({ el: entry.el, row: row });
    }
    if (!hits.length) {
      var empty = document.createElement('div');
      empty.className = 'finder-empty';
      empty.textContent = '没有匹配的内容';
      list.appendChild(empty);
    }
  }

  // `stay` keeps the list open: Enter walks through the matches one at a time,
  // so closing on the first hit would end the search the reader is still in.
  function go(i, stay) {
    if (i < 0 || i >= hits.length) { return; }
    if (!stay) { close(); }
    if (lastHit && lastHit !== hits[i].el) {
      lastHit.classList.remove('finder-hit');   // only one landing marked at a time
    }
    var el = hits[i].el;
    el.classList.remove('finder-hit');
    void el.offsetWidth;                       // restart the animation
    el.classList.add('finder-hit');
    lastHit = el;
    setTimeout(function () { el.classList.remove('finder-hit'); }, 2000);
    (el.closest('figure') || el).scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  function move(step) {
    if (!hits.length) { return; }
    if (active >= 0 && hits[active]) { hits[active].row.removeAttribute('data-active'); }
    active = (active + step + hits.length) % hits.length;
    hits[active].row.setAttribute('data-active', '1');
    hits[active].row.scrollIntoView({ block: 'nearest' });
  }

  // The field is always on screen; only the result dropdown comes and goes.
  function open() {
    if (!index) { build(); }
    box.setAttribute('data-open', '1');
    input.setAttribute('aria-expanded', 'true');
  }
  function close() {
    box.removeAttribute('data-open');
    input.setAttribute('aria-expanded', 'false');
  }
  function refresh() {
    if (!index) { build(); }        // render() reads the index; build it first
    var ts = terms(input.value);
    if (!ts.length) { close(); list.textContent = ''; hits = []; return; }
    render(ts);
    open();
  }

  input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(refresh, 70);
  });
  input.addEventListener('focus', function () { if (input.value.trim()) { refresh(); } });
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); move(1); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); move(-1); }
    else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (!input.value.trim()) { return; }
      // Enter can land inside the debounce window, before the list is built;
      // settle it now rather than doing nothing and looking broken.
      if (!hits.length) { clearTimeout(timer); refresh(); }
      if (!hits.length) { return; }
      move(ev.shiftKey ? -1 : 1);            // Shift+Enter walks backwards
      go(active, true);
    } else if (ev.key === 'Escape') {
      close(); input.blur();
    }
  });
  document.addEventListener('click', function (ev) {
    if (!box.contains(ev.target)) { close(); }
  });
  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault(); input.focus(); input.select();
    }
  });
})();
</script>"""

#: The dimmed backdrop behind the narrow-screen drawer. It is inert on wide
#: screens (``display: none``) and in print, so leaving it in the markup costs
#: nothing and keeps the drawer a pure CSS concern.
_SCRIM = '<div class="scrim" id="scrim" aria-hidden="true"></div>\n'


class DocumentError(RuntimeError):
    """The assembled document violates a structural invariant."""


# --------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------
def cn_number(n: int) -> str:
    """Chinese numerals for the h1 ladder: 1 -> 一, 11 -> 十一, 20 -> 二十."""
    if n <= 0 or n > 99:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    head = "十" if tens == 1 else _CN_DIGITS[tens] + "十"
    return head + (_CN_DIGITS[ones] if ones else "")


def _walk(blocks: list):
    """Every block in document order, including those nested inside quotes."""
    for block in blocks:
        yield block
        if isinstance(block, Quote):
            yield from _walk(block.blocks)


#: A title that already opens with a numbering marker. `numbering: auto` must
#: not prefix it a second time — authors routinely write `### [1] 关键动作`
#: themselves, and `[1] [1] 关键动作` is worse than either choice.
_ALREADY_NUMBERED = re.compile(
    r"^\s*(?:"
    r"[一二三四五六七八九十百零]+、"      # 一、标题 — CJK markers take no space
    r"|\[\d+\](?=\s|$)"                # [1] 标题
    r"|\d+(?:\.\d+)*\.(?=\s|$)"        # 1. 标题   /  1.1. 标题
    r"|\d+(?:\.\d+)+(?=\s|$)"           # 1.1 标题
    r"|\d+[、)）]"                         # 1、标题   /  1) 标题
    r")"
)


def _prefixes(blocks: list, numbering: str) -> dict:
    """Map heading id -> its number label (``"一、"``, ``"1.1 "``, ...).

    The same label feeds the section heading and its outline entry, so the two
    can never disagree. With ``numbering="manual"`` the map is empty and the
    author's titles are emitted verbatim.

    A title that is already numbered keeps its own label, but the counter still
    advances so its unnumbered siblings continue the sequence.
    """
    if numbering != "auto":
        return {}
    out: dict = {}
    counters = [0] * MAX_LEVEL
    for block in _walk(blocks):
        if not isinstance(block, Heading) or not 1 <= block.level <= MAX_LEVEL:
            continue
        idx = block.level - 1
        counters[idx] += 1
        for deeper in range(idx + 1, MAX_LEVEL):
            counters[deeper] = 0
        if block.level == 1:
            prefix = f"{cn_number(counters[0])}、"
        elif block.level == 2:
            prefix = f"{counters[1]}. "
        elif block.level == 3:
            prefix = f"[{counters[2]}] "
        elif block.level == 4:
            prefix = f"{counters[1] or 1}.{counters[3]} "
        else:
            prefix = f"[{counters[4]}] "
        out[block.id] = "" if _ALREADY_NUMBERED.match(block.title or "") else prefix
    return out


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------
def _block(block: Block, figures: dict, prefixes: dict) -> str:
    if isinstance(block, Heading):
        tag = f"h{block.level}"
        cls = ' class="doc"' if block.level == 1 else ""
        prefix = esc(prefixes.get(block.id, ""))
        return f'<{tag}{cls} id="{esc(block.id)}">{prefix}{inline(block.title)}</{tag}>\n'
    if isinstance(block, Paragraph):
        return f"<p>{inline(block.text)}</p>\n"
    if isinstance(block, CodeBlock):
        return code_html(block)
    if isinstance(block, Rule):
        return "<hr>\n"
    if isinstance(block, Table):
        return _table(block)
    if isinstance(block, ListBlock):
        return _list(block) + "\n"
    if isinstance(block, Quote):
        return _quote(block, figures, prefixes)
    if isinstance(block, FigureBlock):
        return _figure(block.ref, figures)
    raise DocumentError(f"cannot render block of type {type(block).__name__}")


def _table(block: Table) -> str:
    head = "".join(f"<th>{inline(cell)}</th>" for cell in block.head)
    rows = "".join(
        "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>"
        for row in block.rows
    )
    return (
        '<div class="tw"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{rows}</tbody>"
        "</table></div>\n"
    )


def _list(block: ListBlock) -> str:
    tag = "ol" if block.ordered else "ul"
    items = "".join(_list_item(item) for item in block.items)
    return f"<{tag}>{items}</{tag}>"


def _list_item(item: ListItem) -> str:
    sub = _list(item.sub) if item.sub is not None else ""
    return f"<li>{inline(item.text)}{sub}</li>"


def _quote(block: Quote, figures: dict, prefixes: dict) -> str:
    body = "".join(_block(inner, figures, prefixes) for inner in block.blocks)
    if block.alert == "GOAL":
        return (
            '<div class="goal"><span class="mark">目标</span>'
            f'<div class="body">{body}</div></div>\n'
        )
    if block.alert == "ACCEPT":
        return (
            '<div class="accept"><span class="mark">验收</span>'
            f'<div class="body">{body}</div></div>\n'
        )
    cls = ' class="note"' if block.alert == "NOTE" else ""
    return f"<blockquote{cls}>{body}</blockquote>\n"


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------
def _figure(ref: FigureRef, figures: dict) -> str:
    svg = figures.get(ref.id)
    if not svg:
        return _figure_missing(ref)
    name = esc(ref.name or ref.id)
    kind = esc(ref.kind or "图示")
    caption = inline(ref.caption) if ref.caption else ""
    return (
        f'<figure id="fig-{esc(ref.id)}">'
        '<div class="fighead">'
        f'<span class="num">图 {ref.number}</span>'
        f'<span class="name">{name}</span>'
        f'<span class="kind">{kind}</span>'
        "</div>"
        f'<div class="canvas">{svg}</div>'
        + (f"<figcaption>{caption}</figcaption>" if caption else "")
        + "</figure>\n"
    )


def _figure_missing(ref: FigureRef) -> str:
    """A visible stand-in for a figure whose SVG was never supplied.

    It doubles as a machine-readable marker: the ``<!-- FIG:... -->`` comment is
    what ``validate.check_document`` reports as an unresolved figure, and the
    absent ``fig-<id>`` element is what it reports as a missing figure.
    """
    hint = ""
    if ref.source == "path":
        hint = f"（来源 {esc(ref.spec_or_path)}）"
    style = (
        "margin:26px 0;padding:22px 18px;border:1px dashed var(--c-red);"
        "border-radius:18px;background:var(--c-red-bg);color:var(--c-red-ink);"
        "font-size:13.5px"
    )
    return (
        f"<!-- FIG:{esc(ref.id)} unresolved -->"
        f'<div class="fig-missing" data-figure="{esc(ref.id)}" style="{style}">'
        f"图 {ref.number} 缺少渲染结果：<code>{esc(ref.id)}</code>{hint}"
        "</div>\n"
    )


# --------------------------------------------------------------------------
# Chrome
# --------------------------------------------------------------------------
def _title(doc: Doc) -> str:
    title = str(doc.meta.get("title") or "").strip()
    if title:
        return title
    return doc.toc[0].title if doc.toc else "文档"


def _opening_mode(doc: Doc) -> str:
    """Which theme the page opens in.

    This is the *material's* choice (``mode: dark``), not the caller's: a light
    document must not flash dark before the toggle script runs. The ``dark``
    argument to :func:`render` only decides whether dark mode is *offered*.
    """
    mode = str(doc.meta.get("mode") or "light").strip().lower()
    return mode if mode in ("light", "dark") else "light"


def _head(doc: Doc, theme: Theme, title: str, nav: bool = False) -> str:
    description = str(doc.meta.get("description") or "").strip()
    desc = f'<meta name="description" content="{esc(description)}">\n' if description else ""
    lang = str(doc.meta.get("lang") or "zh-CN")
    mode = _opening_mode(doc)
    return (
        "<!doctype html>\n"
        f'<html lang="{esc(lang)}" data-theme="{mode}" data-nav="open">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"{desc}"
        f"<style>\n{document_css(theme)}</style>\n"
        f"{_NAV_BOOT if nav else ''}"
        "</head>\n"
        "<body>\n"
    )


def _nav_rail() -> str:
    """The one outline control: a chevron on the sidebar's right edge.

    Deliberately a *sibling* of the ``<aside>`` rather than a child. Collapsing
    the outline sets ``visibility: hidden`` on the aside, so a button inside it
    would vanish along with the thing it is meant to bring back.
    """
    return (
        '<button class="navrail" id="navBtn" type="button" aria-controls="sidebar"'
        ' aria-expanded="true" aria-label="收起目录" title="收起目录">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        ' stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"'
        ' aria-hidden="true"><polyline points="14.5 6 8.5 12 14.5 18"/></svg>'
        "</button>\n"
    )


def _topbar(title: str, toggle: bool = True, search: bool = True) -> str:
    """Title on the left, theme switch on the right -- and nothing else.

    The outline is navigated from the outline itself; a second copy of the
    headings up here only competed with the title for the same strip of space.
    """
    return (
        '<div class="topbar"><div class="topbar-in">'
        f'<span class="brand"><i></i>{esc(title)}</span>'
        '<span class="topbar-spacer"></span>'
        + ('<div class="searchbox">'
           '<input id="finderInput" type="search" placeholder="搜索正文…"'
           ' autocomplete="off" spellcheck="false" aria-label="搜索正文"'
           ' title="搜索正文（Ctrl/⌘ K）">'
           '<div class="finder-list" id="finderList" role="listbox"'
           ' aria-label="搜索结果"></div></div>'
           if search else "")
        + ('<button class="tbtn" id="themeBtn" type="button">深色</button>'
           if toggle else "")
        + "</div></div>\n"
    )


def _chips(doc: Doc) -> list:
    declared = doc.meta.get("meta")
    if isinstance(declared, list) and declared:
        return [str(chip) for chip in declared]
    chips = []
    sections = sum(1 for e in doc.toc if e.level == 1)
    if sections:
        chips.append(f"{sections} 个章节")
    if doc.figures:
        chips.append(f"{len(doc.figures)} 张图示")
    return chips


def _hero(doc: Doc, title: str) -> str:
    parts = ['<header class="hero">']
    eyebrow = str(doc.meta.get("eyebrow") or "").strip()
    if eyebrow:
        parts.append(f'<span class="eyebrow">{esc(eyebrow)}</span>')
    parts.append(f"<h1>{esc(title)}</h1>")
    lede = str(doc.meta.get("lede") or doc.meta.get("description") or "").strip()
    if lede:
        parts.append(f'<p class="lede">{inline(lede)}</p>')
    chips = _chips(doc)
    if chips:
        spans = "".join(f"<span>{inline(chip)}</span>" for chip in chips)
        parts.append(f'<div class="meta">{spans}</div>')
    parts.append("</header>\n")
    return "".join(parts)


def _toc(doc: Doc, prefixes: dict) -> str:
    """The outline: h1 as top-level entries, h2 nested under them.

    Deeper levels stay in :attr:`Doc.toc` for callers that want them; the page
    outline stops at two levels so it stays skimmable.
    """
    shown = [e for e in doc.toc if e.level <= 2] or list(doc.toc)
    groups: list = []
    for entry in shown:
        if entry.level <= 1 or not groups:
            groups.append((entry, []))
        else:
            groups[-1][1].append(entry)
    items = []
    for entry, children in groups:
        label = esc(prefixes.get(entry.id, "") + entry.title)
        sub = ""
        if children:
            links = "".join(
                f'<li><a href="#{esc(c.id)}">'
                f"{esc(prefixes.get(c.id, '') + c.title)}</a></li>"
                for c in children
            )
            sub = f"<ul>{links}</ul>"
        items.append(f'<li><a href="#{esc(entry.id)}">{label}</a>{sub}</li>')
    return f'<nav class="toc" id="toc"><h2>目录</h2><ol>{"".join(items)}</ol></nav>\n'


def _body(blocks: list, figures: dict, prefixes: dict) -> str:
    out: list = []
    seen_h1 = False
    previous = None
    for block in blocks:
        if isinstance(block, Heading) and block.level == 1:
            if seen_h1 and not isinstance(previous, Rule):
                out.append("<hr>\n")
            seen_h1 = True
        out.append(_block(block, figures, prefixes))
        previous = block
    return "".join(out)


def _footer(doc: Doc, title: str) -> str:
    bits = [title]
    sections = sum(1 for e in doc.toc if e.level == 1)
    if sections:
        bits.append(f"{sections} 个章节")
    if doc.figures:
        bits.append(f"{len(doc.figures)} 张图示")
    return (
        '<footer class="doc">'
        f'<span>{esc(" · ".join(bits))}</span>'
        "<span>单文件 HTML，图示为内联 SVG，支持深色主题与打印</span>"
        "</footer>\n"
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def render(
    doc: Doc,
    figures: dict,
    theme: Theme,
    *,
    numbering: str = "auto",
    dark: bool = True,
    toc: bool = True,
    search: bool = True,
    validate: bool = True,
) -> str:
    """Assemble ``doc`` into a complete single-file HTML document.

    ``figures`` maps figure id to already-rendered SVG markup; ids that are
    missing get a visible placeholder rather than silence. ``numbering="auto"``
    numbers the heading ladder (``一、`` / ``1.`` / ``[1]`` / ``1.1`` /
    ``[1]``); ``"manual"`` emits the author's titles verbatim. ``dark`` selects
    the theme the page opens in -- the toggle script can still switch either
    way. ``validate`` re-checks this module's own structural invariants (unique
    ids, resolvable anchors, balanced tags) and raises :class:`DocumentError` if
    it broke them.
    """
    if numbering not in ("auto", "manual"):
        raise ValueError(f"numbering must be 'auto' or 'manual', got {numbering!r}")
    if isinstance(theme, str):
        theme = Theme.load(theme)

    title = _title(doc)
    prefixes = _prefixes(doc.blocks, numbering)
    toc_html = _toc(doc, prefixes) if toc else ""
    has_nav = bool(toc_html)
    # Source order *is* the layout: on the wide grid the <aside> auto-places in
    # column 1 and the <main> in column 2. With --no-toc there is no aside, so
    # the single full-width column has to be asked for by name.
    shell_cls = "shell" if has_nav else "shell no-sidebar"
    html = "".join(
        [
            _head(doc, theme, title, has_nav),
            _topbar(title, dark, search),
            f'<div class="{shell_cls}">\n',
            (f'<aside class="sidebar" id="sidebar">\n{toc_html}</aside>\n'
             + _nav_rail() if has_nav else ""),
            '<main class="content">\n',
            _hero(doc, title),
            _body(doc.blocks, figures, prefixes),
            _footer(doc, title),
            "</main>\n",
            _SCRIM if has_nav else "",
            "</div>\n",
            _SCRIPT if dark else "",
            _NAV_SCRIPT if has_nav else "",
            _UI_SCRIPT,
            "\n</body>\n</html>\n",
        ]
    )
    if validate:
        _self_check(html)
    return html


def _self_check(html: str) -> None:
    """Prove the skeleton is sound.

    Three things are opaque to this layer and are removed (not parsed) first:
    the inline stylesheet and scripts, whose *text* is not markup, and the
    figures' SVG, which the caller rendered. Leaving any of them in would let a
    stray ``<svg>`` or a tag name written inside a CSS comment pair with real
    markup and report a tag imbalance that does not exist.
    """
    skeleton = re.sub(r"<style\b.*?</style>", "", html, flags=re.S)
    skeleton = re.sub(r"<script\b.*?</script>", "", skeleton, flags=re.S)
    skeleton = re.sub(r"<svg\b.*?</svg>", "<svg></svg>", skeleton, flags=re.S)
    findings = [f for f in V.check_document(skeleton) if f.code in _STRUCTURAL_CODES]
    if findings:
        detail = "; ".join(f"{f.code}: {f.message}" for f in findings)
        raise DocumentError(f"assembled document is invalid: {detail}")
