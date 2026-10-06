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

from tests.fake_comfyui import FakeComfyUI, subgraph_promoting

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service", "shared_models", "workflows",
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
    assert [(one["title"], one["media"]) for one in portrait["inputs"]] == [("加载图像 #10", "image")], "不是类名"
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


def test_节点包按_Manager_的_nodename_pattern_认_不锚在开头(library, comfy) -> None:
    """Manager 的映射里 rgthree 只列了 Rgthree* 这类内部名,它的显示名节点(「Any Switch (rgthree)」)靠
    `nodename_pattern: " \\(rgthree\\)$"` 认 —— Manager 自己用 re.search。维护者的 DaSiWa WAN 2.2 缺的正是这几个,
    此前一个「装上」都不给。"""
    comfy.state.manager_mappings["rgthree-comfy"] = [
        ["RgthreeAnySwitch", "RgthreePowerLoraLoader"],
        {"title_aux": "rgthree's ComfyUI Nodes", "nodename_pattern": " \\(rgthree\\)$"}]
    comfy.state.manager_installed = {}
    comfy.state.workflows["switch.json"] = {
        "nodes": [{"id": 1, "type": "Any Switch (rgthree)", "pos": [0, 0], "size": [200, 80]},
                  {"id": 2, "type": "Power Lora Loader (rgthree)", "pos": [0, 100], "size": [200, 80]}],
        "links": [],
    }
    switch = {one["path"]: one for one in _listed(library, comfy)["workflows"]}["switch.json"]
    rgthree = {"id": "rgthree-comfy", "title": "rgthree's ComfyUI Nodes", "installed": False}
    assert switch["missing_nodes"] == [
        {"type": "Any Switch (rgthree)", "count": 1, "packs": [rgthree]},
        {"type": "Power Lora Loader (rgthree)", "count": 1, "packs": [rgthree]},
    ]


def test_子图里过期的下载声明_不算用到_也不算缺(library, comfy) -> None:
    """子图节点上提升出来的那一格选了别的文件(维护者的 video_minimax_h3_t2v):子图里加载节点带着的模板下载声明过期了,
    「用到的模型」「缺的模型」里都不该有它 —— 此前两边都列着,还带一个能点的「下载」(十几 GB 的 UNET)。"""
    comfy.state.workflows["promoted.json"] = subgraph_promoting("sd_xl_base.safetensors")
    row = {one["path"]: one for one in _listed(library, comfy)["workflows"]}["promoted.json"]
    assert row["models"] == [{"folder": "checkpoints", "name": "sd_xl_base.safetensors", "present": True}]
    assert row["missing_models"] == []


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


def test_列出时带上编辑器的地址_就是这台服务器(library, comfy) -> None:
    out = _listed(library, comfy)
    assert out["editor"] == {"kind": "comfyui", "url": comfy.url.rstrip("/")}


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


# --- 文件夹 ------------------------------------------------------------------------------
#
# 文件夹就是 workflows/ 里的子目录(和 ComfyUI 自己的侧栏同一份)。ComfyUI 没有建目录、删目录的接口:新建是写一个隐藏的
# 占位文件;删除只删空的、挪进回收目录。改动前都现查那台机器,不照界面手里那份旧列表。


def _folders(library, comfy) -> list[str]:
    return _listed(library, comfy)["folders"]


def test_列出文件夹_有文件的各级父目录_加上空的_隐藏的不算(library, comfy) -> None:
    comfy.state.workflows["deep/a/b.json"] = {"nodes": [], "links": []}
    comfy.state.dirs |= {"workflows/空的/更深", "workflows/.hidden", "workflows/.hidden/inner"}
    assert _folders(library, comfy) == ["deep", "deep/a", "sub", "video", "空的", "空的/更深"], \
        "zip 所在的根目录不算文件夹;空目录也列;隐藏的不列"
    comfy.state.userdata_v2 = False  # 老版本 ComfyUI:只列得出有文件的那几个
    assert _folders(library, comfy) == ["deep", "deep/a", "sub", "video"]


