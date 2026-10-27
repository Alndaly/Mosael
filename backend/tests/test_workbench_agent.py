"""工作台里的智能体(ADR 0042 第一、二步)宿主这一侧:`comfy_*` 工具 —— 碰画布的经「后端 → 主进程 → 页面」那条路,别的问插件。
改当前这张先开确认卡(开卡时画布不动,点「应用」才交给桥),新标签页不开卡;都不存盘。

画布那条路和浏览器动作是同一套(见 domain/browser 的 workbench_session / run_workbench):工具排一条 `workbench` 动作在这个
工作区对这个连接的工作台会话上,执行器(这里是一个线程,经 /api/browser/worker/* 那几个口,和 electron 的 browserWorker 一样)
领走、交给那个连接开着的工作台、报回桥的回答。工作台没开着(桥说 closed)、执行器根本不在,都说「先在工作台里打开这台 ComfyUI」。

插件那一侧对着 tests/fake_comfyui.py 真跑(插件进程)。
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserAction, BrowserSession, Job
from app.domain import browser, model_library, workbench_agent
from app.domain.agent import autopilot
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client, second_client, wait_status, worker_client

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
    missing = next(one for one in out["findings"] if one["ref"] == "459:451" and one["kind"] == "missing_model")
    assert missing["model"]["name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert missing["model"]["folder"] == "diffusion_models"
    assert missing["model"]["url"].startswith("https://huggingface.co/"), \
        "模板写着下载地址:结构化字段里有它 —— 智能体照它发起下载,不从 fix 里猜"
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
               "comfy_node_packs", "comfy_node_pack_search", "comfy_node_pack_info", "comfy_canvas_edit", "comfy_canvas_new",
               "comfy_model_search", "comfy_model_resolve", "comfy_model_download", "comfy_node_pack_install", "comfy_canvas_run"}


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


#: 桥「运行」导出的 API 格式图(`graphToPrompt` 的 `output`):一份最小、能交给那台 ComfyUI 的。
EXPORTED_PROMPT: dict[str, Any] = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "canvas", "images": ["4", 0]}},
}


class Canvas:
    """画布上开着的那一张:读到的是它现在的样子;桥接了一批就换成改后的样子(这里由测试给)。记下每一次调用。

    `revision` 是这一张改过几回(桥的轮询 / readGraph 报的);改图时和桥一样先比 `expect`:不是读的那一张、读过之后又改过就不改。
    `after_next_read`:下一次读完之后画布上发生的事(重读和交给桥之间,用户在 ComfyUI 里换了一张、又改了一笔)。
    `export_key`:导出那一刻报回的是哪一张(默认就是当前这张;设成别的模拟「重读之后、导出之前换了标签页」)。"""

    def __init__(self, graph: dict[str, Any], key: str = "workflows/人像.json", name: str = "人像",
                 after: dict[str, Any] | None = None, temporary: bool = False) -> None:
        self.graph, self.key, self.name, self.after = graph, key, name, after
        self.temporary = temporary
        self.export_key: str = ""
        self.revision = 1
        self.after_next_read: Any = None
        self.calls: list[dict[str, Any]] = []

    def __call__(self, call: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(call)
        if call["op"] == "readGraph":
            answer = {"ok": True, "graph": {"workflow": copy.deepcopy(self.graph), "selection": [], "modified": False,
                                            "revision": self.revision, "layer": None,
                                            "info": {"name": self.name,
                                                     "path": "" if self.temporary else self.key.removeprefix("workflows/"),
                                                     "key": self.key, "temporary": self.temporary}}}
            then, self.after_next_read = self.after_next_read, None
            if then is not None:
                then()
            return answer
        if call["op"] == "runControls":
            return {"ok": True}
        if call["op"] == "export":
            #: 桥的「运行」导出:界面格式 + API 格式 + 前端的 clientId(见 electron/publish/comfyWorkbench.ts)
            return {"ok": True, "export": {"workflow": copy.deepcopy(self.graph), "prompt": EXPORTED_PROMPT,
                                           "clientId": "4f1c0e2a9b7d4c51a3e8",
                                           "at": {"key": self.export_key or self.key, "revision": self.revision}}}
        if call["op"] == "applyOps":
            expect = call.get("expect") or {}
            if expect.get("key") != self.key:
                return {"error": "otherWorkflow"}
            if expect.get("revision") != self.revision:
                return {"error": "changed"}
            self.revision += 1
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


def test_重读之后_插件算的那一下里换了一张_或者又改了一笔_桥那边一样不改(connected) -> None:
    """PLG-17:批准之后重读画布、插件对着读到的那份算这一批、再交给桥 —— 中间这一下用户在 ComfyUI 里换到同一个模板改出来的
    另一张(节点号一样),此前这一批照样改进那一张。现在改图带着重读时的 key 和改过几回,桥在页面里比。"""
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple())
    with Executor(canvas):
        first = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id, ops=LORA)["result"]
        second = _tool(client, "comfy_canvas_edit", workspace, instance_id=instance_id, ops=LORA)["result"]

        def switch() -> None:
            canvas.key, canvas.name = "workflows/人像 2.json", "人像 2"

        canvas.after_next_read = switch
        other_tab = client.post(f"/api/confirmations/{first['confirmation_id']}/approve").json()
        canvas.key, canvas.name = "workflows/人像.json", "人像"
        canvas.after_next_read = lambda: setattr(canvas, "revision", canvas.revision + 1)
        stale = client.post(f"/api/confirmations/{second['confirmation_id']}/approve").json()
    applied = [call for call in canvas.calls if call["op"] == "applyOps"]
    assert [call["expect"] for call in applied] == [{"key": "workflows/人像.json", "revision": 1},
                                                   {"key": "workflows/人像.json", "revision": 1}], "带的是重读时的那一张"
    assert other_tab["status"] == "failed" and "已经不是「人像」" in other_tab["error"], other_tab
    assert stale["status"] == "failed" and "对不上" in stale["error"], stale
    assert canvas.graph == _simple(), "一样都没改"


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


def test_新标签页_带上是哪段对话开的_按凭据认_不按参数(connected) -> None:
    """ADR 0044 §6:主进程开好新标签页后随状态报回 `openedBy`,工作台让那一处接住这段对话。会话是凭据认出来的。"""
    from app.core.security import mint_service_session
    from tests.util import user_id

    client, _, instance_id, workspace = connected
    session = client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": {"kind": "comfyui", "id": instance_id}})
    session_id = session.json()["id"]
    with SessionLocal() as db:
        token = mint_service_session(db, user_id(), agent_session_id=session_id)
        db.commit()
    canvas = Canvas(_simple())
    with Executor(canvas):
        for arguments in ({"path": "人像/古风.json"}, {"name": "从空白搭", "ops": [{"op": "add_node", "id": "$k", "type": "KSampler"}]}):
            answer = client.post(f"/api/agent/tools/comfy_canvas_new?workspace_id={workspace}",
                                 json={"arguments": {"instance_id": instance_id, **arguments}},
                                 headers={"Authorization": f"Bearer {token}"})
            assert answer.status_code == 200 and "result" in answer.json(), answer.text
    opened = [call for call in canvas.calls if call["op"] == "openWorkflow"]
    assert [call.get("openedBy") for call in opened] == [session_id, session_id]


# --- 补全和试跑(ADR 0042 第三步:下载模型、装节点包、试跑) ------------------------------------------

STEP_THREE = {"comfy_model_search", "comfy_model_resolve", "comfy_model_download", "comfy_node_pack_install",
              "comfy_canvas_run"}
DOWNLOAD_URL = "https://huggingface.co/Comfy-Org/flux/resolve/main/flux1-dev-fp8.safetensors"
DIGEST = "ab" * 32


def _resolved(**overrides: Any) -> dict[str, Any]:
    out = {"source": "huggingface", "url": DOWNLOAD_URL, "page": "https://huggingface.co/Comfy-Org/flux",
           "filename": "flux1-dev-fp8.safetensors", "size": 17_246_524_772, "folder": "checkpoints",
           "family": "Flux", "triggers": [], "title": "FLUX.1 dev", "exists": False, "uses_token": True, "note": ""}
    out.update(overrides)
    return out


def _pack_info(**overrides: Any) -> dict[str, Any]:
    """`comfy_node_pack_info` 交回来的那一份(形状照插件的 node_packs.node_pack_info)。注册表那一下在测试里换掉。"""
    out = {
        "id": "rgthree-comfy", "name": "rgthree's ComfyUI Nodes", "publisher": "Regis Gaughan, III (rgthree)",
        "newest_version": {"version": "1.0.2610050029", "status": "NodeVersionStatusFlagged", "deprecated": False,
                           "date": "2026-10-05"},
        "install_version": "1.0.2608210019", "dependency_risk": "low", "torch_touching": [],
        "compatibility": {"os": {"ok": True}, "accelerator": {"ok": True}, "comfyui": {"ok": True}},
        "advice": [],
    }
    out.update(overrides)
    return out


class _Job:
    """`start_download` 交回来的后台任务(真的那个由任务中心那一套管,这里只看交回去的是什么)。"""

    def __init__(self, job_id: str, kind: str) -> None:
        self.id, self.kind = job_id, kind


def test_补全和试跑的五个工具_都在工作台那一份_只读和确认卡分得清() -> None:
    """发现成本那一条(ADR 0042 §7):五个工具都跟着 ComfyUI 工作台那一份发,都要工作流库;三个会改那台机器的开确认卡,
    两个只读的不开 —— 而且三个确认卡都在登记表里(不然点「批准」那一刻才报 Unknown mutating tool)。"""
    import mcp_server
    from app.domain.agent.confirmable import tool_specs

    assert STEP_THREE <= set(mcp_server.REGISTERED_TOOLS)
    for name in STEP_THREE:
        assert mcp_server.TOOL_KITS.get(name) == "comfyui", name
        assert mcp_server.TOOL_NEEDS.get(name) == "workflow_library", name
    assert {name for name in STEP_THREE if name in mcp_server.READ_ONLY_TOOLS} == \
        {"comfy_model_search", "comfy_model_resolve"}
    confirming = {"comfy_model_download", "comfy_node_pack_install", "comfy_canvas_run"}
    assert STEP_THREE & mcp_server.CONFIRMATION_TOOLS == confirming
    assert confirming <= set(tool_specs()), "确认卡工具必须登记:否则批准时报 Unknown mutating tool"


def test_按文件名找下载地址_只读_只问插件(connected, monkeypatch) -> None:
    client, _, instance_id, workspace = connected
    asked: list[tuple[Any, ...]] = []

    def fake(db, instance, filename, folder="", digest="", hash_type=""):
        asked.append((instance.id, filename, folder, digest, hash_type))
        return {"filename": filename, "candidates": [
            {"source": "huggingface", "filename": filename, "url": DOWNLOAD_URL, "confidence": "confirmed",
             "direct": True, "sha256": DIGEST, "size": 17_246_524_772}],
            "failed": [], "hash": {"state": "matched", "reason": "", "sha256": DIGEST, "note": ""}}

    monkeypatch.setattr(model_library, "search_sources", fake)
    out = _tool(client, "comfy_model_search", workspace, filename="flux1-dev-fp8.safetensors", folder="checkpoints",
                hash=DIGEST, hash_type="sha256", instance_id=instance_id)["result"]
    assert out["instance_id"] == instance_id and out["candidates"][0]["direct"] is True
    assert asked == [(instance_id, "flux1-dev-fp8.safetensors", "checkpoints", DIGEST, "sha256")]
    assert "文件名" in _tool(client, "comfy_model_search", workspace, filename="")["error"]
    with SessionLocal() as db:
        assert db.query(BrowserAction).count() == 0, "只读的不排工作台动作"


def test_解析链接_只读_不是_http_的当场拒绝(connected, monkeypatch) -> None:
    client, _, instance_id, workspace = connected
    bad = _tool(client, "comfy_model_resolve", workspace, url="file:///etc/passwd", instance_id=instance_id)
    assert "http:// 或 https://" in bad["error"]
    monkeypatch.setattr(model_library, "resolve", lambda db, instance, url: _resolved(url=url))
    out = _tool(client, "comfy_model_resolve", workspace, url=DOWNLOAD_URL, instance_id=instance_id)["result"]
    assert out["instance_id"] == instance_id and out["filename"] == "flux1-dev-fp8.safetensors"
    assert out["folder"] == "checkpoints" and out["size"] == 17_246_524_772 and out["exists"] is False


def test_下载模型_先开确认卡_写明文件名_大小_目录_哪台机器_批准之后排一个下载任务(connected, monkeypatch) -> None:
    client, _, instance_id, workspace = connected
    started: dict[str, Any] = {}

    monkeypatch.setattr(model_library, "resolve", lambda db, instance, url: _resolved(url=url))

    def fake_start(db, user, instance, *, workspace_id, url, folder, filename, sha256=""):
        started.update({"instance": instance.id, "workspace_id": workspace_id, "url": url, "folder": folder,
                        "filename": filename, "sha256": sha256, "user": user.id})
        return _Job("job-dl-1", "model_download")

    monkeypatch.setattr(model_library, "start_download", fake_start)
    out = _tool(client, "comfy_model_download", workspace, url=DOWNLOAD_URL, folder="checkpoints",
                filename="flux1-dev-fp8.safetensors", sha256=DIGEST.upper(), instance_id=instance_id)["result"]
    assert out["status"] == "pending" and started == {}, "开卡之前一样没开始下"
    card = _card(client, out["confirmation_id"])
    assert card["permission"] == "external"
    assert "flux1-dev-fp8.safetensors" in card["summary"] and "checkpoints" in card["summary"]
    assert "16.1 GB" in card["summary"], "卡上写明多大"
    assert "huggingface" in card["summary"], "卡上写明从哪个站来"
    approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "executed", approved
    assert approved["result"]["job_id"] == "job-dl-1" and approved["result"]["kind"] == "model_download"
    assert started.pop("user"), "任务记的是批准这张卡的那个人"
    assert started == {"instance": instance_id, "workspace_id": workspace, "url": DOWNLOAD_URL,
                       "folder": "checkpoints", "filename": "flux1-dev-fp8.safetensors", "sha256": DIGEST}


@pytest.mark.parametrize("resolved, arguments, fragment", [
    (_resolved(filename="another.safetensors"), {}, "不是「flux1-dev-fp8.safetensors」"),
    (_resolved(exists=True), {}, "已经有「flux1-dev-fp8.safetensors」"),
    (_resolved(), {"filename": "../evil.safetensors"}, "文件名"),
    (_resolved(), {"folder": "checkpoints/evil"}, "目录"),
    (_resolved(), {"sha256": "not-a-sha256"}, "不是 SHA256"),
])
def test_下载模型_链接对不上文件_已经有了_名字不合法_都不开卡(connected, monkeypatch, resolved, arguments, fragment) -> None:
    """卡上写的必须是待会儿真要下的那一个文件:认出来的是别的文件名、那台机器上已经有、名字带路径、哈希不是 SHA256 ——
    都在开卡之前拒,一张卡也不留。"""
    client, _, instance_id, workspace = connected
    monkeypatch.setattr(model_library, "resolve", lambda db, instance, url: resolved)
    monkeypatch.setattr(model_library, "start_download",
                        lambda *args, **kwargs: pytest.fail("没开卡就不该开始下"))
    out = _tool(client, "comfy_model_download", workspace, instance_id=instance_id,
                **{"url": DOWNLOAD_URL, "folder": "checkpoints", "filename": "flux1-dev-fp8.safetensors", **arguments})
    assert fragment in out["error"]
    assert _cards(client, workspace) == []


def test_装节点包_git地址_封禁_没有正常版本_装过了_停用的都不开卡(connected, monkeypatch) -> None:
    client, _, instance_id, workspace = connected
    cases = [
        ("https://github.com/someone/ComfyUI-Only-On-Git", _pack_info(), "注册表"),
        ("someone/ComfyUI-Only-On-Git", _pack_info(), "注册表"),
        ("comfyui-reactor-node",
         _pack_info(id="comfyui-reactor-node", install_version="0.5.2-b1",
                    newest_version={"version": "0.5.2-b1", "status": "NodeVersionStatusBanned", "deprecated": False}),
         "封禁"),
        ("comfyui-only-flagged",
         _pack_info(id="comfyui-only-flagged", install_version="2.0.0",
                    newest_version={"version": "2.0.0", "status": "NodeVersionStatusFlagged", "deprecated": False}),
         "不装"),
        ("comfyui-installed",
         _pack_info(installed={"version": "1.0.2608210019", "enabled": True}), "已经装着了"),
        ("comfyui-off",
         _pack_info(installed={"version": "1.0.2608210019", "enabled": False}), "停用"),
    ]
    for pack_id, info, fragment in cases:
        monkeypatch.setattr(workbench_agent, "node_pack_info", lambda *args, _info=info, **kwargs: _info)
        monkeypatch.setattr(workbench_agent, "install_node_pack",
                            lambda *args, **kwargs: pytest.fail("没开卡就不该装"))
        out = _tool(client, "comfy_node_pack_install", workspace, pack_id=pack_id, instance_id=instance_id)
        assert fragment in out["error"], (pack_id, out)
    assert _cards(client, workspace) == []


def test_批准后注册表变成封禁_执行前再拒一次(connected, monkeypatch) -> None:
    """确认卡是隔天批的:validate 时正常不等于执行时仍正常。执行前必须重查注册表,
    被封禁的包连 start_node_install 都不许发。"""
    client, _, instance_id, workspace = connected
    banned = _pack_info(pack_status="NodeStatusBanned")
    monkeypatch.setattr(workbench_agent, "node_pack_info", lambda *args, **kwargs: banned)

    def should_not_start(*_args, **_kwargs):
        pytest.fail("封禁的包不该进入安装任务")

    from app.db.models import User
    from app.domain import workflow_library

    monkeypatch.setattr(workflow_library, "start_node_install", should_not_start)
    with SessionLocal() as db:
        user = db.query(User).first()
        with pytest.raises(workbench_agent.WorkbenchAgentError) as caught:
            workbench_agent.install_node_pack(
                db,
                user,
                workspace,
                {"instance_id": instance_id, "pack_id": "rgthree-comfy", "pack": "rgthree-comfy", "version": "1.0.2608210019"},
            )
        assert caught.value.key == "workbenchErr_packBanned"

def test_装节点包_给的那一版不是注册表里正常的那个_不替它猜(connected, monkeypatch) -> None:
    client, _, instance_id, workspace = connected
    monkeypatch.setattr(workbench_agent, "node_pack_info", lambda *args, **kwargs: _pack_info())
    out = _tool(client, "comfy_node_pack_install", workspace, pack_id="rgthree-comfy", version="9.9.9",
                instance_id=instance_id)
    assert "9.9.9" in out["error"] and "1.0.2608210019" in out["error"]
    assert _cards(client, workspace) == []


def test_装节点包_卡上写版本_发布者_风险_装完等任务落终态再重启再读目录(connected, monkeypatch) -> None:
    """ADR 0042 §7 + 拍板 4:只装注册表里正常的那一版;卡上写发布者、版本、会不会动 PyTorch、装完要重启。
    批准之后:起装的任务 → **等它落终态** → 重启那台 ComfyUI → 读目录说现在装的是哪一版。"""
    client, comfy, instance_id, workspace = connected
    comfy.state.manager = "V4.2.1"
    monkeypatch.setattr(workbench_agent, "node_pack_info", lambda *args, **kwargs: _pack_info(
        torch_touching=["torch>=2.4.0"], dependency_risk="high",
        compatibility={"os": {"ok": True}, "accelerator": {"ok": False}, "comfyui": {"ok": True}}))
    with Executor(Canvas(_simple())):
        out = _tool(client, "comfy_node_pack_install", workspace, pack_id="rgthree-comfy",
                    instance_id=instance_id)["result"]
    assert out["status"] == "pending"
    card = _card(client, out["confirmation_id"])
    assert card["permission"] == "external"
    summary = card["summary"]
    assert "rgthree's ComfyUI Nodes" in summary and "1.0.2608210019" in summary
    assert "发布者" in summary and "Regis Gaughan" in summary, "谁发布的写上"
    assert "Flagged" in summary, "最新一版被标记:装的是它之前那个正常版本"
    assert "PyTorch" in summary and "加速器" in summary, "依赖风险和和这台机器合不合都说"
    assert "重启" in summary and "中断" in summary
    #: 卡上那两格是**分开**渲染的(`confirmations.card_parts`):标题一句话,后果提示单独一行。
    #: 几条注意必须都在那一格里(此前它们是一个列表,标题和提示两格都空)。
    assert "装节点包" in card["headline"] and "重启" in card["headline"]
    assert "Flagged" not in card["headline"], "后果提示单独一行,不混进标题"
    warning = card["warning"]
    assert "最新的一版" in warning and "Flagged" in warning
    assert "PyTorch" in warning and "torch>=2.4.0" in warning
    assert "accelerator" in warning and "加速器" in warning
    assert card["payload"]["version"] == "1.0.2608210019"

    approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "executed", approved
    result = approved["result"]
    assert result["pack"] == "rgthree-comfy" and result["version"] == "1.0.2608210019"
    assert result["restarted"] is True and result["catalog_version"] == "1.0.0", "重启之后目录里读回来的那一版"
    paths = [one[1] for one in comfy.state.calls]
    assert paths.index("/v2/manager/queue/task") < paths.index("/v2/manager/reboot"), "装完才重启"
    with SessionLocal() as db:
        [job] = db.query(Job).filter(Job.kind == "node_install").all()
        assert job.status == "succeeded" and [one[1] for one in comfy.state.calls].count("/v2/manager/reboot") == 1


def test_试跑_开卡之前说清是哪一张_批准之后导出_建一个普通的生成任务(connected) -> None:
    client, comfy, instance_id, workspace = connected
    canvas = Canvas(_simple(), key="workflows/portrait.json", name="portrait")
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_run", workspace, instance_id=instance_id)["result"]
        assert out["status"] == "pending"
        assert canvas.ops() == ["readGraph"], "开卡只读了画布,没导出、没跑"
        card = _card(client, out["confirmation_id"])
        assert card["permission"] == "render-cost"
        assert "portrait" in card["summary"] and "portrait.json" in card["summary"], "卡上写跑的是哪一张"
        approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "executed", approved
    assert canvas.ops() == ["readGraph", "readGraph", "runControls", "export", "runControls"], \
        "批准之后:核对还是那一张 → 「运行」前换种子 → 导出 → 建任务 → 「运行」后换种子"
    assert [call["phase"] for call in canvas.calls if call["op"] == "runControls"] == ["before", "after"]
    result = approved["result"]
    assert result["workflow"]["path"] == "portrait.json" and result["kind"] == "image"
    assert wait_status(client, result["job_id"]) == "succeeded"
    submitted = comfy.posted("/prompt")[0]
    assert submitted["prompt"] == EXPORTED_PROMPT, "画布上导出的图原样提交"
    assert submitted["client_id"] == "4f1c0e2a9b7d4c51a3e8"


def test_试跑_只跑一个输出节点_确认卡写节点_提交带部分执行目标(connected) -> None:
    client, comfy, instance_id, workspace = connected
    canvas = Canvas(_simple(), key="workflows/portrait.json", name="portrait")
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_run", workspace, instance_id=instance_id, node_id="9")["result"]
        card = _card(client, out["confirmation_id"])
        assert "只跑输出节点 #9" in card["summary"]
        approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "executed", approved
    submitted = comfy.posted("/prompt")[0]
    assert submitted["partial_execution_targets"] == ["9"], "只执行这个输出节点和它的上游"
    assert submitted["prompt"] == EXPORTED_PROMPT


def test_试跑_指定了画布上没有的节点_不提交(connected) -> None:
    client, comfy, instance_id, workspace = connected
    canvas = Canvas(_simple(), key="workflows/portrait.json", name="portrait")
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_run", workspace, instance_id=instance_id, node_id="99")["result"]
        approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "failed" and "#99" in approved["error"]
    assert comfy.posted("/prompt") == [], "节点不存在时一张都不提交"


def test_试跑_从没存过的那张不开卡_先说去存(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple(), key="workflows/Unsaved Workflow.json", name="未命名", temporary=True)
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_run", workspace, instance_id=instance_id)
    assert "还没存过" in out["error"] and "Ctrl+S" in out["error"]
    assert canvas.ops() == ["readGraph"]
    assert _cards(client, workspace) == []


def test_试跑_开卡之后画布上换了一张_不跑(connected) -> None:
    client, _, instance_id, workspace = connected
    canvas = Canvas(_simple(), key="workflows/portrait.json", name="portrait")
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_run", workspace, instance_id=instance_id)["result"]
        canvas.key, canvas.name = "workflows/别的.json", "别的"
        approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "failed" and "开着的已经不是" in approved["error"]
    assert canvas.ops() == ["readGraph", "readGraph"], "核对之后没导出、没跑"


def test_试跑_重读之后导出之前换了标签页_导出的不是卡上那张_不跑(connected) -> None:
    """桥的导出带回来的是**它导的是哪一张**(`at.key`)。重读和导出之间用户在标签栏里换了一张,导出来的是那一张的图 ——
    照着它提交,跑的就是用户没看过的那张,而卡上写的是另一张。"""
    client, comfy, instance_id, workspace = connected
    canvas = Canvas(_simple(), key="workflows/portrait.json", name="portrait")
    with Executor(canvas):
        out = _tool(client, "comfy_canvas_run", workspace, instance_id=instance_id)["result"]
        canvas.export_key = "workflows/别的.json"
        approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "failed" and "开着的已经不是" in approved["error"]
    assert canvas.ops() == ["readGraph", "readGraph", "runControls", "export"], "导出之后才发现:没建任务"
    assert comfy.posted("/prompt") == [], "一张都没提交"


def test_装节点包_重启没成_说清包装上了_重启失败(connected, monkeypatch) -> None:
    """Manager 不让重启(403):包**已经装上了**,卡上说成一句「失败」就丢了这件事。原话带着,并且说清没有重启。"""
    client, comfy, instance_id, workspace = connected
    comfy.state.manager = "V4.2.1"
    comfy.state.manager_reboot_allowed = False
    monkeypatch.setattr(workbench_agent, "node_pack_info", lambda *args, **kwargs: _pack_info())
    with Executor(Canvas(_simple())):
        out = _tool(client, "comfy_node_pack_install", workspace, pack_id="rgthree-comfy",
                    instance_id=instance_id)["result"]
    approved = client.post(f"/api/confirmations/{out['confirmation_id']}/approve").json()
    assert approved["status"] == "failed", approved
    assert "rgthree-comfy" in approved["error"] and "装上了" in approved["error"]
    assert "没能重启" in approved["error"] and "security_level" in approved["error"], "插件的原话说出来"
    with SessionLocal() as db:
        [job] = db.query(Job).filter(Job.kind == "node_install").all()
        assert job.status == "succeeded", "包确实装上了:失败的是重启"
    assert "/v2/manager/reboot" in [one[1] for one in comfy.state.calls]
