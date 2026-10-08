"""一次工作流运行花了多少钱:大模型调用挂在这次运行上,运行的费用汇总连同子任务一起算。

隔离环境里跑模板:工作流里大模型那几次调用的用量记录 job_id 全是空的 —— 按运行(job)汇总的费用漏掉大模型,
管理页「按人分的花费」(顺着 job 找是谁花的)也漏掉它们。生成、配音这些子任务的账挂在各自的子任务上。
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import ProviderPricingRule, ProviderUsageEvent
from app.domain.workflows import executors as registry
from tests.util import add_provider, fresh_client


def _install_chat(monkeypatch) -> None:
    from app.core import http_retry

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": "好"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 500_000},
    }))
    real = http_retry.RetryingClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(http_retry, "RetryingClient", patched)


def _child_with_a_bill(db, scope, config: dict[str, Any]) -> dict[str, Any]:
    """一个派生子任务、子任务上记一笔账的节点(生成、配音都是这个形状)。借「等待」节点的壳。"""
    from app.domain.billing.usage import billable
    from app.domain.jobs import create_job

    child = create_job(db, workspace_id=scope.workspace_id, kind="t_child", payload={}, created_by=None)
    db.flush()
    with billable(db, user_id=None, capability="image", operation="t_child", workspace_id=scope.workspace_id,
                  idempotency_key=f"t_child:{child.id}", job_id=child.id) as call:
        call.report_cost(300_000, "CNY")
    return {"waited": 0}


def _run(client, workspace_id: str, profile_id: str, *, fails: bool) -> dict:
    #: 收尾那一步:成功的是一段文字;失败的是一个拿不是数的东西比大小的条件。
    last_node = (
        {"id": "last", "type": "condition", "name": "收尾", "config": {"left": "不是数", "op": "gt", "right": "2"}}
        if fails else {"id": "last", "type": "template", "name": "收尾", "config": {"template": "好了"}}
    )
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "plan", "type": "llm", "name": "写方案", "config": {"profile_id": profile_id, "prompt": "写一句"}},
            {"id": "child", "type": "delay", "name": "派生子任务", "config": {"seconds": 0}},
            last_node,
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "plan"},
            {"id": "e2", "source": "plan", "target": "child"},
            {"id": "e3", "source": "child", "target": "last"},
        ],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": workspace_id, "name": "W", "graph": graph}).json()
    job_id = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}}).json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("workflow did not finish")


@pytest.fixture
def setup(monkeypatch):
    _install_chat(monkeypatch)
    monkeypatch.setitem(registry._REGISTRY, "delay", _child_with_a_bill)
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="LLM", vendor="openai-compatible", base_url="https://example.test/v1",
                               api_key="sk", model="m")
        db.add(ProviderPricingRule(workspace_id=workspace_id, provider="openai-compatible", capability="chat", model="m",
                                   billing_unit="million_output_token", unit_amount_micros=2_000_000, currency="CNY"))
        db.commit()
        profile_id = profile.id
    return client, workspace_id, profile_id


def test_大模型调用的账挂在这次运行上_运行的费用连同子任务一起算(setup) -> None:
    client, workspace_id, profile_id = setup
    job = _run(client, workspace_id, profile_id, fails=False)
    assert job["status"] == "succeeded", job

    with SessionLocal() as db:
        chat = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.capability == "chat")).one()
    assert chat.job_id == job["id"], "大模型那次调用挂在这次运行上"
    assert chat.cost_micros == 1_000_000

    costs = job["result"]["costs"]
    assert costs == {"amounts": [{"currency": "CNY", "micros": 1_300_000}], "calls": 2, "unpriced": 0}, costs


def test_运行失败了_已经花掉的钱照样汇总在结果里(setup) -> None:
    client, workspace_id, profile_id = setup
    job = _run(client, workspace_id, profile_id, fails=True)
    assert job["status"] == "failed", job
    assert job["result"]["costs"]["amounts"] == [{"currency": "CNY", "micros": 1_300_000}], job["result"]
