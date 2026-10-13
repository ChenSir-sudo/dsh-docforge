"""Command line interface.

Every capability of docforge is reachable from here, and every command speaks
both human text and JSON. That is what makes the package usable by another
agent (or a plugin wrapper) without importing Python.

Exit codes
----------
0   success, nothing found
1   validation failed
2   usage or I/O error
3   internal error
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import SCHEMA_VERSION, TEMPLATES, __version__, layouts, specs
from . import validate as V
from .theme import Theme, ThemeError

EXIT_OK, EXIT_VALIDATION, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3

LAYOUT_DOC = {
    "pipeline": "横排链条，超宽自动折行成蛇形；适合主流程、阶段推进",
    "tree": "层级树，父节点居中于子节点；适合目录、分类、组织架构",
    "matrix": "行×列表格，格子按 level 分档着色；适合优先级矩阵、热力图、覆盖表",
    "timeline": "泳道 + 时间条，按同一根轴定位；适合排期、路线图、里程碑",
    "funnel": "逐级收窄的梯形，宽度随数值变化；适合转化漏斗、筛选收敛",
    "dag": "分层有向图，菱形/合流都能画；按最长路径分列，边自动布线",
    "fan": "左侧一个源节点，右侧 N 个目标节点，共用一条竖脊分叉；适合意图路由",
    "grid": "等宽网格排布卡片或节点；适合指标卡、场景列表",
    "layers": "自上而下的容器带，每带内一行或一列节点；适合分层架构",
    "hub": "中心节点 + 左右两列卫星，可挂一个下方节点；适合约束清单",
    "ring": "环形闭环，节点按角度分布，弧线顺连；适合飞轮、循环",
    "sequence": "泳道 + 消息；适合 API 时序、请求生命周期",
    "state": "状态网格 + 带标签的迁移；适合状态机、生命周期",
    "free": "完全显式坐标，手工精调图的逃生通道",
}

TPL_KIND = {
    "text": "散文段落",
    "code": "带语言标识的代码块",
    "table": "GFM 表格",
    "list": "有序 / 无序列表",
    "quote": "引用块与提示（[!NOTE] [!KEY] [!GOAL] [!ACCEPT]）",
    "figure": "```figure <id> 图块，内联 JSON 或引用 .json 文件",
}


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docforge",
        description="物料 → 单文件 HTML 文档（含手绘级内联 SVG 图示）",
    )
    p.add_argument("--version", action="version",
                   version=f"docforge {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="把物料编译成单文件 HTML")
    b.add_argument("material", help="物料 .md（Markdown + front-matter）")
    b.add_argument("-o", "--out", help="输出路径（默认与物料同名 .html）")
    b.add_argument("--theme", default=None)
    b.add_argument("--numbering", choices=("auto", "manual"), default=None)
    b.add_argument("--no-toc", action="store_true")
    b.add_argument("--no-dark", action="store_true")
    b.add_argument("--fail-on", choices=("error", "warning", "none"), default="error")
    b.add_argument("--format", choices=("text", "json"), default="text")
    b.add_argument("-q", "--quiet", action="store_true")

    f = sub.add_parser("fig", help="渲染单张图为 SVG / PNG")
    f.add_argument("figure")
    f.add_argument("-o", "--out", help="输出 .svg（默认 stdout）")
    f.add_argument("--theme", default="paper")
    f.add_argument("--mode", choices=("light", "dark"), default="light")
    f.add_argument("--inline", action="store_true",
                   help="输出内联片段而不是独立 .svg 文件")
    f.add_argument("--png", help="同时导出 PNG（需要浏览器）")
    f.add_argument("--width", type=int, default=1400)
    f.add_argument("--scale", type=float, default=2.0)
    f.add_argument("--check", action="store_true", default=True)
    f.add_argument("--no-check", dest="check", action="store_false")
    f.add_argument("--fail-on", choices=("error", "warning", "none"), default="error")
    f.add_argument("--format", choices=("text", "json"), default="text")
    f.add_argument("-q", "--quiet", action="store_true",
                   help="只输出 SVG，不打印校验报告")

    c = sub.add_parser("check", help="只校验，不产出")
    c.add_argument("targets", nargs="+", help="figure .json 或 material .md")
    c.add_argument("--fail-on", choices=("error", "warning", "none"), default="error")
    c.add_argument("--format", choices=("text", "json"), default="text")
    c.add_argument("--no-crossings", action="store_true",
                   help="不报告连线交叉（warning）")
    c.add_argument("--clearance", type=float, default=1.0)

    i = sub.add_parser("init", help="生成一份起始物料")
    i.add_argument("dir")
    i.add_argument("--template", default="doc", metavar="NAME",
                   help="起始模板：" + "/".join(sorted(t.name for t in TEMPLATES.iterdir()
                                                       if t.is_dir())) + "（默认 doc）")
    i.add_argument("--force", action="store_true")

    t = sub.add_parser("themes", help="列出主题")
    t.add_argument("--json", action="store_true")

    l = sub.add_parser("layouts", help="列出布局引擎")
    l.add_argument("--json", action="store_true")

    s = sub.add_parser("shot", help="用无头浏览器截图（可选能力）")
    s.add_argument("html")
    s.add_argument("png")
    s.add_argument("--width", type=int, default=1440)
    s.add_argument("--height", type=int, default=2400)
    s.add_argument("--scale", type=float, default=2.0)
    s.add_argument("--browser", default=None)
    s.add_argument("--timeout", type=int, default=180,
                   help="秒；整次截图的死线，含排队等待（默认 180）")

    e = sub.add_parser("examples", help="列出随包示例")
    e.add_argument("--json", action="store_true")

    si = sub.add_parser("skill-info", help="机器可读的能力描述")
    si.add_argument("--json", action="store_true")
    return p


# --------------------------------------------------------------------------
def _emit(payload, fmt, human, quiet=False, stream=None):
    stream = stream or sys.stdout
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)
    elif not quiet:
        print(human, file=stream)
    return payload


def _findings_payload(findings, extra=None):
    out = {"summary": V.summarize(findings),
           "findings": [f.as_dict() for f in findings]}
    if extra:
        out.update(extra)
    return out


# --------------------------------------------------------------------------
def cmd_fig(args) -> int:
    try:
        spec = specs.load(args.figure)
    except specs.SpecError as exc:
        print(f"docforge: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        scene = specs.render(spec)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user
        print(f"docforge: failed to render {args.figure}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    findings = V.check_scene(scene, check_crossings=True) if args.check else []
    try:
        theme = Theme.load(args.theme)
    except ThemeError as exc:
        print(f"docforge: {exc}", file=sys.stderr)
        return EXIT_USAGE

    svg = (scene.svg(standalone=True, palette=theme.palette(args.mode),
                     svg_css=theme.svg_css())
           if not args.inline else scene.svg())

    # `docforge fig x.json > f.svg` must produce a clean SVG, so when the markup
    # goes to stdout the report goes to stderr instead of corrupting the stream.
    if args.out:
        Path(args.out).write_text(svg)
        report_stream = sys.stdout
    else:
        sys.stdout.write(svg if svg.endswith("\n") else svg + "\n")
        report_stream = sys.stderr

    png_note = None
    if args.png:
        from . import render as R
        if not R.available():
            png_note = "skipped PNG: no Chromium-family browser found"
        else:
            tmp = Path(args.out).with_suffix(".svg") if args.out else None
            if tmp:
                tmp.write_text(svg)
                R.shot(tmp, args.png, width=args.width,
                       height=int(scene.height * args.width / scene.width) + 40,
                       scale=args.scale)
            else:
                R.shot_data_url(svg, args.png, width=args.width, scale=args.scale)
            png_note = f"png -> {args.png}"

    payload = _findings_payload(findings, {
        "figure": spec["id"], "layout": spec["layout"],
        "size": [scene.width, scene.height],
        "output": args.out, "png": args.png, "png_note": png_note,
    })
    if args.format == "json":
        _emit(payload, "json", "", stream=report_stream)
    else:
        tail = f"  ({png_note})" if png_note else ""
        _emit(payload, "text",
              f"{spec['id']}: {scene.width:g}x{scene.height:g}, "
              f"{len(scene.items)} items -> {args.out or 'stdout'}{tail}\n"
              + V.format_text(findings),
              quiet=args.quiet, stream=report_stream)
    return EXIT_VALIDATION if V.should_fail(findings, args.fail_on) else EXIT_OK


def cmd_check(args) -> int:
    findings, checked = [], []
    for target in args.targets:
        path = Path(target)
        if path.suffix.lower() in (".md", ".markdown"):
            try:
                findings += _check_material(path, args)
            except Exception as exc:  # noqa: BLE001
                print(f"docforge: {target}: {exc}", file=sys.stderr)
                return EXIT_INTERNAL
            checked.append(target)
            continue
        try:
            spec = specs.load(target)
        except specs.SpecError as exc:
            print(f"docforge: {exc}", file=sys.stderr)
            return EXIT_USAGE
        findings += V.check_scene(
            specs.render(spec), clearance=args.clearance,
            check_crossings=not args.no_crossings)
        checked.append(target)
    payload = _findings_payload(findings, {"checked": checked})
    _emit(payload, args.format, V.format_text(findings))
    return EXIT_VALIDATION if V.should_fail(findings, args.fail_on) else EXIT_OK


def _check_material(path: Path, args):
    """Render every figure in a material and validate it, without writing HTML."""
    from . import markdown as md
    from . import specs as sp
    doc = md.parse_file(path)
    out = []
    for ref in getattr(doc, "figures", []) or []:
        spec, problem = _resolve_figure_spec(ref, path.parent)
        if spec is None:
            code = ("figure-spec-missing"
                    if problem and "not found" in problem else "figure-spec-invalid")
            out.append(V.Finding(code, V.ERROR, problem or "unresolvable figure",
                                 figure=ref.id))
            continue
        try:
            scene = sp.render(spec)
        except Exception as exc:  # noqa: BLE001
            out.append(V.Finding("figure-render-failed", V.ERROR, str(exc),
                                 figure=ref.id))
            continue
        out += V.check_scene(scene, clearance=args.clearance,
                             check_crossings=not args.no_crossings)
    return out


def _resolve_figure_spec(ref, base: Path):
    """Resolve a figure ref to ``(spec, error)``.

    A ref is an inline spec, a ``@path``, or a bare id. Exactly one of the two
    return values is set. The error is the *reason* — "the file is not there" and
    "the file is not a valid spec" are different problems and deserve different
    codes, because they need different fixes.
    """
    source = getattr(ref, "source", None)
    if source is None:                      # tolerate a plain dict
        payload = getattr(ref, "spec_or_path", None)
        if isinstance(payload, dict):
            try:
                return specs.normalize(dict(payload)), None
            except specs.SpecError as exc:
                return None, str(exc)
        return None, "figure ref has no spec"

    if source == "spec":
        try:
            payload = dict(ref.spec)
        except ValueError as exc:
            return None, f"inline spec is not valid JSON: {exc}"
        # the fence id is authoritative, so an inline spec need not repeat it
        payload.setdefault("id", ref.id)
        try:
            return specs.normalize(payload), None
        except specs.SpecError as exc:
            return None, f"inline spec is invalid: {exc}"

    if source == "path":
        target = Path(ref.spec_or_path)
        if not target.is_absolute():
            target = base / target
        if not target.is_file():
            return None, f"spec file not found: {target}"
        try:
            return specs.load(target), None
        except specs.SpecError as exc:
            return None, str(exc)
    return None, f"figure {ref.id!r} has no spec and no path"


def cmd_build(args) -> int:
    from . import document, markdown as md

    material = Path(args.material)
    if not material.is_file():
        print(f"docforge: no such material: {material}", file=sys.stderr)
        return EXIT_USAGE
    if material.suffix.lower() not in (".md", ".markdown"):
        # Parsing a .json as material would "succeed" and emit the JSON as
        # escaped prose -- a wrong page with exit 0, which is worse than a stop.
        print(f"docforge: material must be Markdown, not {material.suffix or 'a bare file'}"
              f": {material}", file=sys.stderr)
        return EXIT_USAGE
    try:
        doc = md.parse_file(material)
    except Exception as exc:  # noqa: BLE001
        print(f"docforge: cannot parse {material}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    theme_name = args.theme or doc.meta.get("theme") or "paper"
    try:
        theme = Theme.load(theme_name)
    except ThemeError as exc:
        print(f"docforge: {exc}", file=sys.stderr)
        return EXIT_USAGE

    findings = []
    figures = {}
    ids = []
    for ref in getattr(doc, "figures", []) or []:
        ids.append(ref.id)
        spec, problem = _resolve_figure_spec(ref, material.parent)
        if spec is None:
            code = ("figure-spec-missing"
                    if problem and "not found" in problem else "figure-spec-invalid")
            findings.append(V.Finding(code, V.ERROR, problem or "unresolvable figure",
                                      figure=ref.id))
            figures[ref.id] = _error_box(f"图示不可用：{ref.id}")
            continue
        _enrich_ref(ref, spec)
        try:
            scene = specs.render(spec)
        except Exception as exc:  # noqa: BLE001
            findings.append(V.Finding("figure-render-failed", V.ERROR, str(exc),
                                      figure=ref.id))
            figures[ref.id] = _error_box(f"图示渲染失败：{ref.id}")
            continue
        findings += V.check_scene(scene)
        figures[ref.id] = scene.svg()

    numbering = args.numbering or doc.meta.get("numbering") or "auto"
    html = document.render(
        doc, figures, theme,
        numbering=numbering,
        dark=not args.no_dark,
        toc=not args.no_toc,
    )
    findings += V.check_document(html, figure_ids=ids)

    out = Path(args.out) if args.out else material.with_suffix(".html")
    out.write_text(html)

    payload = _findings_payload(findings, {
        "output": str(out),
        "bytes": out.stat().st_size,
        "figures": len(ids),
        "theme": theme.name,
        "numbering": numbering,
    })
    if args.format == "json":
        _emit(payload, "json", "")
    else:
        _emit(payload, "text",
              f"{out}  ({out.stat().st_size / 1024:.0f} KB, {len(ids)} 图, "
              f"主题 {theme.name})\n" + V.format_text(findings),
              quiet=args.quiet)
    return EXIT_VALIDATION if V.should_fail(findings, args.fail_on) else EXIT_OK


def _enrich_ref(ref, spec) -> None:
    """Fill the card's metadata from the spec.

    A ``@figures/x.json`` fence cannot know the figure's title — only the spec
    does. An explicit fence-level value always wins over the spec's.
    """
    for attr, key in (("name", "title"), ("kind", "kind"), ("caption", "caption")):
        if not getattr(ref, attr, "") and spec.get(key):
            setattr(ref, attr, spec[key])


def _error_box(message: str) -> str:
    # Classed, not coloured: the stylesheet owns every colour in a figure, so
    # this placeholder has to obey the theme like the diagrams do.
    return ('<svg class="dg" viewBox="0 0 600 80" '
            'xmlns="http://www.w3.org/2000/svg" role="img">'
            f'<rect class="d-errbox" x="1" y="1" width="598" height="78" rx="10"/>'
            f'<text class="d-errtext" x="300" y="44" text-anchor="middle" '
            f'font-size="14">{message}</text></svg>')


def cmd_init(args) -> int:
    target = Path(args.dir)
    src = TEMPLATES / args.template
    if not src.is_dir():
        # templates are just folders, so a user-added one is valid too: only
        # complain about a name that matches nothing on disk.
        available = ", ".join(sorted(t.name for t in TEMPLATES.iterdir() if t.is_dir()))
        print(f"docforge: no such template {args.template!r} "
              f"(available: {available})", file=sys.stderr)
        return EXIT_USAGE
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"docforge: {target} is not empty (use --force)", file=sys.stderr)
        return EXIT_USAGE
    target.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        dest = target / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
    print(f"created {target} from template {args.template!r}")
    print("next:  docforge build " + str(target / "material.md"))
    return EXIT_OK


def cmd_themes(args) -> int:
    themes = Theme.available()
    if args.json:
        print(json.dumps([{
            "name": t.name, "label": t.label, "description": t.description,
            "tokens": len(t.light), "missing": t.missing(),
        } for t in themes], ensure_ascii=False, indent=2))
        return EXIT_OK
    for t in themes:
        print(f"{t.name:12} {t.label:8} {t.description}")
    return EXIT_OK


def cmd_layouts(args) -> int:
    payload = [{"name": k, "what": LAYOUT_DOC.get(k, "")}
               for k in sorted(layouts.LAYOUTS)]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK
    for row in payload:
        print(f"{row['name']:10} {row['what']}")
    return EXIT_OK


def cmd_shot(args) -> int:
    from . import render as R
    try:
        # `--timeout` is the whole operation's deadline, not just the browser's:
        # waiting behind another screenshot is the same experience for the
        # caller as the browser being slow, so both are bounded by it.
        out = R.shot(args.html, args.png, width=args.width, height=args.height,
                     scale=args.scale, browser=args.browser,
                     timeout=args.timeout, wait_for_lock=args.timeout)
    except R.RenderError as exc:
        print(f"docforge: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"wrote {out}")
    return EXIT_OK


def cmd_examples(args) -> int:
    root = Path(__file__).resolve().parent.parent / "examples"
    items = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if args.json:
        print(json.dumps({"root": str(root), "examples": items},
                         ensure_ascii=False, indent=2))
        return EXIT_OK
    print(f"examples in {root}:")
    for name in items:
        print(f"  {name}")
    return EXIT_OK


def cmd_skill_info(args) -> int:
    from . import render as R
    payload = {
        "name": "docforge",
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "summary": "物料 → 单文件 HTML 文档（含手绘级内联 SVG 图示），"
                   "自带几何与文档自动校验",
        "entrypoint": "python3 -m docforge.cli",
        "python": ">=3.9, standard library only",
        "optional": {
            "screenshot": {
                "available": R.available(),
                "why": "只在需要人眼看渲染结果时使用；自动校验不需要浏览器",
                "env": "DOCFORGE_BROWSER",
            },
        },
        "layouts": [{"name": k, "what": LAYOUT_DOC.get(k, "")}
                    for k in sorted(layouts.LAYOUTS)],
        "themes": [{"name": t.name, "label": t.label,
                    "description": t.description} for t in Theme.available()],
        "commands": {
            "build": "物料 -> 单文件 HTML",
            "fig": "figure.json -> SVG / PNG",
            "check": "只校验图示与文档，不产出",
            "init": "生成起始物料（doc / report / course）",
            "themes": "列出主题",
            "layouts": "列出布局引擎",
            "shot": "无头浏览器截图",
            "examples": "列出随包示例",
            "skill-info": "本描述",
        },
        "exit_codes": {
            "0": "成功",
            "1": "校验未通过",
            "2": "用法或 IO 错误",
            "3": "内部错误",
        },
        "materials": {
            "document": "markdown + YAML front-matter；正文块：" + "、".join(TPL_KIND.values()),
            "figure": "JSON，字段 id/layout/title/size/nodes/edges/options/notes",
        },
        "validation": {
            "errors": list(V.ERROR_CODES),
            "warnings": list(V.WARNING_CODES),
            "contract": "INTERFACE.md",
            "fail_on": {
                "error": "只有 error 让构建失败（默认）",
                "warning": "任何 finding 都失败",
                "none": "只报告，不影响退出码",
            },
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['name']} {payload['version']}  (schema v{SCHEMA_VERSION})")
        print(payload["summary"])
        print(f"layouts: {', '.join(l['name'] for l in payload['layouts'])}")
        print(f"themes : {', '.join(t['name'] for t in payload['themes'])}")
        print(f"screenshot: {'yes' if payload['optional']['screenshot']['available'] else 'no'}")
        print("run `docforge skill-info --json` for the machine-readable form")
    return EXIT_OK


COMMANDS = {
    "build": cmd_build, "fig": cmd_fig, "check": cmd_check, "init": cmd_init,
    "themes": cmd_themes, "layouts": cmd_layouts, "shot": cmd_shot,
    "examples": cmd_examples, "skill-info": cmd_skill_info,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.cmd](args)
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK
    except KeyboardInterrupt:  # pragma: no cover
        return EXIT_INTERNAL
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        print(f"docforge: internal error: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
