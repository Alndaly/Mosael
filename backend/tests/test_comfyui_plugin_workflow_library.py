"""ComfyUI 插件的工作流库(ADR 0035):这台 ComfyUI 上存着的工作流 —— 列出、取原文、复制、改名、挪进 / 挪出回收目录。

对着一台假的 ComfyUI(tests/fake_comfyui.py,userdata 的写 / 移动 / 删除照 ComfyUI 源码的语义)直接调插件的函数:

- 列出:每张一个图摘要(节点位置 / 大小 / 种类 / 旁路、连线、分组;API 格式没有位置,按依赖自动排)、识别出的输入 /
  参数 / 输出、用到的模型在不在、缺的节点(只在前端的虚拟节点、子图不算缺)和它们出自哪个节点包、声明了地址又缺的模型;
  不是工作流的文件、回收目录里的另列;
- 复制给副本换一个新的图 id;复制、改名、恢复一律 `overwrite=false`,撞名回 `conflict` 和建议名;删除是挪进
  `.mosael-trash/workflows/<时刻>/<原路径>`,**从不调 DELETE**。
"""

from __future__ import annotations

import calendar
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fake_comfyui import FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "workflows",
            "tooling", "library", "sources", "install", "model_files", "families", "workflow_library")

#: 一张带布局的界面格式工作流:文生图 + 一个只在前端的虚拟节点、一个没装的节点、一个子图实例、一个分组。
LAID_OUT: dict[str, Any] = {
    "id": "aaaaaaaa-1111-2222-3333-444444444444",
    "nodes": [
        {"id": 4, "type": "CheckpointLoaderSimple", "pos": [0, 0], "size": [315, 98], "mode": 0,
         "widgets_values": ["sd_xl_base.safetensors"], "inputs": [{"name": "ckpt_name", "widget": {"name": "ckpt_name"}}],
         "properties": {"models": [{"name": "sd_xl_base.safetensors", "directory": "checkpoints",
                                    "url": "https://huggingface.co/x/sdxl/resolve/main/sd_xl_base.safetensors"}]}},
        {"id": 10, "type": "LoraLoader", "pos": [400, 0], "size": [315, 126], "mode": 4,
         "widgets_values": ["gone.safetensors", 1.0, 1.0],
         "inputs": [{"name": "model", "link": 1}, {"name": "clip", "link": 2},
                    {"name": "lora_name", "widget": {"name": "lora_name"}}],
         "properties": {"models": [{"name": "gone.safetensors", "directory": "loras",
                                    "url": "https://huggingface.co/x/y/resolve/main/gone.safetensors"}]}},
        {"id": 6, "type": "CLIPTextEncode", "pos": {"0": 400, "1": 200}, "size": {"0": 400, "1": 200},
         "widgets_values": ["a cat"], "inputs": [{"name": "clip", "link": 3}, {"name": "text", "widget": {"name": "text"}}]},
        {"id": 3, "type": "KSampler", "pos": [900, 0], "size": [315, 262], "title": "采样",
         "widgets_values": [42, "randomize", 20, 7.0, "euler", "normal", 1.0], "inputs": []},
        {"id": 9, "type": "SaveImage", "pos": [1300, 0], "size": [315, 270], "widgets_values": ["out"], "inputs": []},
        {"id": 20, "type": "Note", "pos": [0, 400], "size": [300, 100], "widgets_values": ["说明"]},
        {"id": 21, "type": "SetNode", "pos": [0, 600], "size": [200, 60]},
        {"id": 22, "type": "Fast Groups Bypasser (rgthree)", "pos": [0, 700], "size": [200, 60]},
        {"id": 26, "type": "Mute / Bypass Relay (rgthree)", "pos": [200, 700], "size": [200, 60]},
        {"id": 23, "type": "CR Prompt Text", "pos": [0, 800], "size": [300, 100]},
        {"id": 24, "type": "CR Prompt Text", "pos": [0, 950], "size": [300, 100]},
        {"id": 25, "type": "9b2c1d4e-0000-4000-8000-00000000abcd", "pos": [1300, 400], "size": [300, 100]},
    ],
    "links": [[1, 4, 0, 10, 0, "MODEL"], [2, 4, 1, 10, 1, "CLIP"], [3, 4, 1, 6, 0, "CLIP"], [9, 99, 0, 3, 0, "MODEL"]],
    "groups": [{"title": "出图", "bounding": [-20, -40, 1700, 400], "color": "#3f789e"}],
    "definitions": {"subgraphs": [{"id": "9b2c1d4e-0000-4000-8000-00000000abcd", "name": "高清修复", "nodes": []}]},
}


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        server.state.workflows["sub/laid out.json"] = json.loads(json.dumps(LAID_OUT))
        server.state.workflows["pack.zip"] = {"zip": True}
        server.state.userdata[".mosael-trash/workflows/20261005-101500/old/one.json"] = {"nodes": [], "links": []}
        server.state.manager = "V4.2.1"
        server.state.manager_mappings = {
            "ComfyUI_Comfyroll_CustomNodes": [["CR Prompt Text", "CR Text"], {"title_aux": "Comfyroll Studio"}],
            "rgthree-comfy": [["Seed (rgthree)"], {"title_aux": "rgthree's ComfyUI Nodes"}],
        }
        server.state.manager_installed = {"rgthree-comfy": {"ver": "1.0.0", "cnr_id": "rgthree-comfy", "enabled": True}}
        yield server


