---
title: 文档标题
eyebrow: 技术方案 · v1
theme: paper
numbering: auto
---

# 背景与目标

用一段话说明这份文档要解决什么问题、给谁看。

> [!KEY]
> 最核心的一句话结论放在这里，读者只读这一段也能拿到要点。

## 现状

- 并列项用无序列表
- 每一项只讲一件事

## 方案

需要强调的**术语**用粗体，行内代码写成 `graph.invoke(state)`。

### [1] 主流程

```figure flow
@figures/flow.json
```

流程说明放在图后面，先说这张图在回答什么问题。

### [2] 分层结构

```figure layers
@figures/layers.json
```

### [3] 接口约定

```python
def handle(state):
    return {"final_answer": state["draft_answer"]}
```

## 对比

| 方案 | 优点 | 代价 |
|------|------|------|
| A | 简单 | 扩展性差 |
| B | 可扩展 | 前期投入大 |

> [!NOTE]
> 补充说明、边界情况、已知限制写在这里。

> [!GOAL]
> 这一段要达成什么。

> [!ACCEPT]
> 可验证的验收标准。
