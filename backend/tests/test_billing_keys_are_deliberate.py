"""每一处 `billable(...)` 都要**说出**自己的幂等键,没有隐式兜底。

## 为什么这条看不出来

`billable` 的文档写着「重放同一次调用不会重复入账」,`record_usage` 的 docstring 也写着
「source modules can safely call this after a retry or crash recovery without double-booking」。
而兜底键是:

    f"{operation}:{source_id or id(call)}:{int(began * 1000)}"

**时间戳在键里,意味着任何重放都会生成新键**,于是必然重复入账 —— 兜底键实际上等于"不去重"。
(`id(call)` 是内存地址,对象回收后会被复用,理论上还可能撞键,方向相反:该记的没记。)

今天没人被它坑到,因为**所有真正需要幂等的调用点都显式传了稳定键**(generation、
agent-message)。兜底只服务于翻译、分析、提示词优化、画板写作这类一次性调用。但文档给出的是
一个**通用承诺**,而下一个需要重放保护的调用点很可能照着文档不传键 —— 一个在它该生效的那次
不生效的保护,比没有保护更坏。

所以键改成必填,并且这条棘轮盯着它一直是必填的:AST 扫一遍,每处 `billable(` 都得带
`idempotency_key=`。传 `once(...)` 也算 —— 那个名字本身就写着"这一次不受重放保护",
选择是看得见的。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import inspect
from pathlib import Path

from app.domain.usage import billable, once

APP = Path(__file__).resolve().parent.parent / "app"


def _billable_calls() -> list[tuple[str, int, bool]]:
    found: list[tuple[str, int, bool]] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "usage.py":
            continue  # 定义处
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "billable":
                continue
            said = any(kw.arg == "idempotency_key" for kw in node.keywords)
            found.append((path.relative_to(APP.parent).as_posix(), node.lineno, said))
    return found


def test_每一处都说出了自己的键() -> None:
    calls = _billable_calls()
    assert len(calls) >= 10, f"只找到 {len(calls)} 处 billable(),这条测试大概看错了地方"
    silent = [f"{where}:{line}" for where, line, said in calls if not said]
    assert not silent, (
        "这几处没说自己的幂等键。没有兜底了 —— 有稳定工作单元的传从它算出来的键(重放不会"
        "重复计费),重放不可能发生的传 `once(operation)`(那个名字说明这一次不受重放保护):\n  "
        + "\n  ".join(silent)
    )


def test_键是必填的_而不是有默认值() -> None:
    """**必填是这条的关键。** 有默认值的话,忘了传和"想清楚了不传"长得一模一样。"""
    parameter = inspect.signature(billable).parameters["idempotency_key"]
    assert parameter.default is inspect.Parameter.empty, "又有默认值了 —— 隐式兜底会悄悄回来"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_once_每次都不一样_而且看得出是它() -> None:
    """它只保证唯一,不保证幂等 —— 名字和前缀都把这件事说出来。"""
    a, b = once("translate_batch"), once("translate_batch")
    assert a != b
    assert a.startswith("once:translate_batch:")


def test_稳定键真的会去重() -> None:
    """同一个键记两次,只该有一行 —— 这是"重放不重复计费"那句话的实体。"""
    from app.core.db import SessionLocal
    from app.domain.usage import record_usage
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        first = record_usage(db, workspace_id=ws, capability="chat", operation="t",
                             idempotency_key="replay:me", units={"input_tokens": 10})
        again = record_usage(db, workspace_id=ws, capability="chat", operation="t",
                             idempotency_key="replay:me", units={"input_tokens": 10})
        assert first.id == again.id, "同一个键记出了两行 —— 重放会重复计费"
