"""棘轮:**每个节点类型在画布上都有自己的图标**。

`WorkflowNode.tsx` 里那张 `NODE_ICONS` 是手写的,而节点类型的真源在后端的 `NODE_TYPES`。
两边各长各的,漏掉不报错 —— 缺图标的节点会退到一个通用的文字图标(`<Type>`),于是
`timeline_append`、`timeline_clear`、`timeline_add_track` 顶着一个"T"站在
`timeline_cut_ranges`(剪刀)旁边,看起来像它们不是同一类东西。发现时漏了 7 个。

这是**同一个形状第四次出现**(docs/MCP.md 的工具清单、节点字段的中文标签、输出接点的语义名,
现在是图标)。共同点都是"一份该跟着声明走的知识被抄到了消费方那边",而抄漏的表现从来不是
报错,只是界面上默默难看一点 —— 于是没人会去修。

判据只问"有没有",不问"配得好不好":图标选得贴不贴切是人的判断,而**有没有**是机器该管的。
"""

from __future__ import annotations

import pathlib
import re

RATCHET = True

ICONS_FILE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "features" / "workflows" / "WorkflowNode.tsx"
)


def _declared_icons() -> set[str]:
    source = ICONS_FILE.read_text(encoding="utf-8")
    start = source.index("const NODE_ICONS")
    block = source[start : source.index("\n};", start)]
    return set(re.findall(r"^\s+([a-z_]+):", block, re.M))


def test_每个节点类型都有图标() -> None:
    from app.domain.workflows import NODE_TYPES

    missing = sorted(set(NODE_TYPES) - _declared_icons())
    assert not missing, (
        "这些节点类型在 WorkflowNode.tsx 的 NODE_ICONS 里没有图标,画布上会退到通用的"
        f"文字图标,和同族节点摆在一起显得不是一类东西:\n  {missing}"
    )


def test_图标表里不留已经不存在的节点() -> None:
    """棘轮只能缩:节点删掉或改名时,图标要跟着删,否则这张表会慢慢变成一份历史记录。"""
    from app.domain.workflows import NODE_TYPES

    stale = sorted(_declared_icons() - set(NODE_TYPES))
    assert not stale, f"这些图标对应的节点类型已经不在了,从 NODE_ICONS 里删掉:{stale}"
