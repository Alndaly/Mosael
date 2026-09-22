"""棘轮:**协议请求方向上声明的每个字段,sidecar 那侧都要真的读它。**

`test_sidecar_events_have_consumers` 守的是**事件方向**(sidecar 发、后端接)。请求方向一直
没人守,于是它也长出了死字段 —— `RunTurnRequest.history` 声明在 `protocol.ts` 上,注释写着
「后端已经裁剪过的历史轮次」,而**后端从不发、sidecar 从不读**,两侧零引用,纯留档
(见进程审计 2.10)。

单看无害。合起来它和事件方向是同一件事:**协议的两侧没有任何一处被强制对齐**,所以两个方向
都会长出死代码 —— 一边加了没人读,一边读了从不出现。

判据是「这个字段名在 `agent-sidecar/src/` 里除 protocol.ts 之外出现过吗」。宽松是有意的:
读法太多(解构、`msg.x`、`x in msg`),收紧会变成一条误报的棘轮,而误报教人学会忽略它。
即便这么宽,它也抓得到纯留档的那一类 —— 那正是这一类问题的实际长相。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SIDECAR = REPO / "agent-sidecar" / "src"
PROTOCOL = SIDECAR / "protocol.ts"

#: 声明了、sidecar 自己不读,但**有理由**留着的。每条写清为什么。
NOT_READ: dict[str, str] = {
    # 判别标签。它由 index.ts 的 `msg.type === …` 分发,读法是字面量比较而不是字段名。
    "type": "分发用的判别标签,读法是 msg.type === '…'",
}


def _request_fields() -> dict[str, str]:
    """请求方向那几个 interface 上的字段名 → 它声明在哪一行。"""
    text = PROTOCOL.read_text(encoding="utf-8")
    fields: dict[str, str] = {}
    for block in re.finditer(r"export interface (\w*Request)\s*\{(.*?)\n\}", text, re.S):
        name, body = block.group(1), block.group(2)
        # 只取**这一层**的字段(缩进恰好两个空格),不进嵌套对象 —— 嵌套里的名字由外层那个
        # 字段整体决定死活,单独判会误报。
        for field in re.finditer(r"^  (\w+)\??:", body, re.M):
            fields.setdefault(field.group(1), name)
    return fields


def _sidecar_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(SIDECAR.rglob("*.ts"))
        if path != PROTOCOL
    )


def test_请求字段没有纯留档的() -> None:
    fields = _request_fields()
    assert len(fields) > 15, f"只解析出 {len(fields)} 个字段 —— protocol.ts 的形状变了,先修这条测试"

    sources = _sidecar_sources()
    dead = [
        f"{name}(声明在 {owner})"
        for name, owner in sorted(fields.items())
        if name not in NOT_READ and not re.search(rf"\b{re.escape(name)}\b", sources)
    ]
    assert not dead, (
        "这些字段声明在协议的请求方向上,而 sidecar 自己从不读 —— 两侧零引用的纯留档,"
        "下一个人会以为它有值:\n  " + "\n  ".join(dead)
    )


def test_豁免清单只减不增() -> None:
    fields = _request_fields()
    assert len(NOT_READ) <= 1
    for name, reason in NOT_READ.items():
        assert reason.strip(), f"{name} 的豁免没写理由"
        assert name in fields, f"{name} 已经不是请求字段了,从豁免清单里删掉"
