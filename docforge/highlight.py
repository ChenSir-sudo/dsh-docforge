"""Per-language syntax highlighting for fenced code blocks.

Why a hand-rolled tokenizer instead of a highlighting library: docforge's whole
promise is that one material compiles to the same polished single-file HTML on
any machine, with no install step and no network. A library would sit on that
critical path, and a *partial* highlighter is worse than none -- it would colour
some fences and leave others flat. So this module carries one small scanner per
language family built on :mod:`re` alone, with no state between calls.

The property that matters most is that the code survives the trip. :func:`highlight`
never rewrites, reorders or drops a character: it emits the escaped input in
order, each stretch wrapped in a ``tok-*`` run. Strip the tags, unescape, and the
code is back byte for byte -- which is what makes it safe to run in front of
snippets full of ``<``, ``&``, quotes, CJK or CRLF. A tag this module does not
recognise falls back to one escaped run rather than being guessed at or dropped.

Colour never appears here: this module chooses the *class* of a run (and the
accent family of a whole block) and ``assets/code.css`` decides what that class
looks like, in both light and dark.
"""

from __future__ import annotations

import re

__all__ = ["FAMILIES", "LANGUAGES", "family", "highlight"]

#: Every language tag :func:`highlight` tokenizes. Any other tag -- including an
#: untagged fence -- is rendered as escaped plain text.
LANGUAGES: tuple = (
    "bash",
    "console",
    "json",
    "py",
    "python",
    "sh",
    "shell",
    "sql",
    "text",
    "yaml",
    "yml",
)

#: Accent families. ``assets/code.css`` gives each one its own left border and
#: tinted background, so a shell transcript is distinguishable from a JSON
#: payload without reading a single token.
FAMILIES: tuple = ("code", "data", "shell", "query", "plain")

_FAMILY_OF = {
    "py": "code",
    "python": "code",
    "json": "data",
    "yaml": "data",
    "yml": "data",
    "bash": "shell",
    "sh": "shell",
    "shell": "shell",
    "console": "shell",
    "sql": "query",
    "text": "plain",
}


