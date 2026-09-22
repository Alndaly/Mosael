"""每一处 `chat()` 调用都要记账 —— **不能靠调用方记得传 `call=`**。

## 为什么这条看不出来

`domain/ai_chat` 的模块头把「用量:一条都不记」列为它当初存在的四个理由之一。而 `chat()` 的
`call` 参数是**可选**的:一个默认不记账的付费接口,靠每个调用点各自记得传。于是
`agent/judge.ask` —— 在那之后新加的调用点 —— **原样复现了被消灭的那个毛病**:自动驾驶模式下
每张"规则既没允许也没拒绝"的确认卡都会真打一次模型,而账上一条都没有。

**为什么一直没人发现**:判断跑在后台线程上,产物是一张卡的放行/拦截,用户感知不到"刚才打了
一次模型"。而 `billable` 那条「归属不了就 warning」的保护在这里也不会响 —— 压根没进那个
上下文管理器。首页的 Token 图和成本统计缺的这部分,不会以任何形式提示。

这是「一个不变量交给 N 个调用方各自记得」的同一个形状,而它在 `worker_pool` 里已经被正确地
解决过一次(锁放在 worker 自己身上)。这条棘轮不改签名(改成必填会让一大批只测传输行为的
测试全红),而是**静态**要求:`app/` 下每一处 `chat(...)` 要么带 `call=`,要么在
`UNBILLED` 里写明为什么。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

#: 允许不记账的调用点,`文件:函数` → 为什么。**这张表只减不增。**
UNBILLED: dict[str, str] = {}


def _chat_calls() -> list[tuple[str, int, bool]]:
    """`app/` 下所有 `chat(...)` 调用:(文件:函数, 行号, 有没有传 call=)。"""
    found: list[tuple[str, int, bool]] = []
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover
            continue
        # 每个调用挂在它所在的顶层函数名下,报错时说得出是哪一处。
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                name = getattr(inner.func, "id", None) or getattr(inner.func, "attr", None)
                if name != "chat":
                    continue
                billed = any(kw.arg == "call" for kw in inner.keywords)
                rel = path.relative_to(APP.parent).as_posix()
                found.append((f"{rel}:{node.name}", inner.lineno, billed))
    return found


def test_每一处chat调用都记账() -> None:
    calls = _chat_calls()
    assert len(calls) >= 5, f"只找到 {len(calls)} 处 chat() 调用 —— 这条测试大概是看错了地方"

    missing = [
        f"{where}(第 {line} 行)"
        for where, line, billed in calls
        if not billed and where not in UNBILLED
    ]
    assert not missing, (
        "这几处会真的花钱,而账上不会有任何记录 —— 首页的 Token 图和成本统计缺的这部分,"
        "不会以任何形式提示:\n  " + "\n  ".join(missing)
    )


def test_不记账的豁免表只减不增() -> None:
    """一个付费调用不记账,总得说得出为什么。表变长时,先问问那是不是又一次"忘了传"。"""
    assert len(UNBILLED) == 0, "现在一处都不该有;真要加,先在这里写下理由并改掉这个数"
