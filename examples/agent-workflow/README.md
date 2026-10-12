# agent-workflow — 通用 Agent 实战开发流程

这是 docforge 的旗舰示例：把一份已经设计好的长文档（十三阶段、17 张图示）整体移植成
「Markdown 物料 + JSON 图示规格」，并做到 `docforge check` **0 error、0 warning**。

它演示的是**按图选引擎**，而不是用 `free` 硬啃：17 张图里 8 张交给布局引擎
（`fan` / `hub` / `sequence` / `state` / `layers` / `ring`），9 张因为形状特殊退到
`free` 显式坐标。每一次退让都有具体理由（见下），而且每张图的每个盒子、每段文字、
每条连线都由校验器证明过：文字不溢出、盒子不重叠、连线不穿无关节点、箭头真的落在
它声明指向的节点上。`material.md` 里没有任何原始 HTML——卡片网格 `.cards` 按
`SKILL.md` §2 的子集改写成**普通列表**（阶段零的「五类事实」、阶段三的「数据底座预留」），
只有本来就该是图的内容才留成图。

## 各图选用的布局

| 图 | 内容 | 引擎 | 为什么 |
|---|---|---|---|
| 1 | 三层能力模型 | `free` | 左侧一条「贯穿标识」轨与三个分层带**并排**，`layers` 只能上下叠带，无法在带旁再放一列 |
| 2 | 十三阶段演进路线 | `free` | 三行蛇形回头线（「换层」）要在带与带之间的空隙里走线，`pipeline` 的自动折行画不出跨带回头 |
| 3 | Agent 内核主流程 | `free` | 两条支路从条件路由**向上**绕行再汇入结果生成；`dag` 的最长路径分层会把支路排到结果生成之后 |
| 4 | 意图识别与条件路由 | `fan` | 一条链 → 一个枢纽 → 四条分支，正是 `fan` 的形状 |
| 5 | 知识获取条件子流程 | `free` | 带内的重写回环（相关性评分 → 查询重写 → 检索）+ 底部一排预留字段，`layers` 表达不了同一带内的回边 |
| 6 | 工具执行节点的约束 | `hub` | 中心节点 + 左右两列卫星 + 一个下方节点（审计留痕），与 `hub` 完全对应 |
| 7 | 自省与迭代控制 | `free` | 三条出口 + 一条 refine 回边，回边要绕到图下方再回到结果生成，`dag` 的自动布线会穿过出口节点 |
| 8 | 后端 API 端到端时序 | `sequence` | 泳道 + 消息 + 自调用 + 激活条，标准的时序图 |
| 9 | 任务生命周期状态机 | `state` | 状态网格 + 带标签迁移，`rows` 正好是三行网格 |
| 10 | 数据底座 | `free` | 三张服务卡 + 五张不同高度的清单卡，`grid` 强制等高且会在横向上溢出画布 |
| 11 | 持久化队列与任务编排 | `free` | 主链之外挂死信队列与 Scheduler，两条回边（ack、重新入队）要各自走独立通道 |
| 12 | 前端与人工介入闭环 | `free` | 左右两个并排面板（`layers` 只能上下叠），底部还有一条验收路径链 |
| 13 | 安全与多租户纵深防御 | `free` | 三道闸门横向串联 + 一条横向拦截线 + 底部四张配套卡 |
| 14 | 三层评估与 CI 门禁 | `free` | `layers` 用 `node_size` 量卡片，量出的高度装不下卡片实际内容（会 `text-overflow`） |
| 15 | 数据飞轮 | `ring` | 六个节点沿椭圆顺时针闭环，`ring` 天生就是画飞轮的 |
| 16 | 部署拓扑与可观测 | `layers` | 三条自上而下的职责带（服务 / 数据 / 可观测），各带内部再分行 |
| 17 | 灰度发布与回滚 | `free` | 放量链 + 观测指标回路 + 回滚支路 + 发布前准备的分组框，`dag` 无法表达分组框 |

9 张 `free` 图的坐标不是凭空画的：每一张都以
`agent-workflow-doc/figures.py`、`figures_more.py` 里已经算好的坐标为基准，再交给
`docforge.text` 量文字、按度量重排，所以既保留了原图的信息层次，又不会溢出。

## 怎么用

```bash
cd docforge
python3 -m docforge check examples/agent-workflow/material.md   # ok — no findings
python3 -m docforge build examples/agent-workflow/material.md -o /tmp/aw.html
python3 -m docforge fig   examples/agent-workflow/figures/queue.json --png /tmp/q.png
```
