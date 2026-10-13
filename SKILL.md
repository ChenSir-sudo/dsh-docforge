---
name: docforge
description: 把物料（Markdown + JSON 图示规格）编译成一个自包含的单文件 HTML 文档，图示是内联 SVG，几何与文档结构由校验器自动检查。用于把技术方案、分析报告、教学讲义做成可交付、可打印、可换主题的网页。Use when the user wants to turn a document, plan, report, or write-up into a polished single-file HTML page with real diagrams — "做成网页 / 出一份带图的文档 / 生成报告页 / 做成课程页 / 把这个方案排成可交付的 HTML".
whenToUse: 当产出物是一个**要交付给他人的网页文档**，且里面需要**架构图、流程图、流转图、时序图、状态图**时使用。输入已经是 Markdown/JSON 或可以写成 Markdown 时最合适。若只要一段 HTML 片段、或需要联网/交互后端，不要用这个。
metadata:
  version: 1.0.0
  interface: INTERFACE.md
  entrypoint: bin/docforge
  python: ">=3.9, 仅标准库"
  schemas: 1
---

# docforge

**物料进，单文件 HTML 出。图示是内联 SVG，几何由校验器自动检查。**

这个 skill 的价值不在"能生成网页"，而在**生成完能自动证明它没画错**：每张图的每个盒子、每段文字、每条连线都记录了自己的包围盒，校验器会报出文字溢出、盒子重叠、连线穿过无关节点、标签压字、元素出界。你不用靠眼睛找问题。

## 0. 先做这一件事

```bash
$SKILL_DIR/bin/docforge skill-info --json
```

拿到能力清单：可用布局、主题、命令、退出码、校验错误码。**不要凭记忆猜接口**，这个 JSON 是权威的。

`python3` 指工作区里可用的 Python 3（≥3.9）。本 skill 只依赖标准库，不需要 pip 安装任何东西。

## 1. 快速路径

四步，每步都有可验证的产出：

```bash
# 1. 起一份物料骨架（doc / report / course 三选一）
$SKILL_DIR/bin/docforge init ./out --template doc

# 2. 改物料：out/material.md 写正文，out/figures/*.json 写图示
#    物料里用 ```figure <id> 引用图示

# 3. 只校验，不产出 —— 先让这一步干净
$SKILL_DIR/bin/docforge check ./out/material.md

# 4. 生成
$SKILL_DIR/bin/docforge build ./out/material.md -o ./out/index.html
```

**第 3 步不干净就不要进第 4 步。** 校验器报的每一条都能定位到具体图、具体节点。

### 迭代单张图

改图时不要每次都编译整篇文档：

```bash
$SKILL_DIR/bin/docforge fig ./out/figures/flow.json -o /tmp/flow.svg   # 看这一张
$SKILL_DIR/bin/docforge check ./out/figures/flow.json                   # 校这一张
$SKILL_DIR/bin/docforge fig ./out/figures/flow.json --png /tmp/f.png    # 人眼看（需浏览器）
```

## 1.5 语气：写给读者，不是写给自己

物料进、网页出，**排的是文档，不是聊天记录**。同一个意思，书面表达和口头表达在成品里的观感差距很大，而这一层是校验器查不出来的——它只能靠写的时候守住。

| 避免 | 改成 |
|---|---|
| 这一步的产出，我凭什么说它对了 | 这一步的产出依据什么标准判定为合格 |
| 死在模型上 / 死在流程上 | 失败发生在模型能力上 / 失败源于流程设计 |
| 顺手把 RAG 也接上 | 在同一阶段内顺带接入 RAG |
| 跑通再进下一步 | 通过验收后再进入下一阶段 |
| 这个东西 / 那玩意儿 | 该模块 / 该组件（或直接写名词） |
| 千万不要 / 绝对不能 | 不应 / 不可 |
| 一大堆 / 一堆 | 大量 / 多项 |

三条判断标准：

1. **能用陈述句就不用反问句。** 「凭什么说它对了」是自问，读者要的是标准。
2. **能用术语就不用比喻。** 「外脑」「手脚」「刹车」偶尔一次可以提神，通篇用就失去了精确性——正事仍然用「检索」「工具调用」「人工审批」。
3. **第一人称克制。** 「我建议」「你可以」在教程里成立，在方案文档里通常换成无主语陈述。

> [!NOTE]
> 这一条不适用于 `templates/course`（讲义）。讲义面向学习者，第二人称和设问是它的正常语气；判断基准是**这份物料最终给谁看**。

## 2. 物料格式

`material.md` = YAML front-matter + 受支持的 Markdown 子集。

```markdown
---
title: 通用 Agent 实战开发流程
eyebrow: Playbook · 完整落地版
theme: paper          # paper | midnight | contrast
numbering: auto       # auto：标题自动编号（一、/ 1. / [1] / 1.1 / [1]）
---

