"""工具定义加系统提示,不超过本机回退窗口的六成 —— 每轮都重发、又压不掉的那一块,得有个明说的上限。

## 现场

这道预算此前**没有写出来**,是碰巧被 test_context_is_broken_down 兜住的:那里的测试供应商挂在 localhost,
窗口落到本机回退值 32K;水位分项先给工具、再给系统提示,于是「系统提示那一项 > 0」实际断言的是
「工具定义 < 32K」—— 一条没人知道自己在守什么的线。顶到它的时候工具定义估出来 31,954,系统提示只分到
46,空闲是 0:一个字没说,窗口已经满了。

而那不只是显示问题。按 Qwen3 的分词器实数,工具定义 ≈29.1K、系统提示 ≈3.5K,合计 ≈32.5K —— 真只有
32K 的本机模型根本装不下这套工具;窗口查不到、按 32K 回退的本机模型,第一次工具调用之后 pi 按
「窗口 − 已用 − 4096」把 max_tokens 夹到 1(用户看到「我」这种碎片),轮前压缩每轮触发又压不下去。
所以回退窗口调到了 64K(理由全文在 app/domain/providers/model_limits.LOCAL_FALLBACK_CONTEXT_WINDOW),
预算在这里明说。

## 为什么是六成

- 轮前压缩在窗口的 80% 触发(agent-sidecar/src/compaction.ts 的 COMPACT_RATIO)。固定开销压不掉:它越靠近
  80%,压缩越频繁,到了 80% 就每轮都压、每轮都压不下去。
- 六成到八成之间那两成,是对话在第一次压缩之前能用的地方(64K 下约 12.8K);再往上那两成留给本轮回复与工具
  结果。
- 顶到了怎么办:先把说明写紧(op_args 的 note、工具 docstring —— 工具定义每轮重发,一个字一个字地算);写不紧
  再谈按需裁剪工具集。**不要再把回退窗口往上调**:它是对「查不到窗口的本机模型」的猜测,调大它不会让那台
  机器上的窗口变大,只会让请求在服务端超窗。

量的是界面那条水位用的同一个函数(session_context → tool_definition_tokens + 系统提示),不另估一遍。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

from app.domain.providers.model_limits import LOCAL_FALLBACK_CONTEXT_WINDOW
from tests.util import add_provider, fresh_client

#: 固定开销(工具定义 + 系统提示)最多占本机回退窗口的这么多。理由见模块说明。
FIXED_OVERHEAD_SHARE = 0.6


def _local_session(client) -> str:
    """一次挂在本机端点上的对话 —— 窗口查不到,落到本机回退值,正是预算要守的那个窗口。"""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        add_provider(
            db, name="Local", vendor="openai-compatible", base_url="http://127.0.0.1:11434/v1",
            api_key="k", model="some-local-gguf", capability_ids=["chat"], owner_username="tester",
        )
        db.commit()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post("/api/agent/sessions", json={"workspace_id": workspace, "title": "T"})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_工具定义加系统提示_不超过本机回退窗口的六成() -> None:
    client = fresh_client()
    context = client.get(f"/api/agent/sessions/{_local_session(client)}").json()["context"]
    assert context is not None, "没配上供应商:水位不显示,这条预算就什么都没量"
    assert context["window"] == LOCAL_FALLBACK_CONTEXT_WINDOW, "这次对话没落到本机回退窗口上"

    parts = {part["kind"]: part["tokens"] for part in context["parts"]}
    fixed = parts["tools"] + parts["system"]
    budget = int(LOCAL_FALLBACK_CONTEXT_WINDOW * FIXED_OVERHEAD_SHARE)
    assert fixed <= budget, (
        f"每轮重发的固定开销 {fixed}(工具定义 {parts['tools']} + 系统提示 {parts['system']})"
        f"超过了本机回退窗口 {LOCAL_FALLBACK_CONTEXT_WINDOW} 的六成({budget})。"
        "先把新加的说明写紧,别去调回退窗口 —— 见本模块说明。"
    )


def test_量到的是真东西() -> None:
    """假阴性比红更危险:哪天工具清单或系统提示量出来是 0,上面那条会真空通过。"""
    client = fresh_client()
    context = client.get(f"/api/agent/sessions/{_local_session(client)}").json()["context"]
    parts = {part["kind"]: part["tokens"] for part in context["parts"]}
    assert parts["tools"] > 10_000, "工具定义量出来这么小?注册表里有上百个工具"
    assert parts["system"] > 500, "系统提示量出来这么小?"
