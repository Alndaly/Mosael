"""工作台(ADR 0038 §3、§6)插件这一侧:画布是 ComfyUI 自己的,这几个 op 按插件对工作流的理解回答,不碰那台机器上的文件。

- `app` 带着 `content`(画布上现在这张,含没存的改动):和读文件同样的回答,没有路径和改动时间;
- `app_marks`:应用表单写进画布要改成的那几处标记 —— 和 `annotate` 写文件同一个函数(app_form.apply),只交回标记;
- `node_folders`:选中节点上选模型文件的那一格是哪个模型目录(模型库面板据此筛),和生成表单的 `x-model-folder` 同一张对照;
- `generate` 带着 `graph`:跑画布上的图,不读文件、不填参数;`client_id` 用前端的,`extra_pnginfo.workflow` 带上界面格式;
  只按历史轮询(不开 WebSocket 抢前端那条连接);交回这一种的全部产出、各带来自哪个节点。

都对着 tests/fake_comfyui.py,经插件进程跑。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import OBJECT_INFO, FakeComfyUI, multi_reference_ui

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"

APP: dict[str, Any] = {
    "id": "app",
    "title": "换装",
    "description": "",
    "items": [{"node": "10", "input": "image", "label": "人物照片"}, {"node": "6", "input": "text", "main": True}],
}


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path / "data"))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    with FakeComfyUI() as server:
        server.state.object_info = json.loads(json.dumps(OBJECT_INFO))
        server.state.workflows = {"multi.json": multi_reference_ui()}
        yield server


def _host(op: str, url: str, **payload: Any) -> dict[str, Any]:
    return runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": op, **payload}, {"SERVER_URL": url},
                                timeout=60).output


def _writes(comfy) -> list[Any]:
    return [call for call in comfy.state.calls if call[0] == "WRITE"]


def test_画布上的图_能填的项和读文件一样_没有路径和改动时间(comfy) -> None:
    live = multi_reference_ui()
    live["nodes"] = [node for node in live["nodes"] if str(node["id"]) != "14"]  # 画布上删了一个读图节点,还没存
    out = _host("app", comfy.url, content=live)
    saved = _host("app", comfy.url, path="multi.json")
    assert out["path"] == "" and out["modified"] is None and out["editable"] is True
    assert "14.image" in [one["key"] for one in saved["items"]]
    assert "14.image" not in [one["key"] for one in out["items"]], "读的是画布上现在这张,不是文件"
    assert [one["node"] for one in out["outputs"]] == [one["node"] for one in saved["outputs"]]
    assert not _writes(comfy)


def test_画布上的图不是界面格式就说清楚(comfy) -> None:
    with pytest.raises(runtime.PluginRuntimeError, match="不是界面格式"):
        _host("app", comfy.url, content={"3": {"class_type": "KSampler", "inputs": {}}})


def test_写进画布的标记_和annotate写文件的一模一样_只交回标记(comfy) -> None:
    live = multi_reference_ui()
    marks = _host("app_marks", comfy.url, content=live, forms=[APP], results=["17"])
    assert not _writes(comfy), "画布开着时不写文件:存盘是 ComfyUI 自己的保存"
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], forms=[APP], results=["17"])
    stored = comfy.state.workflows["multi.json"]
    expected = {str(node["id"]): node["properties"]["mosael"] for node in stored["nodes"]
                if "mosael" in (node.get("properties") or {})}
    assert marks["nodes"] == expected
    assert marks["extra"] == stored["extra"]["mosael"]
    assert set(marks["nodes"]) == {"10", "6", "17"}
    assert marks["nodes"]["17"] == {"result": True}


def test_写进画布的标记_一张表单都不要只留结果_指着不存在的节点就拒(comfy) -> None:
    live = multi_reference_ui()
    only_result = _host("app_marks", comfy.url, content=live, forms=[], results=["9"])
    assert only_result["nodes"] == {"9": {"result": True}}
    assert only_result["extra"] == {"version": 2, "forms": []}
    cleared = _host("app_marks", comfy.url, content=live, forms=[], results=[])
    assert (cleared["nodes"], cleared["extra"]) == ({}, None)
    with pytest.raises(runtime.PluginRuntimeError, match="#999"):
        _host("app_marks", comfy.url, content=live, forms=[], results=["999"])


def test_写进画布的新表单_插件起的id在交回的标记里(comfy) -> None:
    live = multi_reference_ui()
    marks = _host("app_marks", comfy.url, content=live, forms=[APP, {"title": "精调", "items": [
        {"node": "3", "input": "steps"}]}], results=[])
    ids = [one["id"] for one in marks["extra"]["forms"]]
    assert ids[0] == "app" and len(ids[1]) == 6, "界面写完照这份认出新表单的 id,下次再写带着它,不会又起一个"
    assert marks["nodes"]["3"] == {"forms": {ids[1]: {"steps": {"order": 0}}}}


def test_选中的节点那一格是哪个模型目录(comfy) -> None:
    out = _host("node_folders", comfy.url, nodes=[
        {"class_type": "CheckpointLoaderSimple", "input": "ckpt_name"},
        {"class_type": "LoraLoader", "input": "lora_name"},
        {"class_type": "UpscaleModelLoader", "input": "model_name"},
        {"class_type": "KSampler", "input": "steps"},
    ])
    assert out["folders"] == ["checkpoints", "loras", "upscale_models", ""]
    with pytest.raises(runtime.PluginRuntimeError, match="形状不对"):
        _host("node_folders", comfy.url, nodes=[{"class_type": "X", "input": "y"}] * 65)


def _canvas_prompt() -> dict[str, Any]:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 640, "height": 480, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "画布上改过、还没存的那句", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 7, "steps": 12, "cfg": 5, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": 1, "model": ["4", 0],
                                                    "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "a", "images": ["8", 0]}},
        "17": {"class_type": "SaveImage", "inputs": {"filename_prefix": "b", "images": ["8", 0]}},
    }


def _generate(comfy, tmp_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    scratch = tmp_path / "out"
    scratch.mkdir(exist_ok=True)
    tasks: list[dict[str, Any]] = []
    hooks = runtime.StreamHooks(on_progress=lambda *_: None, on_task=tasks.append, is_cancelled=lambda: False)
    result = runtime.stream_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "generate", **request},
                                 {"SERVER_URL": comfy.url}, hooks=hooks, scratch_dir=scratch, timeout=60).output
    return {"result": result, "tasks": tasks}


def test_跑画布上的图_不读文件不填参数_用前端的clientId_带上界面格式_只轮询(comfy, tmp_path: Path) -> None:
    comfy.state.outputs = {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
                           "17": {"images": [{"filename": "b.png", "subfolder": "", "type": "output"}]}}
    workflow = multi_reference_ui()
    prompt = _canvas_prompt()
    out = _generate(comfy, tmp_path, {
        "kind": "image", "model": "multi.json", "prompt": "", "negative_prompt": "", "parameters": {}, "inputs": [],
        "resume": None, "graph": {"prompt": prompt, "workflow": workflow, "client_id": "4f1c0e2a9b7d4c51a3e8"},
    })
    body = next(call[2] for call in comfy.state.calls if call[1] == "/prompt")
    assert body["prompt"] == prompt, "画布上的图原样提交:不从文件读、不填参数"
    assert body["client_id"] == "4f1c0e2a9b7d4c51a3e8", "用前端的 clientId:画布上照常亮起正在跑的节点"
    assert body["extra_data"] == {"extra_pnginfo": {"workflow": workflow}}, "产出拖回 ComfyUI 有布局"
    assert not [call for call in comfy.state.calls if call[1] == "/ws"], "不开 WebSocket 去抢前端那条连接"
    assert not [call for call in comfy.state.calls if call[1].startswith("/api/userdata/")], "不读工作流文件"
    assert out["tasks"] == [{"prompt_id": "p1", "client_id": "4f1c0e2a9b7d4c51a3e8"}]
    assert sorted(one["parameters"]["source_node"] for one in out["result"]["outputs"]) == ["17", "9"], \
        "这一种的全部产出,各带来自哪个节点 —— 工作台按节点分组摆"


def test_跑画布上的图_clientId认不出就用自己的_图形状不对什么都不提交(comfy, tmp_path: Path) -> None:
    comfy.state.outputs = {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}
    _generate(comfy, tmp_path, {"kind": "image", "model": "", "prompt": "", "parameters": {}, "inputs": [], "resume": None,
                                "graph": {"prompt": _canvas_prompt(), "workflow": "不是图", "client_id": "a b;c"}})
    body = next(call[2] for call in comfy.state.calls if call[1] == "/prompt")
    assert body["client_id"] != "a b;c" and len(body["client_id"]) == 32
    assert "extra_data" not in body
    calls = len(comfy.state.calls)
    with pytest.raises(runtime.PluginRuntimeError, match="形状不对"):
        _generate(comfy, tmp_path, {"kind": "image", "model": "", "prompt": "", "parameters": {}, "inputs": [],
                                    "resume": None, "graph": {"prompt": {"3": "KSampler"}}})
    assert not [call for call in comfy.state.calls[calls:] if call[1] == "/prompt"]


def test_跑画布上的图_缺节点照样先查一遍_不提交(comfy, tmp_path: Path) -> None:
    prompt = copy.deepcopy(_canvas_prompt())
    prompt["30"] = {"class_type": "NotInstalledNode", "inputs": {}}
    with pytest.raises(runtime.PluginRuntimeError, match="NotInstalledNode"):
        _generate(comfy, tmp_path, {"kind": "image", "model": "", "prompt": "", "parameters": {}, "inputs": [],
                                    "resume": None, "graph": {"prompt": prompt, "client_id": "abc"}})
    assert not [call for call in comfy.state.calls if call[1] == "/prompt"]