# 总体架构            ← auto 模式下渲染成「一、总体架构」

正文段落。

## 1. 三层能力模型     ← 渲染成「1. 三层能力模型」

```figure arch
@figures/arch.json
```

> [!KEY]
> 核心结论。
```

### 正文块

| 写法 | 产出 |
|---|---|
| `#` … `#####` | 五级标题。`numbering: auto` 时按 markdown-standard 阶梯自动编号 |
| 普通段落 | `<p>` |
| ` ```lang ` | 带语言标识的代码块 |
| ` ```figure <id> ` | 图示卡（图 N + 图名 + 类型 + SVG + 图注） |
| GFM 表格 | 表头 + 分隔行 + 数据行 |
| `-` / `1.` | 无序 / 有序列表，支持两层 |
| `> [!NOTE]` | 灰色补充说明 |
| `> [!KEY]` | 核心结论（主色引用块） |
| `> [!GOAL]` | 目标卡 |
| `> [!ACCEPT]` | 验收卡 |
| 行内 | `**粗体**`、`` `代码` ``、`[文字](链接)` |

### 图块两种写法

````markdown
```figure arch
@figures/arch.json
```

```figure quick
{ "layout": "pipeline", "nodes": [{"id":"a","title":"A"}], "edges": [] }
```
````

`@路径` 相对物料文件所在目录解析。图块里的 `<id>` 必须和 spec 的 `id` 一致。

## 2.5 嵌套：一个节点里放一张图

节点可以带 `sub_spec`——一份完整的图示规格。子图**按自己的固有尺寸**画进宿主节点里，不缩放（缩放会把字号一起缩掉），并且带自己的 id 命名空间，所以箭头不会串色。

```json
{"id": "retrieval", "title": "检索子系统",
 "sub_spec": {"id": "inner", "layout": "pipeline", "size": [560, 130],
   "nodes": [{"id": "q", "title": "查询"}, {"id": "r", "title": "检索"}],
   "edges": [{"from": "q", "to": "r"}]}}
```

三条要点：

1. **子规格应该自己声明 `size`**。不声明就按该引擎的默认宽度（通常 1200），塞进宿主里多半会超框。
2. **子图照常全量校验**。嵌套不是躲过校验的通道——里面的问题会带着路径浮上来，形如 `[host/retrieval] text-overflow: ...`。
3. **最多四层**。超过就报错，不会无限递归。

宿主节点由引擎正常摆位，`node_size` 会自动把它算成「标题 + 子图」，所以**所有布局引擎都能直接用嵌套**，不需要改引擎。

## 3. 图示格式

一个 spec 是一个 JSON 对象。**引擎负责摆位，spec 负责内容**——你不需要算坐标。

```json
{
  "id": "flow",
  "layout": "pipeline",
  "title": "主流程",
  "kind": "流程图",
  "size": [1200, 220],
  "nodes": [
    {"id": "in",  "title": "输入解析", "sub": ["raw input"]},
    {"id": "cls", "title": "意图识别", "sub": ["LLM 输出"], "kind": "indigo"},
    {"id": "out", "title": "输出", "sub": ["final_answer"], "kind": "green"}
  ],
  "edges": [{"from": "in", "to": "cls", "label": "解析"}],
  "options": {"y": 60, "margin": 60}
}
```

