#!/usr/bin/env python3
"""Measure real glyph advances and compare them with docforge's estimate.

The validator trusts a per-glyph advance table. Every box size, gap and
clearance is computed from it. Nothing had ever compared that table with a glyph
the machine actually rendered, so the tolerance had no empirical basis.

This measures a corpus in a real browser, using the same font stack the documents
use, and reports the error the table would make. `--faces` repeats the check on
faces the table was *not* calibrated on, which is the question that matters:
documents are opened on machines the author never sees.

    python3 tools/measure-text.py [--font SIZE] [--json out.json]

Needs a Chromium-family browser; set DOCFORGE_BROWSER to point at one.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from docforge import render as R          # noqa: E402
from docforge import text as T            # noqa: E402

#: A corpus that covers what actually turns up in figures: identifiers, prose,
#: numbers, punctuation, and CJK mixed with Latin.
CORPUS = [
    "messages", "task_params", "retrieval_context", "requires_approval",
    "approval_status", "iteration_count", "final_answer", "user_intent",
    "intent_node", "tool_executor", "human_review", "should_refine",
    "StateGraph", "add_conditional_edges", "checkpointer", "thread_id",
    "InMemorySaver", "SQLite", "Q1", "Q4", "MMXXV", "0123456789",
    "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "the quick brown fox jumps over the lazy dog",
    "{status, data, error}", "[1] note :: a-b/c_d", "100% / 3.14 - 2.72",
    "RAG", "MCP", "HITL", "API", "CI/CD", "K8s", "OpenTelemetry",
    "状态", "用户意图", "检索子系统", "质量闭环与人工介入",
    "状态 State 与图蓝图", "RAG 与工具/MCP", "评估、部署、灰度",
    "阶段 0：需求建模与成功标准", "检索 retrieved 5 条",
]

def _doc_stack() -> str:
    """The stack the documents actually use, read from the sheet that defines it.

    Restating it here is how the two drifted apart before; there is one source
    of truth and this reads it.
    """
    css = (ROOT / "assets" / "svg.css").read_text(encoding="utf-8")
    m = re.search(r"--sans:\s*(.+?);", css, re.S)
    return " ".join(m.group(1).split()) if m else "sans-serif"


DOC_STACK = _doc_stack()

#: Faces a reader may actually end up with. The table is calibrated on whichever
#: of these the machine resolves first, so the question that matters is not "is
#: the table exact" but "how far off is it on a face it was not calibrated on".
#: A single-font check would have answered the easy half.
PROBE_FACES = [
    ("document stack", DOC_STACK),
    ("Helvetica", "Helvetica, sans-serif"),
    ("Arial", "Arial, sans-serif"),
    ("Times (serif)", '"Times New Roman", Times, serif'),
    ("PingFang SC", '"PingFang SC", sans-serif'),
]

#: Kept for the corpus-only report.
FALLBACK = DOC_STACK


def probe_html(fs: int, face: str = None) -> str:
    payload = json.dumps(CORPUS, ensure_ascii=False)
    face = face or DOC_STACK
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  body {{ font-family: {face}; font-size: 16px; }}
  #out {{ white-space: pre; font-family: monospace; }}
</style></head><body>
<div id="out"></div>
<script>
var CORPUS = {payload};
var FS = {fs};
window.addEventListener('load', function () {{
  var body = getComputedStyle(document.body);
  var fam = body.fontFamily;
  var cv = document.createElement('canvas');
  var ctx = cv.getContext('2d');
  ctx.font = FS + 'px ' + fam;
  var rows = CORPUS.map(function (s) {{
    return {{ text: s, px: ctx.measureText(s).width, em: ctx.measureText(s).width / FS }};
  }});
  // Per-character advances for printable ASCII: one constant cannot describe a
  // face where 'M' is 0.71 em and 'i' is 0.28 em.
  var chars = {{}};
  for (var c = 32; c < 127; c++) {{
    var ch = String.fromCharCode(c);
    chars[ch] = ctx.measureText(ch).width / FS;
  }}
  // Figure text is not all one weight: node titles are 600, debug tags 700.
  var weights = {{}};
  [400, 600, 700].forEach(function (w) {{
    ctx.font = w + ' ' + FS + 'px ' + fam;
    weights[w] = CORPUS.map(function (s) {{ return ctx.measureText(s).width / FS; }});
  }});
  document.getElementById('out').textContent = JSON.stringify({{
    fontFamily: fam, fontFamilyUsed: ctx.font, size: FS,
    rows: rows, chars: chars, weights: weights
  }});
}});
</script></body></html>"""