# --------------------------------------------------------------------------
# Escaping and painting
# --------------------------------------------------------------------------
def _escape(text: str) -> str:
    """Escape ``& < > "`` -- enough for text nodes and for attribute values."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _spans(code: str, pattern: re.Pattern, classes: tuple) -> list:
    """``(start, end, class)`` for every named group that matched.

    Each entry of ``classes`` is one ``(group, class)`` pair and the first match
    wins, so the order of ``classes`` is the precedence between alternatives.
    The span is the *group's* extent, not the whole match: an alternative may
    legitimately consume a prefix (YAML's indent before a key, say) that is not
    part of the token. The scanner never yields overlaps, because
    :meth:`re.Pattern.finditer` cannot.
    """
    out: list = []
    for match in pattern.finditer(code):
        for group, cls in classes:
            start, end = match.span(group)
            if end > start:
                out.append((start, end, cls))
                break
    return out


def _paint(code: str, spans: list) -> str:
    """Emit ``code`` in order, wrapping ``spans`` and escaping everything.

    This is the whole round-trip guarantee: the output is the input's slices,
    concatenated in order, so nothing can be lost or moved. ``spans`` must be
    sorted and non-overlapping -- :func:`_spans` is the only producer.
    """
    out: list = []
    pos = 0
    for start, end, cls in spans:
        if start > pos:
            out.append(_escape(code[pos:start]))
        out.append(f'<span class="{cls}">{_escape(code[start:end])}</span>')
        pos = end
    out.append(_escape(code[pos:]))
    return "".join(out)


def _scan(code: str, pattern: re.Pattern, classes: tuple) -> str:
    return _paint(code, _spans(code, pattern, classes))


def _alt(name: str, words) -> str:
    """A word-boundary alternation over literal words, as a named group.

    ``\\b`` does the work that ordering would otherwise have to: ``in`` never
    swallows the ``in`` of ``int``, so the word lists stay sorted and readable.
    """
    return r"(?P<%s>\b(?:%s)\b)" % (name, "|".join(words))


# --------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------
_PY_KW = (
    "and", "as", "assert", "async", "await", "break", "case", "class",
    "continue", "def", "del", "elif", "else", "except", "finally", "for",
    "from", "global", "if", "import", "in", "is", "lambda", "match",
    "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
    "with", "yield",
)

_PY_BI = (
    "ArithmeticError", "AssertionError", "Exception", "False", "KeyError",
    "None", "NotImplementedError", "RuntimeError", "StopIteration", "True",
    "TypeError", "ValueError", "abs", "all", "any", "bool", "cls", "dict",
    "enumerate", "filter", "float", "frozenset", "getattr", "hasattr", "int",
    "isinstance", "iter", "len", "list", "map", "max", "min", "next",
    "object", "open", "print", "range", "repr", "reversed", "round", "self",
    "set", "setattr", "sorted", "str", "sum", "super", "tuple", "type", "zip",
)

#: Triple quotes first, then single: a ``"""`` body must not be read as three
#: empty strings. An unterminated triple quote runs to the end of the snippet,
#: which is exactly how the editor would colour it.
_PY_STR = (
    r"(?P<str>(?:[rRbBuUfF]{0,2})(?:"
    r"'''[\s\S]*?(?:'''|\Z)"
    r'|"""[\s\S]*?(?:"""|\Z)'
    r"|'(?:\\.|[^'\\\n])*'"
    r'|"(?:\\.|[^"\\\n])*"'
    r"))"
)

_PY_RE = re.compile(
    r"(?P<com>#[^\n]*)"
    r"|" + _PY_STR
    # A def/class name is the one definition site the reader looks for.
    + r"|(?P<fn>(?:(?<=\bdef\s)|(?<=\bclass\s))[A-Za-z_]\w*)"
    + r"|(?P<num>\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+"
    + r"|\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)(?:[eE][+-]?\d[\d_]*)?[jJ]?\b)"
    + r"|" + _alt("bi", _PY_BI)
    + r"|" + _alt("kw", _PY_KW)
    # Any other name in call position still reads as a function.
    + r"|(?P<fn2>[A-Za-z_]\w*(?=\s*\())"
    + r"|(?P<op>[-+*/%=<>!&|^~@:.,;(){}\[\]\\]+)"
)

_PY_CLASSES = (
    ("com", "tok-com"),
    ("str", "tok-str"),
    ("fn", "tok-fn"),
    ("num", "tok-num"),
    ("bi", "tok-bi"),
    ("kw", "tok-kw"),
    ("fn2", "tok-fn"),
    ("op", "tok-op"),
)


def _python(code: str) -> str:
    return _scan(code, _PY_RE, _PY_CLASSES)


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------
#: A quotedstring followed by ``:`` is a key, so the key alternative must come
#: before the plain string one at the same start position.
_JSON_RE = re.compile(
    r'(?P<key>"(?:\\.|[^"\\])*"(?=\s*:))'
    r'|(?P<str>"(?:\\.|[^"\\])*")'
    r"|(?P<num>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|" + _alt("bi", ("false", "null", "true"))
    + r"|(?P<op>[{}\[\],:])"
)

_JSON_CLASSES = (
    ("key", "tok-key"),
    ("str", "tok-str"),
    ("num", "tok-num"),
    ("bi", "tok-bi"),
    ("op", "tok-op"),
)


def _json(code: str) -> str:
    return _scan(code, _JSON_RE, _JSON_CLASSES)


# --------------------------------------------------------------------------
# YAML
# --------------------------------------------------------------------------
#: ``key:`` is a scalar at the start of a mapping entry, with or without the
#: ``- `` of a sequence item. The lookahead demands a space or end of line after
#: the colon, which is what keeps ``https://x`` from reading as a key.
_YAML_RE = re.compile(
    r"(?P<com>#[^\n]*)"
    r"|(?P<str>'(?:''|[^'\n])*'|\"(?:\\.|[^\"\\\n])*\")"
    r"|(?P<key>[A-Za-z_][\w.\-/]*(?:[ \t][A-Za-z_][\w.\-/]*)*"
    r"(?=\s*:(?:\s|\Z)))"
    r"|(?P<bi>\b(?:false|no|null|off|on|true|yes|False|Null|True)\b|~)"
    r"|(?P<num>\b(?:0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.[\d_]*)?"
    r"(?:[eE][+-]?\d+)?)\b)"
    r"|(?P<op>[-:,\[\]{}|>&*!?]+)",
)

_YAML_CLASSES = (
    ("com", "tok-com"),
    ("str", "tok-str"),
    ("key", "tok-key"),
    ("bi", "tok-bi"),
    ("num", "tok-num"),
    ("op", "tok-op"),
)


def _yaml(code: str) -> str:
    return _scan(code, _YAML_RE, _YAML_CLASSES)


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------
_SQL_KW = (
    "add", "all", "alter", "and", "as", "asc", "between", "by", "case",
    "column", "constraint", "create", "cross", "default", "delete", "desc",
    "distinct", "drop", "else", "end", "exists", "foreign", "from", "full",
    "group", "having", "if", "in", "index", "inner", "insert", "into", "is",
    "join", "key", "left", "like", "limit", "not", "null", "offset", "on",
    "or", "order", "outer", "primary", "references", "returning", "right",
    "select", "set", "table", "then", "union", "unique", "update", "values",
    "view", "when", "where", "with",
)

_SQL_BI = (
    "avg", "cast", "coalesce", "count", "current_date", "current_timestamp",
    "max", "min", "now", "nullif", "sum",
)

_SQL_RE = re.compile(
    r"(?P<com>--[^\n]*|/\*[\s\S]*?(?:\*/|\Z))"
    r"|(?P<str>'(?:''|[^'])*')"
    r"|(?P<key>\"(?:\"\"|[^\"])*\"|`[^`]*`)"
    r"|(?P<num>\b\d+(?:\.\d+)?\b)"
    # A bound parameter is a value the reader scans for, so it shares the
    # constant class rather than falling in with the punctuation.
    r"|(?P<bi>\$\d+)"
    r"|" + _alt("bi2", _SQL_BI)
    + r"|" + _alt("kw", _SQL_KW)
    + r"|(?P<fn>[A-Za-z_]\w*(?=\s*\())"
    + r"|(?P<op>[-+*/%=<>!|&^~;,.()\[\]{}:?@]+)",
    re.IGNORECASE,
)

_SQL_CLASSES = (
    ("com", "tok-com"),
    ("str", "tok-str"),
    ("key", "tok-key"),
    ("num", "tok-num"),
    ("bi", "tok-bi"),
    ("bi2", "tok-bi"),
    ("kw", "tok-kw"),
    ("fn", "tok-fn"),
    ("op", "tok-op"),
)


def _sql(code: str) -> str:
    return _scan(code, _SQL_RE, _SQL_CLASSES)


# --------------------------------------------------------------------------
# Shell (bash / sh / shell), and console transcripts of one
# --------------------------------------------------------------------------
_SH_KW = (
    "case", "do", "done", "elif", "else", "esac", "fi", "for", "function",
    "if", "in", "select", "then", "time", "until", "while",
)

_SH_BI = (
    "alias", "awk", "bg", "brew", "cat", "cd", "chmod", "chown", "cp", "curl",
    "cut", "declare", "df", "diff", "docker", "du", "echo", "eval", "exec",
    "exit", "export", "fg", "find", "git", "grep", "gzip", "head", "jq",
    "kill", "let", "ln", "local", "ls", "make", "mkdir", "mount", "mv",
    "node", "npm", "pip", "printf", "ps", "pwd", "python", "python3", "read",
    "readonly", "return", "rm", "rsync", "sed", "set", "shift", "sleep",
    "sort", "source", "ssh", "sudo", "tail", "tar", "tee", "test", "touch",
    "tr", "trap", "type", "umask", "unalias", "uniq", "unset", "wait", "wc",
    "wget", "which", "xargs", "yarn",
)

_SH_STR = (
    r"(?P<str>'(?:[^'\n])*'"
    r'|"(?:\\.|[^"\\\n])*"'
    r"|`(?:\\.|[^`\\])*`)"
)


def _shell_pattern(prompt: bool) -> str:
    """The shell scanner, optionally with a ``$`` / ``>`` transcript prompt.

    One pattern for both so a ``console`` fence is tokenized by exactly the same
    rules as a ``bash`` one, plus the prompt rule the transcript needs.
    """
    head = r"(?m)^(?P<prompt>[ \t]*(?:\$|>)[ \t])|" if prompt else ""
    return (
        head
        + r"(?P<com>#[^\n]*)"
        + r"|" + _SH_STR
        # $VAR, ${VAR}, $1, $@ -- the part of a transcript a reader scans for.
        + r"|(?P<bi>\$\{[A-Za-z_]\w*\}|\$[A-Za-z_]\w*|\$[0-9@*?#!$-])"
        + r"|" + _alt("kw", _SH_KW)
        + r"|" + _alt("bi2", _SH_BI)
        + r"|(?P<num>\b\d+\b)"
        + r"|(?P<fn>[A-Za-z_][\w.-]*(?=\s*\(\s*\)))"
        + r"|(?P<op>[-+*/%=<>!|&;()\[\]{}~^:,.]+)"
    )


_SH_RE = re.compile(_shell_pattern(False))
_CONSOLE_RE = re.compile(_shell_pattern(True))

#: A console line is a command only if the transcript marks it with a prompt.
_PROMPT_LINE_RE = re.compile(r"^[ \t]*(?:\$|>|#)[ \t]")

_SH_CLASSES = (
    ("com", "tok-com"),
    ("str", "tok-str"),
    ("bi", "tok-bi"),
    ("kw", "tok-kw"),
    ("bi2", "tok-bi"),
    ("num", "tok-num"),
    ("fn", "tok-fn"),
    ("op", "tok-op"),
)

#: The transcript prompt is punctuation, but it comes first in the pattern.
_CONSOLE_CLASSES = (("prompt", "tok-op"),) + _SH_CLASSES


def _shell(code: str) -> str:
    return _scan(code, _SH_RE, _SH_CLASSES)


def _console(code: str) -> str:
    """A transcript: commands are shell, their output stays neutral.

    Tokenizing line by line is what makes that distinction possible -- a
    transcript's output line is prose, so colouring the ``in`` of ``added 3
    packages in 1.2s`` as a shell keyword would be a lie. It also means a command
    line that opens a quote it never closes cannot bleed into the output below
    it.
    """
    spans: list = []
    pos = 0
    for line in code.splitlines(keepends=True):
        if _PROMPT_LINE_RE.match(line):
            spans.extend(
                (pos + start, pos + end, cls)
                for start, end, cls in _spans(line, _CONSOLE_RE, _CONSOLE_CLASSES)
            )
        pos += len(line)
    return _paint(code, spans)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _plain(code: str) -> str:
    return _escape(code)


_TOKENIZERS = {
    "bash": _shell,
    "console": _console,
    "json": _json,
    "py": _python,
    "python": _python,
    "sh": _shell,
    "shell": _shell,
    "sql": _sql,
    "text": _plain,
    "yaml": _yaml,
    "yml": _yaml,
}


def family(lang: str) -> str:
    """The accent family for ``lang`` -- one of :data:`FAMILIES`.

    Unknown and untagged fences land in ``"plain"``, which still gets the block
    chrome; only the accent changes.
    """
    return _FAMILY_OF.get(_normalise(lang), "plain")


def _normalise(lang: str) -> str:
    return str(lang or "").strip().lower()


def highlight(code: str, lang: str) -> str:
    """Highlight ``code`` as ``lang``: escaped HTML with ``tok-*`` runs.

    Total and independent. Every character of ``code`` is emitted exactly once,
    in order, HTML-escaped; unknown languages, empty input and a non-string
    ``code`` are all valid, and no call leaves state behind for the next one -- a
    triple-quoted string or a block comment that never closes simply runs to the
    end of *this* snippet.
    """
    text = code if isinstance(code, str) else str(code or "")
    if not text:
        return ""
    return _TOKENIZERS.get(_normalise(lang), _plain)(text)