### 节点

| 字段 | 说明 |
|---|---|
| `id` | 必填，唯一 |
| `title` | 主标题 |
| `sub` | 副标题，字符串或数组（多行） |
| `kind` | `default` / `line` / `indigo` / `teal` / `amber` / `red` / `green` / `violet` / `slate` / `ink` |
| `as_card` | 渲染成清单卡，配 `items` / `accent` / `sub` |
| `item_code` | 卡片里的 `items` 是标识符（字段名、函数名）时置 `true`：等宽字体 + 次一级颜色，与标题拉开层级 |
| `as_chip` | 渲染成胶囊标签 |
| `x` `y` `width` `height` | **可选**，显式覆盖引擎摆位 |

**宽度是从文字算出来的。** 不要手写宽度，除非要强制对齐。

### 布局引擎

| layout | 用来画 | 关键 options |
|---|---|---|
| `pipeline` | 横排链条，超宽自动折行成蛇形 | `y` `gap` `margin` `rows` |
| `dag` | 分层有向图，菱形、合流都对 | `center_sinks` `gap_x` `gap_y` `channel` |
| `matrix` | 行×列表格，格子按 `level` 分档着色 | `row_labels` `col_labels` `cell_w` `cell_h` `corner`（必填 `nodes[].row` / `nodes[].col`） |
| `timeline` | 泳道 + 时间条，共用一根轴 | `axis` `row_labels` `row_h` `bar_h`（必填 `nodes[].row` / `.start` / `.end`） |
| `funnel` | 逐级收窄的梯形 | `stage_h` `min_ratio` `drop_labels`（节点按顺序堆叠） |
| `fan` | 左侧一条链 → 一个枢纽 → 右侧 N 个分支 | `prefix` `source` `targets` `labels` `reach` |
| `layers` | 分层容器带，每带一行/一列 | `groups`（必填）`label_h` `band_gap` |
| `hub` | 中心节点 + 左右两列卫星 + 一个下方节点 | `center` `left` `right` `below` |
| `ring` | 环形闭环，弧线顺连 | `rx` `ry` `gap_deg` `center` |
| `sequence` | 泳道 + 消息 | `lanes` `messages` `activations`（必填 lanes/messages） |
| `state` | 状态网格 + 带标签迁移 | `rows` `transitions`（必填 rows） |
| `grid` | 等宽网格，放指标卡 | `cols` `as_card` `fill` |
| `free` | 完全显式坐标 | 你自己给 `x`/`y` 和 `connectors[].pts` |

每个 layout 的必填项记不住就问：

```bash
$SKILL_DIR/bin/docforge layouts
$SKILL_DIR/bin/docforge layouts --json
```

### 手工微调的两个逃生口

- 节点加 `x`/`y`/`width`/`height` 覆盖自动摆位；
- `free` 布局下用 `connectors: [{"pts": [[x,y],[x,y]], "label": "…"}]` 完全手动布线。

`notes` 可以在任意位置补文字、胶囊、图例、水平分隔线：

```json
"notes": [
  {"type": "text", "x": 50, "y": 380, "text": "兜底分支必须存在", "cls": "d-fig-t"},
  {"type": "tag",  "x": 300, "y": 20, "text": "阶段一"},
  {"type": "legend", "x": 50, "y": 560, "entries": [["indigo", "内核层"], ["teal", "外壳层"]]},
  {"type": "hline", "x": 50, "y": 300, "x2": 1150, "dashed": true}
]
```

### 声明"这个节点就是孤立的"

分层图里常有独立节点。**别去压制校验，直接声明**：

```json
"options": {"allow_isolated": ["security"]}
```

## 4. 校验契约

`check` 和 `build` 都会跑校验。退出码：`0` 干净、`1` 校验未通过、`2` 用法/IO 错、`3` 内部错。

