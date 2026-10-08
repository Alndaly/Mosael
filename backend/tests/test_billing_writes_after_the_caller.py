"""付费调用的账由记账这一层写:调用期间不写进调用方的会话,随调用方提交的那一刻一起落库;没提交的在事务结束之后补写(D66)。

此前账在调用之后当场 add + flush 进调用方的会话:SQLite 只有一个写者,flush 一次就攥着写锁直到那个事务结束。一个会话里接连
几次付费调用 —— 工作流「口播收紧」一个节点里两三轮大模型 —— 第一笔账 flush 之后,后面每一次大模型请求都攥着写锁,别的节点、
任务进度、请求都排在后面,超过等锁的上限就报 database is locked。这里钉住:

- 「口播收紧」第二轮、第三轮发出大模型请求的那一刻,这个节点的连接上没有写事务;三轮的账在节点结束后都在库里;
- 调用方的会话里、提交之前没有待写的东西,库里也没有;提交之后在库里;回滚了也在(钱花了);
- 保存点提交时写进去、外层又回滚了的,事务结束之后照样补写;
- 同一个键只记一条;接替的那一条写进来时,被接替的那一条在同一个事务里撤下。

「落终态的那一刻账已经在」见 test_usage_is_booked_when_the_job_settles。
"""

from __future__ import annotations

import json
import threading

import httpx
from sqlalchemy import select

from app.core import db as core_db
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent, Workflow
from app.domain.billing.usage import billable, record_usage, superseded_attempt
from tests.test_workflows import _install_llm_transport
from tests.util import acting_as, add_provider, fresh_client


def _holds_the_write_lock() -> bool:
    """这个线程手上有没有没提交的写事务(core.db 记着每条连接上的写事务是谁开的)。"""
    me = threading.current_thread().name
    return any(writer.thread == me and writer.connection.in_transaction for writer in list(core_db._writers.values()))


def test_口播收紧的第二轮第三轮大模型请求_不攥着写锁(monkeypatch) -> None:
    from app.domain.workflows.engine import execute_graph
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    holding: list[bool] = []

    def model(request: httpx.Request) -> httpx.Response:
        holding.append(_holds_the_write_lock())
        #: 改不短:每一轮都还超,三轮都跑满。
        answer = {"rewrites": [{"index": 1, "narration": "夏天久坐也不闷夏天久坐也不闷夏天久坐也不闷"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}],
                                         "usage": {"prompt_tokens": 11, "completion_tokens": 7}})

    _install_llm_transport(monkeypatch, ai_nodes, model)
    with SessionLocal() as db:
        profile = add_provider(db, name="LLM", vendor="openai-compatible", base_url="https://api.test", api_key="sk", model="m")
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        graph = {"nodes": [{"id": "fit", "type": "fit_narration", "config": {
            "items": [{"narration": "夏天久坐也不闷,五五亚麻加棉,透气看得见", "seconds": 2}],
            "text_field": "narration", "seconds_field": "seconds", "profile_id": profile.id, "model": "m", "max_rewrites": 3,
        }}], "edges": []}
        with acting_as(db):
            db.commit()  # 节点在自己的会话里读父 job
            execute_graph(graph, wf_id=workflow.id, entry_is_root=True)

    assert len(holding) == 3, holding
    assert holding == [False, False, False], "第一轮的账写进了节点的会话:之后每一轮大模型请求都攥着写锁"
    with SessionLocal() as db:
        booked = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.workspace_id == workspace_id)).all()
    assert [event.operation for event in booked] == ["workflow_llm"] * 3, "三轮的账在节点结束之后都在库里"


def _call(db, workspace_id: str, key: str, **extra) -> ProviderUsageEvent | None:
    with billable(db, capability="chat", operation="probe", workspace_id=workspace_id, idempotency_key=key, **extra) as call:
        call.report_cost(1200, "USD")
    return call.event


def _booked(key: str) -> ProviderUsageEvent | None:
    with SessionLocal() as db:
        return db.scalar(select(ProviderUsageEvent).where(ProviderUsageEvent.idempotency_key == key))


def test_调用方的事务里不写账_结束之后才在库里_回滚了也在() -> None:
    workspace_id = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        event = _call(db, workspace_id, "probe:committed")
        assert (event.cost_micros, event.currency, event.cost_confidence) == (1200, "USD", "reported"), "成本当场就算好了"
        assert not db.new and not db.dirty, "调用方的会话里不该有待写的账"
        assert db.scalar(select(ProviderUsageEvent).where(ProviderUsageEvent.idempotency_key == "probe:committed")) is None
        assert _booked("probe:committed") is None, "调用方的事务还没结束"
        db.commit()
    assert _booked("probe:committed").cost_micros == 1200

    with SessionLocal() as db:
        _call(db, workspace_id, "probe:rolled-back")
        db.rollback()
    assert _booked("probe:rolled-back") is not None, "钱花了就有账,调用方回滚也一样"

    with SessionLocal() as db:
        _call(db, workspace_id, "probe:savepoint-then-rollback")
        with db.begin_nested():
            pass  # 保存点提交:排着的账写进了保存点
        db.rollback()  # 外层回滚,保存点里的跟着没了
    assert _booked("probe:savepoint-then-rollback") is not None, "外层回滚了,事务结束之后照样补写"


def test_同一个键只记一条_接替的那一条写进来时撤下被接替的() -> None:
    workspace_id = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        _call(db, workspace_id, "generation:g1:failed")
        db.commit()
    with SessionLocal() as db:
        first = record_usage(db, workspace_id=workspace_id, capability="chat", operation="probe", idempotency_key="probe:twice")
        again = record_usage(db, workspace_id=workspace_id, capability="chat", operation="probe", idempotency_key="probe:twice")
        assert again.idempotency_key == first.idempotency_key
        replaced = superseded_attempt(db, "generation:g1:failed")
        assert replaced is not None and replaced["cost_micros"] == 1200
        assert _booked("generation:g1:failed") is not None, "接替的那一条写进来之前,被接替的照旧在"
        _call(db, workspace_id, "generation:g1:succeeded", supersedes="generation:g1:failed")
        db.commit()

    with SessionLocal() as db:
        keys = [event.idempotency_key for event in db.scalars(select(ProviderUsageEvent))]
    assert sorted(keys) == ["generation:g1:succeeded", "probe:twice"]
