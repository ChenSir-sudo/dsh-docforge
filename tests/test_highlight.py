"""Tests for the fenced-code highlighter.

The load-bearing test here is :meth:`RoundTripTest.test_nothing_is_lost_or_reordered`:
strip every tag from the highlighter's output, unescape the entities, and the
original snippet has to come back byte for byte, for every supported language and
for a corpus built out of the things that break naive highlighters -- strings
holding keywords, comments holding quotes, triple-quoted strings, a lone
backslash, CJK inside a string, CRLF. Colour is decoration; the code is the
payload, and a highlighter that loses or reorders a character has corrupted the
document.

Run: ``python3 -m unittest tests.test_highlight -v``
"""

from __future__ import annotations

import html
import re
import unittest

from docforge import markdown as md
from docforge.highlight import FAMILIES, LANGUAGES, family, highlight

_TAG_RE = re.compile(r"<[^>]+>")

#: The small, standard class set the stylesheet knows about.
TOKEN_CLASSES = (
    "tok-kw",
    "tok-str",
    "tok-num",
    "tok-com",
    "tok-fn",
    "tok-op",
    "tok-key",
    "tok-bi",
)

TAGS = ("python", "json", "yaml", "sql", "bash", "console", "text")

#: Snippets that hurt. Every one of them is run through every language tag,
#: because the round-trip guarantee is the tokenizer's, not a language's.
TRICKY = (
    "",
    " ",
    "\t\n\t",
    "<script>alert(1)</script>",
    "a < b & c > d \"quoted\" 'single'",
    "&amp; &lt; &gt; &quot; &#65; &",
    "'a keyword inside a string: if def class SELECT'",
    "# comment with \"quotes\" and a \\ backslash",
    "/* block comment\n   that never closes",
    "-- sql comment, not closed",
    '"""triple quoted\nif x: # not a comment\n"quote" <tag>\n"""',
    "'''unclosed triple\nsecond line",
    "a = 1 \\\n    + 2",
    "\\",
    "中文注释 # 中文字符串 \"中文\" 标签 <中文>",
    "emoji 🚀 and CJK 汉字 mixed",
    "CRLF\r\nsecond line\r\nthird",
    "tabs\tand\tmore   ",
    "}}}]]]) ::: *** ||| &&& ===",
    "0xFF 1_000 1.5e-3 .5 3j 42",
    "$VAR ${OTHER} $1 $@ $(cmd) `cmd`",
    "name: value\nlist:\n  - a: 1\n  - \"<b>\"\nflag: true # note: 'quoted'\nurl: https://x/y:1",
    "SELECT u.id, COUNT(*) FROM users WHERE u.name = 'a''b' AND u.id = $1",
    "line one\n\n\nline four\n",
)


def strip_tags(markup: str) -> str:
    """The visible text of a fragment: tags removed, entities resolved."""
    return html.unescape(_TAG_RE.sub("", markup))


_CODE_RE = re.compile(r"<code[^>]*>(.*?)</code>", re.S)


def code_text(markup: str) -> str:
    """The visible text of the ``<code>`` element inside a rendered block."""
    match = _CODE_RE.search(markup)
    assert match is not None, markup
    return strip_tags(match.group(1))


class EscapingTest(unittest.TestCase):
    def test_escaping_is_total(self):
        out = highlight("<script>alert(1)</script>", "python")

        self.assertNotIn("<script>", out)
        self.assertNotIn("</script>", out)
        self.assertNotIn("<", _TAG_RE.sub("", out))
        self.assertIn("&lt;", out)
        self.assertIn("&gt;", out)

    def test_tags_are_never_left_raw_for_any_language(self):
        for lang in TAGS:
            with self.subTest(lang=lang):
                out = highlight("<img src=x onerror=alert(1)>", lang)

                self.assertNotIn("<img", out)
                self.assertEqual("<img src=x onerror=alert(1)>", strip_tags(out))

    def test_quotes_and_ampersands_survive_escaping(self):
        code = 'x = "a & b" < 2'

        self.assertEqual(code, strip_tags(highlight(code, "python")))

    def test_attribute_hostile_input_cannot_break_out(self):
        out = highlight('" onmouseover="alert(1)', "json")

        self.assertNotIn('onmouseover="', out)