```bash
$SKILL_DIR/bin/docforge check ./out/material.md --format json   # 机器可读
$SKILL_DIR/bin/docforge check ./out/material.md --fail-on warning
```

### 错误 —— 必须改

| code | 含义 | 怎么改 |
|---|---|---|
| `text-overflow` | 文字比盒子宽 | 缩短文案，或加 `width`，或拆成两行 `sub` |
| `box-overlap` | 两个盒子相交 | 调 `gap` / `margin` / `size`，或换 layout |
| `edge-over-label` | 一条连线从**别人的**标签文字上穿过 | 挪标签坐标（`lx`/`ly`），或给连线加 `pts` 绕开 |
| `embed-overflow` | 嵌套子图比宿主给它的内容区大 | 给子规格声明更小的 `size`，或别给宿主写死 `width`/`height` |
| `label-collision`（图注） | 一段图注压到了分层带的**表头**上 | 把图注移出带外（通常给 `options.y` 留出表头条），或删掉它 |
| `edge-through` | 连线穿过无关节点 | 改 layout，或给这条边 `out`/`into`/`channel`/`pts` |
| `label-collision` | 标签压在盒子或别的标签上 | 给边显式 `lx`/`ly`，或去掉这条标签 |
| `out-of-canvas` | 元素出界 | 去掉 `size` 让它自适应，或调大 `size` |
| `degenerate-edge` | 连线长度为 0 | 检查边两端是不是同一个节点 |
| `connector-detached` | ⚠️ 警告：箭头的落点离它声称连的节点超过 12px | 端点坐标写错了；箭头其实指向空白 |
| `toc-anchor-missing` | 目录条目指向的标题不存在 | 通常说明物料被改坏了 |

### 警告 —— 需要判断

| code | 含义 | 怎么处理 |
|---|---|---|
| `edge-crossing` | 两条连线交叉 | 能改就改；确实必要就接受 |
| `isolated-node` | 节点没有任何连线 | 是故意的话用 `allow_isolated` 声明 |
| `band-overlap` | 两个容器带相交 | 调 `band_gap`；若是有意为之（侧栏压在分层带上），用 `options.allow_band_overlap` 声明 |
| `no-figures` | 整篇文档一张图都没有 | 如果本来就不需要图，忽略 |
| `connector-detached` | 箭头的落点离目标节点超过 12px（约一个箭头长） | 修正端点坐标；`from` 端不检查，因为扇出的支线本来就从空中主干出发 |
| `label-clearance`、`edge-overlap`、`short-connector` | 两个盒子之间不足 12px，连线根本画不出来 | 拉开间距（`gap` / `y` / `size`）；这个警告是"校验器唯一能替你发现盒子挨太紧"的地方 |

### 文档级

| code | 含义 |
|---|---|
| `unresolved-figure` | 图块占位符没被替换 |
| `unresolved-token` | 模板变量残留 |
| `tag-imbalance` | 标签未闭合 |
| `figure-count` | 声明的图数和实际渲染的对不上 |
| `duplicate-id` | 元素 id 重复 |
| `dangling-anchor` | 链接指向不存在的锚点 |
| `figure-missing` | 图块声明了但文档里没渲染出来 |
| `figure-spec-missing` | `@路径` 指向的 spec 文件不存在 |
| `figure-spec-invalid` | spec 文件存在但内容不合法（报错里带原因） |
| `figure-render-failed` | spec 合法但渲染时抛错 |
| `toc-anchor-missing` | 目录条目指向的标题不存在 |

这些一律是错误，通常意味着图块 `id` 和 spec 的 `id` 对不上，或 `@路径` 写错了。

## 5. 主题

```bash
$SKILL_DIR/bin/docforge themes
```

| 主题 | 观感 |
|---|---|
| `paper` | 浅色纸面 + 靛蓝，默认 |
| `midnight` | 冷色深底 + 青色 |
| `contrast` | 高对比，面向无障碍与打印 |

