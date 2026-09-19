"""执行历史不能因为一条失败原因而整片消失。

用户看到的:「从主题到完整视频」跑过好几次,执行历史面板却一条都没有 —— 连空状态都没有。

三层叠起来的:

1. 写入。`WorkflowDomainError(str(exc))` 把第三方报错原文(LLM 返回的 403 JSON)当 **key**,
   `blame()` 再截成 80 字写进 `error_key`;而写 `error` 那一句时,原文里的花括号被当成
   "填不上的占位符"抹掉,真正的原因("额度用完")在落库那一刻就没了。
2. 读取。`JobOut` 拿那半截"key"当模板去 format,花括号一炸 —— **一条坏行把整个列表打成 500**。
3. 查询。列表先取整个工作区最新 N 条、再按工作流过滤:别的工作流多跑几次,这个就被挤没了。

判据收成一条(`core/i18n.is_message_key`):认不出的就是一句现成的话 —— 原样显示,不当模板填,
不当 key 落库。
"""

from __future__ import annotations

from app.db.models import Job, now

#: 真实的形状:LLM 网关原样返回的一段 JSON,里面全是花括号。
RAW = '调用 LLM失败:Error: 403 {"error":{"type":"permission_error","message":"You\'ve reached your usage limit"}}'


def test_一句带花括号的原话原样渲染() -> None:
    from app.core.i18n import render_message

    assert render_message(RAW, "zh") == RAW, "不是模板就不该被 format —— 花括号是内容,不是槽"


def test_原话不当_key_落库_而且一个字都不丢() -> None:
    from app.domain.jobs import blame
    from app.domain.workflows import WorkflowDomainError

    exc = WorkflowDomainError(RAW)
    assert exc.key == ""
    assert str(exc) == RAW, "此前花括号之后全被当占位符抹掉,「额度用完」这句在落库那一刻就没了"
    recorded = blame(exc)
    assert recorded["error_key"] == ""
    assert "usage limit" in recorded["error"]


def test_任务消息也一样(monkeypatch) -> None:
    from app.domain.jobs import say

    job = Job(message="", message_key="", message_params={})
    say(job, RAW)
    assert job.message_key == "" and job.message == RAW


def test_认得出的_key_照旧翻() -> None:
    from app.domain.jobs import blame
    from app.domain.workflows import WorkflowDomainError

    assert blame(WorkflowDomainError("wfErr_noExecutor", params={"type": "demo"}))["error_key"] == "wfErr_noExecutor"


def test_库里已有的坏行不拖垮列表() -> None:
    """改正之前落下的行:`error_key` 是一句被截成 80 字的原话。读的时候用完整那句 `error`。"""
    from app.api.schemas import JobOut

    job = Job(
        id="j", workspace_id="w", kind="workflow", status="failed", progress=1.0,
        message="", message_key="", message_params={}, payload={}, result={},
        error="调用 LLM失败:Error: 403", error_key=RAW[:80], error_params={},
        created_at=now(), updated_at=now(),
    )
    assert JobOut.model_validate(job).error == "调用 LLM失败:Error: 403"


def test_别的工作流跑得再多_这个的历史也还在() -> None:
    """此前先取工作区最新 50 条再过滤 —— 同一工作区里别的工作流多跑几次,这个就被挤出去了。"""
    from app.core.db import SessionLocal
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": []}
    mine = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "我的", "graph": graph}).json()
    other = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "别人的", "graph": graph}).json()

    def run(workflow_id: str, index: int, error_key: str = "") -> Job:
        return Job(
            id=f"{workflow_id[:8]}-{index}", workspace_id=ws["id"], kind="workflow", status="failed",
            progress=1.0, message="", message_key="", message_params={},
            payload={"workflow_id": workflow_id}, result={},
            error="调用 LLM失败:Error: 403", error_key=error_key, error_params={},
            created_at=now(), updated_at=now(),
        )

    with SessionLocal() as db:
        #: 我的那两次在前面,其中一次是改正之前那种坏行。
        db.add(run(mine["id"], 0, error_key=RAW[:80]))
        db.add(run(mine["id"], 1))
        db.flush()
        #: 然后别人的跑了 60 次,全都比我的新。
        for index in range(60):
            db.add(run(other["id"], index))
        db.commit()

    response = client.get(f"/api/workflows/{mine['id']}/runs")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 2, "被别的工作流挤出前 50 条,历史面板就成了空的"