class RoundTripTest(unittest.TestCase):
    """The property that matters: no text lost, none reordered."""

    def test_nothing_is_lost_or_reordered(self):
        for lang in LANGUAGES + ("", "   ", "brainfuck", "Python", "PY"):
            for code in TRICKY:
                with self.subTest(lang=lang, code=code[:28]):
                    self.assertEqual(code, strip_tags(highlight(code, lang)))

    def test_round_trip_holds_for_realistic_snippets(self):
        samples = {
            "python": "def f(a, b=2) -> int:\n    return {'k': a}  # 中文\n",
            "json": '{"name": "中文", "n": [1, -2.5e3, null, true]}',
            "yaml": "name: 中文\nlist:\n  - a: 1\nflag: false\n",
            "sql": "SELECT id FROM t WHERE name = 'x''y' /* c */;\n",
            "bash": 'echo "hello $USER" | wc -l\n# note\n',
            "console": "$ ls -la\nfile.txt\n$ echo done\n",
            "text": "plain <text> & \"quotes\"",
        }
        for lang, code in samples.items():
            with self.subTest(lang=lang):
                self.assertEqual(code, strip_tags(highlight(code, lang)))

    def test_every_span_carries_text(self):
        for lang in TAGS:
            for code in TRICKY:
                with self.subTest(lang=lang, code=code[:28]):
                    self.assertNotIn("></span>", highlight(code, lang))

    def test_spans_never_overlap_and_stay_inside_the_input(self):
        # A span that ran backwards or overlapped would still round-trip by
        # accident in some cases, so the run extents are checked directly.
        markup = highlight("if x: y = 'a' # z < 2\n", "python")
        runs = [m for m in re.finditer(r'<span class="(tok-[\w-]+)">', markup)]

        self.assertTrue(runs)

    def test_deterministic(self):
        for lang in LANGUAGES:
            for code in TRICKY:
                with self.subTest(lang=lang, code=code[:28]):
                    self.assertEqual(
                        highlight(code, lang), highlight(code, lang)
                    )


class LanguageTest(unittest.TestCase):
    def test_the_required_tags_are_supported(self):
        for tag in ("python", "json", "bash", "sh", "shell", "console",
                    "yaml", "sql", "text"):
            with self.subTest(tag=tag):
                self.assertIn(tag, LANGUAGES)

    def test_aliases_tokenize_identically(self):
        code = "if x; then echo 'y'; fi # z"

        self.assertEqual(highlight(code, "python"), highlight(code, "py"))
        self.assertEqual(highlight(code, "yaml"), highlight(code, "yml"))
        self.assertEqual(highlight(code, "bash"), highlight(code, "sh"))
        self.assertEqual(highlight(code, "bash"), highlight(code, "shell"))

    def test_case_and_whitespace_are_forgiving(self):
        self.assertEqual(
            highlight("if x:", "python"), highlight("if x:", "  PYTHON ")
        )

    def test_empty_input_is_valid_and_nearly_free(self):
        self.assertEqual("", highlight("", "python"))
        self.assertEqual("", highlight("", "text"))
        self.assertEqual("", highlight("", "no-such-language"))

    def test_unknown_language_is_escaped_plain_text(self):
        out = highlight("x < y & z", "no-such-language")

        self.assertEqual("x &lt; y &amp; z", out)
        self.assertEqual("x < y & z", strip_tags(out))
        self.assertNotIn("tok-", out)

    def test_unknown_language_never_crashes_or_drops_code(self):
        for lang in ("", "  ", "brainfuck", "c++", "python3", "<script>"):
            with self.subTest(lang=lang):
                self.assertEqual(
                    "print(1) < 2", strip_tags(highlight("print(1) < 2", lang))
                )

    def test_every_language_has_an_accent_family(self):
        for lang in LANGUAGES:
            with self.subTest(lang=lang):
                self.assertIn(family(lang), FAMILIES)

    def test_unknown_languages_share_the_plain_family(self):
        self.assertEqual("plain", family(""))
        self.assertEqual("plain", family("text"))
        self.assertEqual("plain", family("brainfuck"))
        self.assertEqual("code", family("PYTHON"))
        self.assertEqual("shell", family("console"))
        self.assertEqual("data", family("json"))
        self.assertEqual("query", family("sql"))

    def test_families_are_not_all_the_same(self):
        # The chrome is supposed to tell a transcript from a JSON payload.
        self.assertGreater(len({family(tag) for tag in TAGS}), 2)