主题是 JSON，`light` / `dark` 两份 token 必须键名一致（`Theme.missing()` 会验证）。**文档里的 SVG 没有写死任何颜色**，全靠 CSS 变量，所以换主题时图和正文一起换。想加自己的主题，照 `themes/paper.json` 复制一份改色值即可。

生成的 HTML 自带浅色/深色切换按钮。

## 6. 截图（可选）

自动校验**不需要浏览器**。只有你想人眼看渲染结果时才需要。

```bash
$SKILL_DIR/bin/docforge shot ./out/index.html /tmp/shot.png --width 1440 --height 2400 --scale 2
```

没装 Chromium 系浏览器时会明确报错并给出 `DOCFORGE_BROWSER` 环境变量，不会假装成功。

并发截图会用一把进程间锁串行化 —— 多个 agent 同时截图不会互相把对方拖超时。
所以**不要为了"快点"并行跑多个 `shot`**，它们会排队。

**截图只能从页面顶部拍**。要看后半部分，按一级章节把内容单独成页再拍。

## 7. 命令速查

```
docforge build   <material.md> [-o out.html] [--theme] [--numbering auto|manual]
                 [--no-toc] [--fail-on error|warning|none] [--format text|json]
docforge fig     <figure.json> [-o out.svg] [--png out.png] [--mode light|dark] [--inline]
docforge check   <figure.json|material.md>... [--fail-on] [--format] [--clearance N]
docforge init    <dir> [--template doc|report|course] [--force]
docforge themes | layouts | examples [--json]
docforge shot    <in.html> <out.png> [--width] [--height] [--scale] [--timeout N]
docforge skill-info [--json]
```

## 8. 常见坑

1. **图块 id 和 spec 的 id 不一致** → `figure-missing`。两处都要改。
2. **`@figures/x.json` 路径写错** → `figure-spec-missing`；文件在但内容不合法 → `figure-spec-invalid`，报错里带具体原因。路径相对物料文件。
3. **节点没被 layout 用上** → 渲染时直接报错并列出节点名。检查 `options` 里是否漏了这个 id（`fan` 的 `prefix`/`source`/`targets`、`hub` 的 `left`/`right`、`layers` 的 `groups`）。
4. **手写宽度** → 没必要，还容易溢出。让引擎按文字算。
5. **`size` 写小了** → `out-of-canvas`。不确定就别写 `size`，让它自适应高度。
6. **文字溢出** → 中文按 1.0 em、拉丁按 0.55 em 估算。关键词太长就拆 `sub`。
7. **用 `grid` 放非卡片节点** → 记得 `as_card: true`，否则按普通节点渲染宽度会不一致。
8. **`sequence` 的 `lanes` id 和 `messages` 的 `from`/`to` 对不上** → spec 校验会直接拦下来。

## 9. 更完整的契约

`INTERFACE.md` 里有全部函数签名、`Scene`/`Item`/`Plan` 数据结构、校验器实现细节、扩展新 layout 的方法。要改这个 skill 本身时读它。

## 10. 质量与测试

这一层是给改这个 skill 的人看的。**测试不是可选项**——校验器的每条规则、每个布局引擎、
每段 HTML 结构都有对应的用例，改坏了会当场红。

```bash
sh tools/test.sh          # 全部单测 + 端到端（约 5 秒，不需要联网或浏览器）
```

`tools/test.sh` 是 POSIX sh 脚本，**不要用 `python3` 调它**。

几条被测试守住的不变量：

- **每个校验码都要在 `SKILL.md` 里有名字**（`tests/test_docs.py`）。新增一条检查却忘了写文档，测试会失败。
- **同一份物料构建两次必须逐字节相同**（`tests/test_e2e.py`）。任何时间戳、字典序、随机数都会让它红。
- **代码块高亮必须无损**：剥掉标签后要精确还原原文（`tests/test_highlight.py`）。
- **图示里的 SVG 不许出现写死的颜色**，否则换主题时会花掉。
