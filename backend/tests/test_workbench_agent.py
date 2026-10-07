"""工作台里的智能体(ADR 0042 第一步)宿主这一侧:`comfy_*` 工具 —— 碰画布的经「后端 → 主进程 → 页面」那条路,别的问插件。

画布那条路和浏览器动作是同一套(见 domain/browser 的 workbench_session / run_workbench):工具排一条 `workbench` 动作在这个
工作区对这个连接的工作台会话上,执行器(这里是一个线程,经 /api/browser/worker/* 那几个口,和 electron 的 browserWorker 一样)
领走、交给那个连接开着的工作台、报回桥的回答。工作台没开着(桥说 closed)、执行器根本不在,都说「先在工作台里打开这台 ComfyUI」。

插件那一侧对着 tests/fake_comfyui.py 真跑(插件进程)。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserAction, BrowserSession, Job
from app.domain import browser
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client, second_client, worker_client

PACKAGE = "dev.mosael.comfyui"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "comfyui" / "agent"
QWEN = json.loads((FIXTURES / "image_qwen_image_2_1_image_edit.json").read_text(encoding="utf-8"))


def _connect(client, comfy: FakeComfyUI) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    return instance_id


@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        comfy.state.object_info = json.loads((FIXTURES / "object_info.json").read_text(encoding="utf-8"))
        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        yield client, comfy, _connect(client, comfy), workspace


class Executor:
    """桌面端的执行器:领 `workbench` 动作,交给「开着的工作台」(这里是一个按调用回答的函数),报回去。"""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.claimed: list[dict[str, Any]] = []
        self.stop = threading.Event()
        self.worker = worker_client()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        while not self.stop.is_set():
            action = self.worker.post("/api/browser/worker/claim", json={"worker": "desk-1"}).json()["action"]
            if action is None:
                time.sleep(0.05)
                continue
            self.claimed.append(action)
            value = {} if action["action"] == "close" else self.answer(action["args"]["call"])
            self.worker.patch("/api/browser/worker/report", json={
                "action_id": action["id"], "lease_token": action["lease_token"], "status": "done", "result": {"value": value},
            })

    def __enter__(self) -> "Executor":
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop.set()
        self.thread.join(timeout=5)


def _tool(client, tool: str, workspace: str, **arguments: Any) -> Any:
    answer = client.post(f"/api/agent/tools/{tool}?workspace_id={workspace}", json={"arguments": arguments})
    assert answer.status_code == 200, answer.text
    return answer.json()


def _graph_answer(call: dict[str, Any]) -> dict[str, Any]:
    assert call == {"op": "readGraph"}
    return {"ok": True, "graph": {"workflow": QWEN, "selection": ["451"], "modified": True, "layer": QWEN["definitions"]["subgraphs"][0]["id"],
                                  "info": {"name": "Qwen 编辑", "path": "", "key": "workflows/Unsaved Workflow.json"}}}


def test_读画布_排一条工作台动作_执行器交给那个连接开着的工作台_回插件压过的摘要(connected) -> None:
    client, comfy, instance_id, workspace = connected
    with Executor(_graph_answer) as desk:
        out = _tool(client, "comfy_canvas_read", workspace, instance_id=instance_id)["result"]
    [action] = desk.claimed
    assert action["action"] == "workbench" and action["kind"] == "workbench"
    assert action["partition"] == f"persist:pool-comfyui-{instance_id}", "执行器据分区认出是哪个连接的工作台"
    assert out["instance_id"] == instance_id and out["modified"] is True
    assert out["workflow"]["name"] == "Qwen 编辑"
    assert out["selection"] == ["459:451"], "停在子图里时,选中的节点换成从根图往里走的写法"
    assert [layer["layer"] for layer in out["layers"]] == ["root", "subgraph"]
    assert "definitions" not in json.dumps(out), "交给智能体的是摘要,不是原文"
    with SessionLocal() as db:
        [session] = db.query(BrowserSession).filter(BrowserSession.kind == browser.WORKBENCH_KIND).all()
        assert session.workspace_id == workspace and session.status == "open"
    with Executor(_graph_answer) as desk:
        _tool(client, "comfy_canvas_read", workspace, instance_id=instance_id)
    with SessionLocal() as db:
        assert db.query(BrowserSession).filter(BrowserSession.kind == browser.WORKBENCH_KIND).count() == 1, "接着用同一个会话"


def test_工作台没开着_执行器不在_都说先在工作台里打开(connected, monkeypatch) -> None:
    client, _, instance_id, workspace = connected
    with Executor(lambda call: {"ok": False, "error": "closed"}):
        out = _tool(client, "comfy_canvas_read", workspace, instance_id=instance_id)
    assert "先在工作台里打开这台 ComfyUI" in out["error"]
    monkeypatch.setattr(browser, "WORKBENCH_QUEUE_SECONDS", 0.5)
    started = time.monotonic()
    out = _tool(client, "comfy_check", workspace, instance_id=instance_id)
    assert "先在工作台里打开这台 ComfyUI" in out["error"] and time.monotonic() - started < 10
    with SessionLocal() as db:
        assert db.query(BrowserAction).filter(BrowserAction.status.in_(("queued", "running"))).count() == 0, "放弃的动作落了终态"


def test_定位_节点按画布的写法_子图里的交给桥先打开那一层(connected) -> None:
    client, _, instance_id, workspace = connected
    calls: list[dict[str, Any]] = []

    def answer(call: dict[str, Any]) -> dict[str, Any]:
        calls.append(call)
        return {"ok": True} if call["node"] != "77" else {"ok": False, "error": "noNode"}

    with Executor(answer):
        assert _tool(client, "comfy_locate", workspace, node="#459:451", instance_id=instance_id)["result"] == {"located": "459:451"}
        out = _tool(client, "comfy_locate", workspace, node="77", instance_id=instance_id)
        bad = _tool(client, "comfy_locate", workspace, node="12; alert(1)", instance_id=instance_id)
    assert calls == [{"op": "locate", "node": "459:451", "subgraph": None}, {"op": "locate", "node": "77", "subgraph": None}]
    assert "没有节点 77" in out["error"]
    assert "不是画布上节点的写法" in bad["error"], "不合规的写法不往桌面端送"


def test_诊断画布上这张_带上那次运行的报错拆到节点(connected) -> None:
    client, _, instance_id, workspace = connected
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="generation", status="failed",
                  error="ComfyUI 拒绝了这张工作流:#459:458 Value not in list: sampler_name: 'x' not in [...]")
        db.add(job)
        db.commit()
        job_id = job.id
    with Executor(_graph_answer):
        out = _tool(client, "comfy_check", workspace, instance_id=instance_id, job_id=job_id)["result"]
    kinds = {(one["ref"], one["kind"]) for one in out["findings"]}
    assert ("459:458", "last_run_error") in kinds and ("459:451", "missing_model") in kinds
    assert out["workflow"]["name"] == "Qwen 编辑" and out["counts"]["error"] >= 2


def test_只问插件的_工作台没开着也能用(connected) -> None:
    client, comfy, instance_id, workspace = connected
    out = _tool(client, "comfy_node_types", workspace, classes=["KSampler"], instance_id=instance_id)["result"]
    assert out["types"][0]["type"] == "KSampler"
    #: 只接了一台:可以不说是哪一台
    out = _tool(client, "comfy_node_types", workspace, query="ksampler")["result"]
    assert out["types"][0]["type"] == "KSampler"
    comfy.state.templates = {"image_qwen_image_2_1_image_edit.json": QWEN}
    out = _tool(client, "comfy_template", workspace, name="image_qwen_image_2_1_image_edit")["result"]
    assert "workflow" not in out and out["summary"]["layers"][0]["layer"] == "root", "整图不交给智能体"
    with SessionLocal() as db:
        assert db.query(BrowserAction).count() == 0, "不碰画布的不排工作台动作"


def test_连接归人_别人的连接_没接_接了好几台(connected) -> None:
    client, comfy, instance_id, workspace = connected
    other = second_client()
    other_ws = other.post("/api/workspaces", json={"name": "O"}).json()["id"]
    out = _tool(other, "comfy_node_types", other_ws, classes=["KSampler"], instance_id=instance_id)
    assert "没找到这个 ComfyUI 连接" in out["error"], "别人接的和不存在的一样"
    out = _tool(other, "comfy_node_types", other_ws, classes=["KSampler"])
    assert "你还没有接 ComfyUI" in out["error"]
    second = _connect(client, comfy)
    out = _tool(client, "comfy_node_types", workspace, classes=["KSampler"])
    assert "好几台" in out["error"] and instance_id in out["error"] and second in out["error"]


def test_空着太久的工作台会话收回时_排的那条关闭不拆视图(connected) -> None:
    client, _, instance_id, workspace = connected
    session_id = browser.workbench_session(workspace_id=workspace, connection_id=instance_id)
    with SessionLocal() as db:
        browser.close_session(db, session_id)
    action = worker_client().post("/api/browser/worker/claim", json={"worker": "desk-1"}).json()["action"]
    assert (action["action"], action["kind"]) == ("close", "workbench"), "执行器看 kind:工作台会话的 close 什么都不拆"


COMFY_TOOLS = {"comfy_canvas_read", "comfy_locate", "comfy_check", "comfy_templates", "comfy_template", "comfy_node_types",
               "comfy_node_packs", "comfy_node_pack_search", "comfy_node_pack_info"}


def test_没接_ComfyUI_的人_每一轮不发_comfy_工具的定义(connected) -> None:
    """工具定义每轮重发(本机模型的回退窗口里有预算,见 test_tool_definitions_budget):用不上的九个工具不占那一块。"""
    client, _, _, _ = connected
    names = {one["name"] for one in client.get("/api/agent/tools").json()}
    assert COMFY_TOOLS <= names
    other = {one["name"] for one in second_client().get("/api/agent/tools").json()}
    assert not other & COMFY_TOOLS
    assert "list_assets" in other, "别的工具照发"
