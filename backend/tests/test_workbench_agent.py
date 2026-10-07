"""工作台里的智能体(ADR 0042 第一、二步)宿主这一侧:`comfy_*` 工具 —— 碰画布的经「后端 → 主进程 → 页面」那条路,别的问插件。
改当前这张先开确认卡(开卡时画布不动,点「应用」才交给桥),新标签页不开卡;都不存盘。

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
from app.domain.agent import autopilot
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
               "comfy_node_packs", "comfy_node_pack_search", "comfy_node_pack_info", "comfy_canvas_edit", "comfy_canvas_new"}


def test_没接_ComfyUI_的人_每一轮不发_comfy_工具的定义(connected) -> None:
    """工具定义每轮重发(本机模型的回退窗口里有预算,见 test_tool_definitions_budget):用不上的这几个工具不占那一块。"""
    client, _, _, _ = connected
    names = {one["name"] for one in client.get("/api/agent/tools").json()}
    assert COMFY_TOOLS <= names
    other = {one["name"] for one in second_client().get("/api/agent/tools").json()}
    assert not other & COMFY_TOOLS
    assert "list_assets" in other, "别的工具照发"


# --- 改画布、开新标签(ADR 0042 第二步) ----------------------------------------------------------

def _simple() -> dict[str, Any]:
    """画布上开着的一张最普通的文生图(界面格式,和前端 graphToPrompt 交出来的一样)。"""
    def out(name: str, kind: str, links: list[int]) -> dict[str, Any]:
        return {"name": name, "type": kind, "links": links}

    def inp(name: str, kind: str, link: int | None) -> dict[str, Any]:
        return {"name": name, "type": kind, "link": link}

    nodes = [
        {"id": 4, "type": "CheckpointLoaderSimple", "inputs": [], "outputs": [out("MODEL", "MODEL", [1]), out("CLIP", "CLIP", [2, 3]),
         out("VAE", "VAE", [4])], "widgets_values": ["sd_xl_base_1.0.safetensors"], "mode": 0},
        {"id": 6, "type": "CLIPTextEncode", "inputs": [inp("clip", "CLIP", 2)], "outputs": [out("CONDITIONING", "CONDITIONING", [5])],
         "widgets_values": ["a cat"], "mode": 0},
        {"id": 7, "type": "CLIPTextEncode", "inputs": [inp("clip", "CLIP", 3)], "outputs": [out("CONDITIONING", "CONDITIONING", [6])],
         "widgets_values": ["blurry"], "mode": 0},
        {"id": 5, "type": "EmptyLatentImage", "inputs": [], "outputs": [out("LATENT", "LATENT", [7])], "widgets_values": [1024, 1024, 1],
         "mode": 0},
        {"id": 3, "type": "KSampler", "inputs": [inp("model", "MODEL", 1), inp("positive", "CONDITIONING", 5),
         inp("negative", "CONDITIONING", 6), inp("latent_image", "LATENT", 7)], "outputs": [out("LATENT", "LATENT", [8])],
         "widgets_values": [42, "fixed", 20, 7, "euler", "simple", 1], "mode": 0},
        {"id": 8, "type": "VAEDecode", "inputs": [inp("samples", "LATENT", 8), inp("vae", "VAE", 4)], "outputs": [out("IMAGE", "IMAGE", [9])],
         "widgets_values": [], "mode": 0},
        {"id": 9, "type": "SaveImage", "inputs": [inp("images", "IMAGE", 9)], "outputs": [], "widgets_values": ["ComfyUI"], "mode": 0},
    ]
    links = [[1, 4, 0, 3, 0, "MODEL"], [2, 4, 1, 6, 0, "CLIP"], [3, 4, 1, 7, 0, "CLIP"], [4, 4, 2, 8, 1, "VAE"],
             [5, 6, 0, 3, 1, "CONDITIONING"], [6, 7, 0, 3, 2, "CONDITIONING"], [7, 5, 0, 3, 3, "LATENT"], [8, 3, 0, 8, 0, "LATENT"],
             [9, 8, 0, 9, 0, "IMAGE"]]
    return {"last_node_id": 9, "last_link_id": 9, "nodes": nodes, "links": links, "version": 0.4}


class Canvas:
    """画布上开着的那一张:读到的是它现在的样子;桥接了一批就换成改后的样子(这里由测试给)。记下每一次调用。"""

    def __init__(self, graph: dict[str, Any], key: str = "workflows/人像.json", name: str = "人像",
                 after: dict[str, Any] | None = None) -> None:
        self.graph, self.key, self.name, self.after = graph, key, name, after
        self.calls: list[dict[str, Any]] = []

    def __call__(self, call: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(call)
        if call["op"] == "readGraph":
            return {"ok": True, "graph": {"workflow": self.graph, "selection": [], "modified": False, "layer": None,
                                          "info": {"name": self.name, "path": self.key.removeprefix("workflows/"), "key": self.key,
                                                   "temporary": False}}}
        if call["op"] == "applyOps":
            if self.after is not None:
                self.graph = self.after
            return {"ok": True, "created": {one["id"]: "21" for one in call["ops"] if one["op"] == "add_node"}}
        if call["op"] == "openWorkflow":
            self.key = f"workflows/{call.get('name')}.json"
            self.name = call.get("name") or ""
            self.graph = call.get("graph") or self.graph
            return {"ok": True, "workflow": {"path": self.key, "name": self.name, "temporary": "graph" in call},
                    "created": {one["id"]: "30" for one in call.get("ops") or [] if one["op"] == "add_node"}}
        return {"ok": False, "error": "unsupported"}

    def ops(self) -> list[str]:
        return [call["op"] for call in self.calls]


LORA = [
    {"op": "add_node", "id": "$l", "type": "LoraLoader", "widgets": {"lora_name": "add_detail.safetensors", "strength_model": 0.6}},
    {"op": "connect", "from": "4.MODEL", "to": "$l.model"},
    {"op": "connect", "from": "4.CLIP", "to": "$l.clip"},
    {"op": "connect", "from": "$l.MODEL", "to": "3.model"},
    {"op": "set_widget", "node": "3", "widget": "steps", "value": 30},
]


def _card(client, confirmation_id: str) -> dict[str, Any]:
    return client.get(f"/api/confirmations/{confirmation_id}").json()


def _cards(client, workspace: str) -> list[dict[str, Any]]:
    return client.get(f"/api/confirmations?workspace_id={workspace}").json()


def test_改画布_先开确认卡_开卡时画布一点没动_卡上是改动清单(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple())
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_edit", workspace, ops=LORA, instance_id=instance_id)["result"]
        assert autopilot.wait_for_idle_autopilot(), "没有自动放行的线程在跑"
        assert _card(client, out["confirmation_id"])["status"] == "pending", "手动模式下等人点「应用」,不自己放行"
    assert out["status"] == "pending"
    assert canvas.ops() == ["readGraph"], "开卡只读了一次画布,什么都没改"
    card = _card(client, out["confirmation_id"])
    assert card["tool"] == "comfy_canvas_edit" and card["permission"] == "edit"
    assert "「人像」" in card["summary"] and "5 处改动" in card["summary"] and "Ctrl+Z" in card["summary"]
    payload = card["payload"]
    assert payload["instance_id"] == instance_id and payload["workflow"]["key"] == "workflows/人像.json"
    assert [one["op"] for one in payload["changes"]] == ["add_node", "connect", "connect", "connect", "set_widget"]
    assert payload["changes"][3]["replaces"] == {"node": "4", "output": "MODEL"}, "接进 3.model 的那根原来来自 #4,清单上写明换掉了谁"
    assert payload["changes"][4] == {"op": "set_widget", "node": "3", "type": "KSampler", "widget": "steps", "before": 20, "after": 30}
    assert payload["check"]["before"]["error"] == payload["check"]["after"]["error"], "改前改后各诊断一次"


def test_点应用之后_对着现在的画布再算一遍_对得上才交给桥_改完再诊断_说修好了几个(connected) -> None:
    client, _, instance_id, workspace = connected
    broken = _simple()
    broken["nodes"][4]["widgets_values"][4] = "no_such_sampler"
    canvas = Canvas(broken, after=_simple())
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id,
                    ops=[{"op": "set_widget", "node": "3", "widget": "sampler_name", "value": "euler"}])["result"]
        card = _card(client, out["confirmation_id"])
        assert card["payload"]["check"]["fixed"][0]["kind"] == "combo_not_in_list", "卡上就说这一批会修好哪几个"
        approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "executed", approved
    assert canvas.ops() == ["readGraph", "readGraph", "applyOps", "readGraph"], "批之后再读一遍、交给桥一批、改完再读一遍"
    [applied] = [call for call in canvas.calls if call["op"] == "applyOps"]
    assert applied["ops"] == [{"op": "set_widget", "node": "3", "widget": "sampler_name", "value": "euler", "layer": None}]
    result = approved["result"]
    assert result["applied"] == 1 and result["workflow"]["name"] == "人像"
    assert [one["kind"] for one in result["fixed"]] == ["combo_not_in_list"] and result["introduced"] == []


def test_一条说不通_整批不开卡_每一条的原因交回智能体(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple())
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id, ops=[
            {"op": "set_widget", "node": "3", "widget": "steps", "value": 30},
            {"op": "set_widget", "node": "3", "widget": "sampler_name", "value": "dpm_9000"},
            {"op": "connect", "from": "4.VAE", "to": "3.model"},
            {"op": "remove_node", "node": "77"},
        ])
    assert "一条都没改" in out["error"] and "第 2 条" in out["error"] and "第 3 条" in out["error"]
    assert canvas.ops() == ["readGraph"]
    assert _cards(client, workspace) == [], "没开卡"


def test_改完会多出错误的_不交给用户批_说给智能体让它重改(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple())
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id, ops=[{"op": "disconnect", "to": "3.positive"}])
    assert "多出 1 个错误" in out["error"] and "positive" in out["error"]
    assert canvas.ops() == ["readGraph"]
    assert _cards(client, workspace) == []


def test_批之前换了一张_或者又改过_清单对不上_一样不改(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple())
    with Executor(canvas):
        first = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id, ops=LORA)["result"]
        second = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id, ops=LORA)["result"]
        canvas.key, canvas.name = "workflows/别的.json", "别的"
        other_tab = client.post(f"/api/confirmations/{first['confirmation_id']}/approve").json()
        canvas.key, canvas.name = "workflows/人像.json", "人像"
        canvas.graph["nodes"][4]["widgets_values"][2] = 25  # 用户在 ComfyUI 里把 steps 改成了 25
        stale = client.post(f"/api/confirmations/{second['confirmation_id']}/approve").json()
    assert other_tab["status"] == "failed" and "已经不是「人像」" in other_tab["error"]
    assert stale["status"] == "failed" and "对不上" in stale["error"]
    assert "applyOps" not in canvas.ops()


def test_改子图的定义_卡上写明这张图里用了几处_都会变(connected) -> None:
    client, _, instance_id, workspace = connected
    graph = json.loads(json.dumps(QWEN))
    twin = json.loads(json.dumps(next(one for one in graph["nodes"] if one["id"] == 459)))
    twin.update(id=900, inputs=[one for one in twin["inputs"] if one.get("widget")], outputs=[{**twin["outputs"][0], "links": []}])
    graph["nodes"].append(twin)
    canvas = Canvas(graph, key="workflows/Qwen.json", name="Qwen")
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id,
                    ops=[{"op": "set_widget", "node": "459:458", "widget": "denoise", "value": 0.8}])["result"]
    card = _card(client, out["confirmation_id"])
    sub = QWEN["definitions"]["subgraphs"][0]["id"]
    assert card["payload"]["subgraphs"] == [{"id": sub, "name": "Image Edit (Qwen Image 2.1)", "uses": 2}]
    assert card["payload"]["changes"][0]["layer"]["uses"] == 2
    assert "用了 2 处" in card["warning"] and "每一处都会变" in card["warning"], "卡上单独一条提示"


def test_新标签页_模板照这台机器改好_在新标签页打开_从不存盘_不开卡(connected) -> None:
    client, comfy, instance_id, workspace = connected
    comfy.state.templates = {"image_qwen_image_2_1_image_edit.json": QWEN}
    canvas = Canvas(_simple())
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_new", workspace, instance_id=instance_id, template="image_qwen_image_2_1_image_edit",
                    name="Qwen 编辑", ops=[{"op": "set_widget", "node": "459", "widget": "steps", "value": 30}])["result"]
    assert canvas.ops() == ["openWorkflow", "readGraph"], "开一个新标签、读一遍诊断;没有 save"
    opened = canvas.calls[0]
    assert opened["name"] == "Qwen 编辑" and opened["graph"]["definitions"]["subgraphs"][0]["name"] == "Image Edit (Qwen Image 2.1)"
    assert opened["ops"] == [{"op": "set_widget", "node": "459", "widget": "steps", "value": 30, "layer": None}]
    assert out["saved"] is False and out["opened"] == {"name": "Qwen 编辑", "temporary": True, "path": ""}
    assert "missing" in {one["status"] for one in out["template"]["models"]}, "缺的模型(连同大小)交给智能体说"
    assert out["check"]["counts"]["error"] >= 1 and out["changes"] == 1
    assert _cards(client, workspace) == [], "新标签页不动开着的,不开卡"


def test_新标签页_打开存着的那一张_或者从空白搭(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple())
    with Executor(canvas):
        saved = _tool(client, "comfy_canvas_new", workspace, instance_id=instance_id, path="人像/古风.json")["result"]
        built = _tool(client, "comfy_canvas_new", workspace, instance_id=instance_id, name="从空白搭",
                      ops=[{"op": "add_node", "id": "$k", "type": "KSampler"}, {"op": "add_node", "id": "$e", "type": "EmptyLatentImage"},
                           {"op": "connect", "from": "$e.LATENT", "to": "$k.latent_image"}])["result"]
        both = _tool(client, "comfy_canvas_new", workspace, instance_id=instance_id, template="x", path="a.json")
        nothing = _tool(client, "comfy_canvas_new", workspace, instance_id=instance_id)
    assert canvas.calls[0] == {"op": "openWorkflow", "path": "人像/古风.json"}
    [blank] = [call for call in canvas.calls if call["op"] == "openWorkflow" and "graph" in call]
    assert blank["graph"]["nodes"] == [] and [one["op"] for one in blank["ops"]] == ["add_node", "add_node", "connect"]
    assert built["created"] == {"$k": "30", "$e": "30"} and saved["saved"] is False
    assert "只能给一样" in both["error"] and "要给点东西" in nothing["error"]