@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path / "data"))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import workflow_library
        from comfy_http import Comfy

        yield workflow_library, Comfy
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _listed(library, comfy) -> dict[str, Any]:
    module, Comfy = library
    return module.workflows({"op": "workflows"}, Comfy(comfy.url), "zh")


def test_列出_每张一个图摘要_带布局的照原样_API格式按依赖自动排(library, comfy) -> None:
    out = _listed(library, comfy)
    by_path = {one["path"]: one for one in out["workflows"]}
    assert set(by_path) == {"portrait.json", "video/wan.json", "sub/laid out.json"}, "压缩包不是工作流"
    laid = by_path["sub/laid out.json"]
    graph = laid["graph"]
    assert graph["auto_layout"] is False
    assert len(graph["nodes"]) == laid["node_count"] == 12
    first = graph["nodes"][0]
    assert (first["x"], first["y"], first["w"], first["h"]) == (0, 0, 315, 98)
    assert graph["nodes"][2]["x"] == 400 and graph["nodes"][2]["w"] == 400, "老格式的 {\"0\": x, \"1\": y} 也认"
    roles = [node["role"] for node in graph["nodes"]]
    assert roles[:5] == ["model", "model", "text", "sampler", "output"]
    assert roles[5] == "note" and roles[9] == "missing"
    assert graph["nodes"][1]["muted"] is True, "旁路(mode 4)的节点画成淡的"
    assert graph["nodes"][3]["title"] == "采样"
    assert graph["links"] == [[0, 1], [0, 1], [0, 2]], "指着不存在节点的连线丢掉"
    assert graph["groups"] == [{"x": -20, "y": -40, "w": 1700, "h": 400, "title": "出图", "color": "#3f789e"}]
    wan = by_path["video/wan.json"]["graph"]
    assert wan["auto_layout"] is True, "API 格式没有位置:自动排"
    xs = {node["title"]: node["x"] for node in wan["nodes"]}
    assert xs["CheckpointLoaderSimple"] < xs["KSampler"] < xs["VHS_VideoCombine"], "按依赖从左往右排"


def test_识别出的输入参数输出_和跑它的那个生成模型同一份(library, comfy) -> None:
    portrait = {one["path"]: one for one in _listed(library, comfy)["workflows"]}["portrait.json"]
    assert portrait["kind"] == "image" and portrait["problem"] == ""
    assert [(one["title"], one["media"]) for one in portrait["inputs"]] == [("LoadImage", "image")]
    assert any(one["key"].endswith("steps") for one in portrait["parameters"])
    assert [(one["node"], one["media"]) for one in portrait["outputs"]] == [("9", "image")]


def test_用到的模型在不在_缺的节点排除虚拟节点和子图_带节点包(library, comfy) -> None:
    laid = {one["path"]: one for one in _listed(library, comfy)["workflows"]}["sub/laid out.json"]
    assert {(one["folder"], one["name"], one["present"]) for one in laid["models"]} == {
        ("checkpoints", "sd_xl_base.safetensors", True), ("loras", "gone.safetensors", False)}
    assert laid["missing_models"] == [{"folder": "loras", "name": "gone.safetensors",
                                       "url": "https://huggingface.co/x/y/resolve/main/gone.safetensors"}], \
        "在的不算缺;缺的带着工作流里声明的下载地址"
    assert laid["missing_nodes"] == [{"type": "CR Prompt Text", "count": 2, "packs": [
        {"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll Studio", "installed": False}]}], \
        "Note、SetNode、rgthree 的 Fast Groups Bypasser 只在前端;子图实例不是节点类型"
    assert "CR Prompt Text" in laid["problem"], "缺节点转不过来:原因照说"