def _probe_once(exe: str, fs: int, face: str, timeout: float) -> str:
    with tempfile.TemporaryDirectory(prefix="docforge-measure-") as tmp:
        page = pathlib.Path(tmp) / "probe.html"
        page.write_text(probe_html(fs, face), encoding="utf-8")
        proc = subprocess.Popen(
            [exe, *R.FLAGS, f"--user-data-dir={tmp}/prof",
             "--virtual-time-budget=8000", "--window-size=900,700",
             "--dump-dom", f"file://{page}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True,
        )
        try:
            return proc.communicate(timeout=timeout)[0]
        except subprocess.TimeoutExpired:
            # A browser left running holds the next probe's profile dir and
            # turns one slow run into a cascade of them.
            R._kill_group(proc)
            raise


def measure(fs: int, face: str = None, attempts: int = 3) -> dict:
    exe = R.find_browser()
    if not exe:
        raise SystemExit("no Chromium-family browser found; set DOCFORGE_BROWSER")
    last = None
    for attempt in range(attempts):
        try:
            out = _probe_once(exe, fs, face, timeout=90)
        except subprocess.TimeoutExpired as exc:
            last = exc
            print(f"  (probe timed out; retry {attempt + 1}/{attempts})",
                  file=sys.stderr)
            continue
        m = re.search(r'<div id="out">(.*?)</div>', out, re.S)
        if m:
            import html as _html
            return json.loads(_html.unescape(m.group(1)))
        last = RuntimeError("the probe produced no output")
    raise SystemExit(f"could not measure {face or 'the document stack'}: {last}")


def report(data: dict) -> int:
    fs = data["size"]
    print(f"font stack  : {data['fontFamilyUsed']}")
    print(f"measured at : {fs}px\n")
    print(f"  {'string':<40} {'real em':>8} {'est em':>8} {'err':>7} {'@14px':>7}")
    worst = []
    for row in data["rows"]:
        est = T.units(row["text"])
        err = est - row["em"]
        worst.append((abs(err), row["text"], row["em"], est, err))
        flag = "  <-- " if abs(err) * 14 > 2.0 else ""
        print(f"  {row['text'][:38]:<40} {row['em']:8.3f} {est:8.3f} "
              f"{err:+7.3f} {err * 14:+6.1f}px{flag}")
    worst.sort(reverse=True)
    print("\nworst offenders (error at 14px, vs the 2px tolerance):")
    for _, text, em, est, err in worst[:6]:
        print(f"  {text[:44]:<46} {err * 14:+6.1f}px")
    latin = [r for r in data["rows"]
             if all(ord(c) < T.CJK_MIN for c in r["text"]) and r["text"]]
    per_char = [r["em"] / len(r["text"]) for r in latin]
    if per_char:
        print(f"\n  Latin advance: mean {sum(per_char)/len(per_char):.4f} em, "
              f"min {min(per_char):.4f}, max {max(per_char):.4f} "
              f"(the estimate is {T.NARROW})")
    return 0


def calibrate(fs: int) -> dict:
    """Average the measured advances across every available face.

    A table fitted to the machine it was built on is only right on that machine.
    Documents are opened on machines the author never sees, so the table should
    minimise the worst case across plausible faces rather than be optimal on
    one -- the optimum-on-one table was 17px out on Arial.
    """
    per_face = []
    for label, stack in PROBE_FACES:
        try:
            per_face.append((label, measure(fs, stack)["chars"]))
        except SystemExit:
            continue
    if not per_face:
        raise SystemExit("no face could be measured")
    keys = sorted(set.intersection(*(set(c) for _, c in per_face)))
    return {k: sum(c[k] for _, c in per_face) / len(per_face) for k in keys}


def cross_face(fs: int) -> int:
    """How well does the table hold up on a face it was not calibrated on?"""
    print(f"\n=== the same estimate against {len(PROBE_FACES)} faces ===")
    print(f"  {'face':<18} {'resolved as':<34} {'median':>8} {'p95':>8} {'max':>8}")
    worst = 0.0
    for label, stack in PROBE_FACES:
        try:
            data = measure(fs, stack)
        except SystemExit:
            print(f"  {label:<18} (not available)")
            continue
        errs = sorted(abs((T.units(r["text"]) - r["em"]) * 14.0)
                      for r in data["rows"])
        n = len(errs)
        print(f"  {label:<18} {data['fontFamilyUsed'][:32]:<34} "
              f"{errs[n // 2]:8.2f} {errs[int(n * 0.95)]:8.2f} {errs[-1]:8.2f}")
        worst = max(worst, errs[-1])
    print(f"\n  worst case across all faces: {worst:.2f}px at 14px")
    print(f"  the checker's flat allowance is {DEFAULT_OVERFLOW_TOL if False else 2.0}px, "
          f"plus a per-character term")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--font", type=int, default=200, help="probe size in px")
    ap.add_argument("--json", help="write the raw measurements here")
    ap.add_argument("--faces", action="store_true",
                    help="also measure faces the table was not calibrated on")
    ap.add_argument("--emit-table",
                    help="write an averaged _ADVANCE table (across faces) here")
    args = ap.parse_args()
    data = measure(args.font)
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report(data)
    if args.emit_table:
        chars = calibrate(args.font)
        mean = sum(v for k, v in chars.items() if k != " ") / (len(chars) - 1)
        rows, line = [], []
        for ch in sorted(chars, key=ord):
            line.append(f"{json.dumps(ch)}: {chars[ch]:.4f}")
            if len(line) == 6:
                rows.append("    " + ", ".join(line) + ","); line = []
        if line:
            rows.append("    " + ", ".join(line) + ",")
        pathlib.Path(args.emit_table).write_text(
            f"NARROW = {mean:.4f}\n\n_ADVANCE = {{\n"
            + "\n".join(rows) + "\n}\n", encoding="utf-8")
        print(f"\nwrote an averaged table to {args.emit_table} "
              f"(fallback NARROW = {mean:.4f})")
    if args.faces:
        cross_face(args.font)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
