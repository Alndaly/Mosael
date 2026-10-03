"""「这张图现在跑得起来吗」在每一个开跑的入口都问,问的是同一个函数(workflows.engine.check_runnable)。

## 现场

开跑前的检查此前只写在 engine.start_workflow_job 里:

- `call_workflow` 调的子工作流缺必填参数,要等父工作流前面的节点全跑完、轮到它时才说;
- 智能体的「运行工作流」卡开卡时只看工作流在不在 —— 用户批准之后才报缺参数;
- 定时任务启用、触发时只看绑的工作流在不在,到点才失败;派发失败也没人知道(只写进运行记录)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Notification
from tests.util import fresh_client, wait_status


def _child_needing_topic(client, ws: str) -> dict:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "写稿子", "graph": {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"topic": ""}, "required_params": ["topic"]}},
            {"id": "t", "type": "template", "config": {"template": "关于 {{start.topic}}"}},
            {"id": "out", "type": "output", "config": {"values": {"text": "{{t.text}}"}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "t"}, {"id": "e2", "source": "t", "target": "out"}],
    }}).json()


def _parent(client, ws: str, child_id: str, inputs: dict) -> dict:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "总流程", "graph": {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "slow", "type": "delay", "config": {"seconds": 0}},
            {"id": "call", "type": "call_workflow", "config": {"workflow_id": child_id, "inputs": inputs}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "slow"}, {"id": "e2", "source": "slow", "target": "call"}],
    }}).json()


def test_调用的子工作流缺必填参数_父工作流点运行当场就说_说的是哪一张() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    child = _child_needing_topic(client, ws)

    missing = _parent(client, ws, child["id"], {})
    refused = client.post(f"/api/workflows/{missing['id']}/run", json={"params": {}})
    assert refused.status_code == 422, refused.text
    assert "写稿子" in refused.text and "topic" in refused.text and "call" in refused.text

    given = _parent(client, ws, child["id"], {"topic": "猫"})
    started = client.post(f"/api/workflows/{given['id']}/run", json={"params": {}})
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    result = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
    assert result["call"]["output"] == {"text": "关于 猫"}


def test_入参引用上游的值_运行前不拿引用原文去查子工作流() -> None:
    """入参是 `{{start.v}}` 这种引用时,它的值要到运行时才知道 —— 运行前只能算「给了」。

    实测撞到:父工作流把自己的开始参数接给子工作流的必填参数,点运行当场 422,说子工作流
    「开始节点没有这些参数:start.v」—— 引用原文被当成子工作流自己的配置去校验了。于是
    「调用工作流」只能传写死的字面量,接上游的值一律跑不起来。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    child = _child_needing_topic(client, ws)

    def parent(inputs: dict) -> dict:
        return client.post("/api/workflows", json={"workspace_id": ws, "name": "总流程", "graph": {
            "nodes": [
                {"id": "start", "type": "start", "config": {"params": {"v": "猫"}}},
                {"id": "call", "type": "call_workflow", "config": {"workflow_id": child["id"], "inputs": inputs}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "call"}],
        }}).json()

    for inputs, expected in (({"topic": "{{start.v}}"}, "关于 猫"), ({"topic": "小{{start.v}}"}, "关于 小猫")):
        started = client.post(f"/api/workflows/{parent(inputs)['id']}/run", json={"params": {}})
        assert started.status_code == 200, started.text
        assert wait_status(client, started.json()["id"]) == "succeeded"
        result = client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]
        assert result["call"]["output"] == {"text": expected}

    # 引用落空、运行时才是空的那种,仍由子工作流开跑时那一道拦下(不是在这里静默放过)。
    blank = client.post("/api/workflows", json={"workspace_id": ws, "name": "空引用", "graph": {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"v": ""}}},
            {"id": "call", "type": "call_workflow", "config": {"workflow_id": child["id"], "inputs": {"topic": "{{start.v}}"}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "call"}],
    }}).json()
    started = client.post(f"/api/workflows/{blank['id']}/run", json={"params": {}})
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "failed"


def test_智能体的运行工作流卡_跑不起来就不开卡_原因交给智能体() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    child = _child_needing_topic(client, ws)

    def open_card(params: dict):
        return client.post("/api/confirmations", json={
            "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi",
            "payload": {"workflow_id": child["id"], "params": params},
        })

    refused = open_card({})
    assert refused.status_code == 422, refused.text
    assert "params.topic" in refused.text
    assert open_card({"topic": "   "}).status_code == 422, "空白不算给了"
    assert open_card({"topic": "猫"}).status_code == 200


def test_定时任务_带着自己的参数跑不起来就建不出来_启用不了() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    child = _child_needing_topic(client, ws)

    def make(params: dict, *, enabled: bool = True):
        return client.post("/api/scheduled-tasks", json={
            "workspace_id": ws, "name": "每天写", "kind": "workflow", "trigger_type": "manual", "schedule": {},
            "enabled": enabled, "payload": {"workflow_id": child["id"], "params": params},
        })

    refused = make({})
    assert refused.status_code == 422, refused.text
    assert "写稿子" in refused.text and "topic" in refused.text
    # 停着建可以(跑不起来的任务至少要存得下、关得掉),打开开关时再问。
    parked = make({}, enabled=False)
    assert parked.status_code == 200, parked.text
    assert client.patch(f"/api/scheduled-tasks/{parked.json()['id']}", json={"enabled": True}).status_code == 422
    fine = make({"topic": "猫"})
    assert fine.status_code == 200, fine.text
    ran = client.post(f"/api/scheduled-tasks/{fine.json()['id']}/run")
    assert ran.status_code == 200, ran.text


def test_定时任务派发失败_通知工作区() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    task = client.post("/api/scheduled-tasks", json={
        "workspace_id": ws, "name": "每天导出", "kind": "render", "trigger_type": "manual", "schedule": {},
        "payload": {"sequence_id": "已经删掉的时间线"},
    })
    assert task.status_code == 200, task.text
    ran = client.post(f"/api/scheduled-tasks/{task.json()['id']}/run")
    assert ran.status_code == 200, ran.text
    with SessionLocal() as db:
        notices = db.query(Notification).filter(Notification.workspace_id == ws).all()
    assert [notice.title for notice in notices] == ["定时任务没跑起来:每天导出"]
    assert notices[0].link == "#/scheduler"
    assert notices[0].payload["scheduled_task_id"] == task.json()["id"] and notices[0].payload["job_id"]