def test_新版的下拉写成_COMBO_加options_也认得出模型在不在(library, comfy) -> None:
    """ComfyUI 0.38 里用新写法定义的节点(放大模型加载器这类),object_info 里的下拉是 ["COMBO", {"options": [...]}]。"""
    comfy.state.object_info["UpscaleModelLoader"]["input"]["required"]["model_name"] = [
        "COMBO", {"multiselect": False, "options": ["4x-UltraSharp.pth"]}]
    comfy.state.workflows["up.json"] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "up"}},
    }
    up = {one["path"]: one for one in _listed(library, comfy)["workflows"]}["up.json"]
    assert up["models"] == [{"folder": "upscale_models", "name": "4x-UltraSharp.pth", "present": True}]
    assert up["missing_models"] == []


def test_不是工作流的文件_回收目录里的_另列(library, comfy) -> None:
    out = _listed(library, comfy)
    assert [one["path"] for one in out["others"]] == ["pack.zip"]
    assert "压缩包" in out["others"][0]["reason"]
    assert out["trash"] == [{"path": ".mosael-trash/workflows/20261005-101500/old/one.json",
                             "deleted_at": float(calendar.timegm((2026, 10, 5, 10, 15, 0)))}], "删除时刻写在目录名里(UTC)"
    assert out["manager"] == {"version": "V4.2.1"}


def test_取原文(library, comfy) -> None:
    module, Comfy = library
    out = module.workflow({"op": "workflow", "path": "sub/laid out.json"}, Comfy(comfy.url), "zh")
    assert out["content"]["id"] == LAID_OUT["id"]


def test_复制_副本换一个新的图id_不覆盖_撞名给建议名(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    done = module.copy_workflow({"path": "sub/laid out.json", "new_path": "sub/laid out (1).json"}, client, "zh")
    assert done == {"path": "sub/laid out (1).json"}
    copy = comfy.state.workflows["sub/laid out (1).json"]
    assert copy["id"] != LAID_OUT["id"] and re.fullmatch(r"[0-9a-f-]{36}", copy["id"]), "两张同 id 的图,工具名会撞"
    assert copy["nodes"] == LAID_OUT["nodes"]
    clash = module.copy_workflow({"path": "sub/laid out.json", "new_path": "portrait.json"}, client, "zh")
    assert clash == {"conflict": True, "suggestion": "portrait (1).json"}
    assert comfy.state.workflows["portrait.json"]["id"] != copy["id"], "撞名不覆盖"
    writes = [call for call in comfy.state.calls if call[0] == "WRITE"]
    assert writes and all(call[2]["overwrite"] is False for call in writes)


def test_改名_挪目录_不覆盖(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    assert module.rename_workflow({"path": "portrait.json", "new_path": "人像/人像.json"}, client, "zh") == \
        {"path": "人像/人像.json"}
    assert "portrait.json" not in comfy.state.workflows and "人像/人像.json" in comfy.state.workflows
    clash = module.rename_workflow({"path": "人像/人像.json", "new_path": "video/wan.json"}, client, "zh")
    assert clash == {"conflict": True, "suggestion": "video/wan (1).json"}
    assert all(call[2]["overwrite"] is False for call in comfy.state.calls if call[0] == "MOVE")


def test_删除是挪进回收目录_能恢复_从不硬删(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    trashed = module.trash_workflow({"path": "video/wan.json"}, client, "zh")
    assert re.fullmatch(r"\.mosael-trash/workflows/\d{8}-\d{6}(-\d+)?/video/wan\.json", trashed["path"])
    assert "video/wan.json" not in comfy.state.workflows
    listed = _listed(library, comfy)
    assert "video/wan.json" not in {one["path"] for one in listed["workflows"]}
    assert trashed["path"] in {one["path"] for one in listed["trash"]}
    comfy.state.workflows["video/wan.json"] = {"nodes": [], "links": []}  # 原处又有了一张同名的
    clash = module.restore_workflow({"path": trashed["path"], "new_path": "video/wan.json"}, client, "zh")
    assert clash == {"conflict": True, "suggestion": "video/wan (1).json"}
    back = module.restore_workflow({"path": trashed["path"], "new_path": "video/wan (1).json"}, client, "zh")
    assert back == {"path": "video/wan (1).json"}
    assert not [call for call in comfy.state.calls if call[0] == "DELETE"], "ComfyUI 的 DELETE 是硬删,工作流库从不调"


@pytest.mark.parametrize("bad", ["../x.json", "a\\b.json", ".hidden/x.json", "x.txt"])
def test_路径插件这边再查一遍(library, comfy, bad: str) -> None:
    module, Comfy = library
    from lines import ComfyError

    with pytest.raises(ComfyError):
        module.rename_workflow({"path": "portrait.json", "new_path": bad}, Comfy(comfy.url), "zh")
    assert not [call for call in comfy.state.calls if call[0] in ("MOVE", "WRITE")]
