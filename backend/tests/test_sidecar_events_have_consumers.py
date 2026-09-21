"""sidecar 发得出的每一种事件,后端都要有一个分支接它。

## 为什么这条看不出来

两侧是两种语言、两个运行时:`agent-sidecar/src/protocol.ts` 的 `Event` 联合是 TypeScript,
接它的是 `adapters.py` / `domain/agent/login.py` 里的 `elif` 链。**没有任何一处同时看得见这两边。**
sidecar 多发一种事件,后端那条 `elif` 链默默落到末尾什么也不做;两侧都不报错,行为只是少了一块。

本仓库真实发生过:sidecar 专门为「那一轮在用户打字和这一帧到达之间结束了」发一条
`queued{pending:false}`,注释写着"说出来是为了让后端把它当成普通的下一轮发过去而不是丢掉"
—— 而 `_run_pi` 的事件循环里**没有 `queued` 分支**。后端把「字节写出去了」当成「对面接住了」,
摘掉那条消息的队列标,于是它既没进正在跑的那一轮,也不会再被排队执行。用户丢的是自己刚打的
一句话,而界面显示成功。

这和 `test_executor_outputs_are_declared.py` 是同一类检查(一侧产出的东西,另一侧要有落点),
只是换到了进程边界上。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PROTOCOL = REPO / "agent-sidecar" / "src" / "protocol.ts"
#: 接事件的那几处。新增一处读 sidecar 事件的地方,要加进来。
CONSUMERS = (
    REPO / "backend" / "app" / "ai" / "sidecar" / "adapters.py",
    REPO / "backend" / "app" / "domain" / "agent" / "login.py",
)

#: 后端不接、且有理由不接的。每一条都要写清楚为什么。
NOT_CONSUMED: dict[str, str] = {
    # 握手帧:sidecar 起来时发一次,后端按「进程起来了」处理,不进事件循环。
    "ready": "启动握手,不在回合的事件循环里",
}


def _event_types() -> set[str]:
    """`export type Event =` 那个联合里的每一个 `type: "…"` 字面量。"""
    text = PROTOCOL.read_text(encoding="utf-8")
    start = text.index("export type Event =")
    end = text.index("\nexport ", start + 1)
    return set(re.findall(r'type:\s*"([a-z_]+)"', text[start:end]))


def _consumed_types(sources: dict[Path, str] | None = None) -> set[str]:
    """消费方**拿来做分支判断**的那些字面量。

    **只认比较,不认"文件里出现过"。** 第一版在整个文件里搜 `"queued"`,而这两个文件里
    到处都是它 —— 注释、docstring、`live.ack("queued", …)` 这个处理器本身。于是我把分支删掉
    验证它会不会红,它**不红** —— 又一条判据对、扫描面太宽的棘轮,而这正是这轮审计里
    被点名最多的那一类。AST 只取 `Compare` 节点里的字符串,注释和调用参数天然进不来。
    """
    if sources is None:
        sources = {path: path.read_text(encoding="utf-8") for path in CONSUMERS}
    found: set[str] = set()
    for path, text in sources.items():
        for node in ast.walk(ast.parse(text, filename=str(path))):
            if not isinstance(node, ast.Compare):
                continue
            for operand in [node.left, *node.comparators]:
                items = operand.elts if isinstance(operand, (ast.Tuple, ast.List, ast.Set)) else [operand]
                for item in items:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        found.add(item.value)
    return found


def test_每一种事件都有人接() -> None:
    types = _event_types()
    assert len(types) > 10, f"只解析出 {len(types)} 种事件 —— Event 联合的形状变了,先修这条测试"

    consumed = _consumed_types()
    orphans = [name for name in sorted(types) if name not in NOT_CONSUMED and name not in consumed]
    assert not orphans, (
        "这些事件 sidecar 发得出来,而后端没有任何分支接它 —— 落进 elif 链的末尾,什么也不做,"
        "两侧都不报错:\n  " + "\n  ".join(orphans)
    )


def test_豁免清单只减不增() -> None:
    """不接也要一直说得出理由。清单变长时,先问问是不是又漏了一种。"""
    assert len(NOT_CONSUMED) <= 1
    for name, reason in NOT_CONSUMED.items():
        assert reason.strip(), f"{name} 的豁免没写理由"
        assert name in _event_types(), f"{name} 已经不是一种事件了,从豁免清单里删掉"
