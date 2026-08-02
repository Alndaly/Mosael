"""结构性约束:**记账只有一个入口**。

`record_usage` 有十八个关键字参数,而它曾被三处各拼一遍(生成 runner、智能体 host、对话)。
抄三遍的后果不是"重复",是**不一致**:各自算耗时、各自编幂等键、各自决定失败要不要记。
而新增的调用类型干脆一条都不记 —— 首页那张 Token 图长期是漏的,漏得没有任何提示。

现在归属、耗时、成败、幂等、落库都在 `billable()` 里,调用方只报计量。所以除了 usage.py
自己,谁都不该再直接调 `record_usage` —— 那等于重新长出第四份。

只减不增,和 tests/test_chat_single_implementation.py、test_undo_registry.py 同一套棘轮。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

OWNER = "app/domain/usage.py"

#: 例外 → 理由。只减不增。
EXEMPT: dict[str, str] = {}


def _callers_of(name: str) -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", "app", "mcp_server.py"], cwd=BACKEND, capture_output=True, text=True
    ).stdout.split()
    hits = []
    for rel in tracked:
        path = BACKEND / rel
        if not rel.endswith(".py") or not path.exists():
            continue
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
                hits.append(rel)
                break
    return sorted(hits)


def test_只有_usage_模块直接记账() -> None:
    offenders = [rel for rel in _callers_of("record_usage") if rel != OWNER and rel not in EXEMPT]
    assert offenders == [], (
        "记账又出现了第二个入口 —— 请改用 app.domain.usage.billable():\n  " + "\n  ".join(offenders)
    )


def test_豁免清单里没有过时条目() -> None:
    for rel in EXEMPT:
        assert (BACKEND / rel).exists(), f"豁免了不存在的文件: {rel}"


def test_翻译走的是记账链路而不是又一份实现(monkeypatch) -> None:
    """AI 翻译以前一条账都不记 —— 因为 /api/translate 根本没有工作区,而 workspace_id 是
    NOT NULL。补上字段 + 走权限闸门绑定归属之后,这条路径应当有账。"""
    import httpx

    from app.db.models import ProviderUsageEvent
    from app.domain import ai_retry
    from tests.util import add_provider, fresh_client
    from app.core.db import SessionLocal

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "你好"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    transport = httpx.MockTransport(handler)
    real = ai_retry.RetryingClient
    monkeypatch.setattr(ai_retry, "RetryingClient", lambda *a, **kw: real(*a, **{**kw, "transport": transport}))

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        add_provider(db, name="LLM", vendor="openai-compatible", base_url="https://api.test", api_key="sk", model="m")
        db.commit()

    res = client.post(
        "/api/translate",
        json={"workspace_id": ws["id"], "texts": ["hello", "world"], "target_lang": "zh", "engine": "ai"},
    )
    assert res.status_code == 200, res.text

    with SessionLocal() as db:
        events = db.query(ProviderUsageEvent).filter_by(workspace_id=ws["id"]).all()
        assert len(events) == 1, "整批翻译应当记成一条账,而不是每句一条或一条都没有"
        assert events[0].operation == "translate_batch"
        # 两句各 5/3 token,累加成一条
        assert events[0].units["input_tokens"] == 10
        assert events[0].units["output_tokens"] == 6


def test_没有工作区归属时不静默(caplog) -> None:
    """记不了账要喊出来 —— 静默漏记正是这次要终结的毛病。"""
    import logging

    from app.core.db import SessionLocal
    from app.domain.usage import billable

    with SessionLocal() as db, caplog.at_level(logging.WARNING):
        with billable(db, capability="chat", operation="无归属的调用") as call:
            call.meter(input_tokens=1)
    assert any("无归属的调用" in record.getMessage() for record in caplog.records)