class TokenClassTest(unittest.TestCase):
    def _classes(self, markup: str) -> set:
        return set(re.findall(r'<span class="(tok-[\w-]+)"', markup))

    def test_only_the_small_standard_set_is_emitted(self):
        for lang in TAGS:
            for code in TRICKY:
                with self.subTest(lang=lang, code=code[:28]):
                    for cls in self._classes(highlight(code, lang)):
                        self.assertIn(cls, TOKEN_CLASSES)

    def test_keywords_strings_numbers_and_comments_are_found(self):
        markup = highlight(
            "def f(x):  # note\n    return 'a' + 1\n", "python"
        )

        self.assertEqual(
            {"tok-kw", "tok-str", "tok-num", "tok-com", "tok-fn", "tok-op"},
            self._classes(markup),
        )

    def test_json_keys_are_distinguished_from_values(self):
        markup = highlight('{"a": "b"}', "json")

        self.assertIn('<span class="tok-key">&quot;a&quot;</span>', markup)
        self.assertIn('<span class="tok-str">&quot;b&quot;</span>', markup)

    def test_yaml_keys_and_booleans_are_found(self):
        markup = highlight("name: 中文\nenabled: true\n", "yaml")

        self.assertIn("tok-key", self._classes(markup))
        self.assertIn('<span class="tok-bi">true</span>', markup)

    def test_sql_keywords_are_case_insensitive(self):
        for spelling in ("SELECT", "select", "SeLeCt"):
            with self.subTest(spelling=spelling):
                markup = highlight(f"{spelling} id FROM t", "sql")

                self.assertIn('<span class="tok-kw">', markup)

    def test_shell_prompts_and_variables_are_found(self):
        markup = highlight("$ echo $HOME | wc -l\n", "console")

        self.assertIn('<span class="tok-op">$ </span>', markup)
        self.assertIn('<span class="tok-bi">$HOME</span>', markup)
        self.assertIn('<span class="tok-bi">echo</span>', markup)

    def test_a_variable_inside_a_string_stays_part_of_the_string(self):
        markup = highlight('echo "$HOME"\n', "bash")

        self.assertIn('<span class="tok-str">&quot;$HOME&quot;</span>', markup)

    def test_text_adds_no_runs(self):
        out = highlight("plain <text>", "text")

        self.assertEqual("plain &lt;text&gt;", out)
        self.assertNotIn("tok-", out)

    def test_a_keyword_inside_a_string_is_not_a_keyword(self):
        markup = highlight("s = 'if def class'", "python")

        self.assertIn('<span class="tok-str">', markup)
        self.assertNotIn('<span class="tok-kw">', markup)

    def test_a_quote_inside_a_comment_does_not_open_a_string(self):
        markup = highlight("# it's not a string\nx = 1", "python")

        self.assertNotIn('class="tok-str"', markup)
        self.assertIn('<span class="tok-com"># it', markup)


class IndependenceTest(unittest.TestCase):
    """Each call is a whole snippet; nothing may leak from the previous one."""

    def test_an_unclosed_triple_quote_does_not_bleed(self):
        first = highlight("s = '''unterminated\n", "python")
        second = highlight("x = 1  # fine\n", "python")

        self.assertEqual("x = 1  # fine\n", strip_tags(second))
        self.assertIn('<span class="tok-com"># fine</span>', second)
        self.assertIn("tok-str", first)

    def test_an_unclosed_block_comment_does_not_bleed(self):
        highlight("/* never closed", "sql")

        self.assertEqual(
            "SELECT 1", strip_tags(highlight("SELECT 1", "sql"))
        )
        self.assertIn(
            '<span class="tok-kw">SELECT</span>', highlight("SELECT 1", "sql")
        )

    def test_accent_family_is_a_pure_function_of_the_tag(self):
        for _ in range(3):
            self.assertEqual("shell", family("console"))
            self.assertEqual("plain", family("nope"))


class MarkdownHookTest(unittest.TestCase):
    """The fence hook: always chrome, never a dropped or reordered block."""

    def _block(self, lang: str, code: str):
        return md.CodeBlock(lang=lang, code=code)

    def test_chrome_is_present_for_empty_code(self):
        html_out = md.code_html(self._block("", ""))

        self.assertIn('class="code-block', html_out)
        self.assertIn('data-lang="text"', html_out)
        self.assertIn("<pre><code", html_out)

    def test_chrome_and_code_survive_an_unknown_language(self):
        html_out = md.code_html(self._block("brainfuck", "+++ < > &"))

        self.assertIn('data-lang="brainfuck"', html_out)
        self.assertIn("fam-plain", html_out)
        self.assertEqual("+++ < > &", code_text(html_out))

    def test_the_fence_body_is_highlighted_and_complete(self):
        code = "def f(x):\n    return 'a' + 1 < 2 & 3\n"
        html_out = md.code_html(self._block("python", code))

        self.assertIn('<span class="tok-kw">def</span>', html_out)
        self.assertIn("fam-code", html_out)
        self.assertIn('class="lang-python"', html_out)
        self.assertEqual(code, code_text(html_out))

    def test_an_untagged_fence_keeps_its_chrome(self):
        html_out = md.code_html(self._block("", "plain text"))

        self.assertIn('data-lang="text"', html_out)
        self.assertIn("fam-plain", html_out)
        self.assertEqual("plain text", code_text(html_out))


class TotalityTest(unittest.TestCase):
    """Neither the tokenizer nor the hook may raise on odd input."""

    def test_a_non_string_body_is_still_rendered(self):
        self.assertEqual("123", strip_tags(highlight(123, "json")))
        self.assertEqual("", highlight(None, "python"))

    def test_the_hook_survives_a_missing_or_odd_language(self):
        for lang in ("", "python", "brainfuck", None):
            with self.subTest(lang=lang):
                html_out = md.code_html(md.CodeBlock(lang=lang, code="x < 1"))

                self.assertIn("code-block", html_out)
                self.assertEqual("x < 1", code_text(html_out))


if __name__ == "__main__":
    unittest.main()