def test_新建文件夹_写一个隐藏的占位文件_列得出来_工作流和别的文件里都没有它(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    assert module.make_folder({"path": "人像/草稿"}, client, "zh") == {"path": "人像/草稿"}
    writes = [call for call in comfy.state.calls if call[0] == "WRITE"]
    assert [call[1] for call in writes] == ["workflows/人像/草稿/.mosael-folder"]
    assert writes[0][2]["overwrite"] is False
    listed = _listed(library, comfy)
    assert {"人像", "人像/草稿"} <= set(listed["folders"])
    assert not [one for one in listed["workflows"] + listed["others"] if ".mosael-folder" in one["path"]]


def test_新建文件夹_已经有了回建议名_不分大小写(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    assert module.make_folder({"path": "video"}, client, "zh") == {"conflict": True, "suggestion": "video (1)"}
    assert module.make_folder({"path": "VIDEO"}, client, "zh") == {"conflict": True, "suggestion": "VIDEO (1)"}, \
        "那台机器可能是 Windows:VIDEO 和 video 是同一个"
    assert not [call for call in comfy.state.calls if call[0] == "WRITE"]


@pytest.mark.parametrize("bad", ["", "../x", "a//b", ".hidden", "a/.b", "a:b", "x.json", "a /b"])
def test_文件夹名插件这边再查一遍(library, comfy, bad: str) -> None:
    module, Comfy = library
    from lines import ComfyError

    with pytest.raises(ComfyError):
        module.make_folder({"path": bad}, Comfy(comfy.url), "zh")
    with pytest.raises(ComfyError):
        module.rename_folder({"path": "video", "new_path": bad}, Comfy(comfy.url), "zh")
    assert not [call for call in comfy.state.calls if call[0] in ("MOVE", "WRITE")]


def test_移动到文件夹就是改名_目标文件夹没有会建出来_这张已经不在了说清楚(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    from lines import ComfyError

    assert module.rename_workflow({"path": "portrait.json", "new_path": "人像/portrait.json"}, client, "zh") == \
        {"path": "人像/portrait.json"}
    assert "人像" in _folders(library, comfy)
    with pytest.raises(ComfyError, match="已经没有工作流「portrait.json」"):
        module.rename_workflow({"path": "portrait.json", "new_path": "别处/portrait.json"}, client, "zh")
    with pytest.raises(ComfyError, match="已经没有"):
        module.trash_workflow({"path": "portrait.json"}, client, "zh")


def test_文件夹改名_整个目录一次挪过去_里面的跟着走(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    comfy.state.dirs.add("workflows/video/空的子文件夹")
    assert module.rename_folder({"path": "video", "new_path": "片子/视频"}, client, "zh") == {"path": "片子/视频"}
    assert "片子/视频/wan.json" in comfy.state.workflows and "video/wan.json" not in comfy.state.workflows
    moves = [call for call in comfy.state.calls if call[0] == "MOVE"]
    assert [(call[1], call[2]["dest"], call[2]["overwrite"]) for call in moves] == [
        ("workflows/video", "workflows/片子/视频", False)], "一个目录一次挪,不一张张挪"
    folders = _folders(library, comfy)
    assert {"片子", "片子/视频", "片子/视频/空的子文件夹"} <= set(folders) and "video" not in folders


def test_文件夹改名_不覆盖_不能挪进自己里面_已经不在了说清楚(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    from lines import ComfyError

    assert module.rename_folder({"path": "video", "new_path": "Sub"}, client, "zh") == \
        {"conflict": True, "suggestion": "Sub (1)"}, "目标已经有了(不分大小写):给建议名,不合并进去"
    with pytest.raises(ComfyError, match="自己里面"):
        module.rename_folder({"path": "video", "new_path": "video/inner"}, client, "zh")
    with pytest.raises(ComfyError, match="已经没有文件夹「gone」"):
        module.rename_folder({"path": "gone", "new_path": "here"}, client, "zh")
    assert not [call for call in comfy.state.calls if call[0] == "MOVE"]


def test_文件夹只改大小写_不分大小写的磁盘上先挪到临时名字再挪过去(library, comfy) -> None:
    module, Comfy = library
    comfy.state.case_insensitive = True
    assert module.rename_folder({"path": "video", "new_path": "Video"}, Comfy(comfy.url), "zh") == {"path": "Video"}
    assert "Video/wan.json" in comfy.state.workflows and "video/wan.json" not in comfy.state.workflows
    folders = _folders(library, comfy)
    assert "Video" in folders and "video" not in folders
    assert not [one for one in comfy.state.all_dirs() if "renaming" in one], "临时名字不留下"


def test_删除文件夹_只删空的_挪进回收目录_回收站里不多出一条(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    module.make_folder({"path": "草稿/更深"}, client, "zh")
    trashed = module.trash_folder({"path": "草稿"}, client, "zh")
    assert re.fullmatch(r"\.mosael-trash/workflows/\d{8}-\d{6}(-\d+)?/草稿", trashed["path"]), "空的子文件夹一起挪走"
    listed = _listed(library, comfy)
    assert not {"草稿", "草稿/更深"} & set(listed["folders"])
    assert [one["path"] for one in listed["trash"]] == [".mosael-trash/workflows/20261005-101500/old/one.json"], \
        "占位文件不是一张工作流,回收站里不列"
    assert not [call for call in comfy.state.calls if call[0] == "DELETE"], "从不硬删"


def test_删除文件夹_里面还有文件就不动_现查那台机器不照旧列表(library, comfy) -> None:
    module, Comfy = library
    client = Comfy(comfy.url)
    from lines import ComfyError

    assert module.trash_folder({"path": "video"}, client, "zh") == {"not_empty": True, "count": 1}
    module.make_folder({"path": "只有压缩包"}, client, "zh")
    comfy.state.workflows["只有压缩包/pack.zip"] = {"zip": True}  # 不是工作流,也是那台机器上的一个文件
    assert module.trash_folder({"path": "只有压缩包"}, client, "zh") == {"not_empty": True, "count": 1}
    module.make_folder({"path": "刚建的"}, client, "zh")
    comfy.state.workflows["刚建的/在 ComfyUI 里刚存的.json"] = {"nodes": [], "links": []}  # 界面那份列表之后存进去的
    assert module.trash_folder({"path": "刚建的"}, client, "zh") == {"not_empty": True, "count": 1}
    assert not [call for call in comfy.state.calls if call[0] == "MOVE"]
    with pytest.raises(ComfyError, match="已经没有文件夹"):
        module.trash_folder({"path": "不存在"}, client, "zh")
