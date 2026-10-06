"""ComfyUI 插件的工作流导入与补齐(ADR 0035 §5):认出要导入的那份东西、换成界面格式、预览;存进 workflows/ 不覆盖;
经 ComfyUI-Manager 装缺的节点包、重启 ComfyUI。

对着一台假的 ComfyUI(tests/fake_comfyui.py:userdata 的写照源码语义,Manager 的排队 / 历史 / 重启照 V4.2.1 的接口)
直接调插件的函数 —— **从不在真机器上装节点**:

- 认得出:界面格式 / API 格式的 JSON 原文;PNG(tEXt / iTXt)、WebP(EXIF 的 Make / Model)里嵌的工作流,界面格式优先;
  压缩包里的第一张;链接只去取认得的站(HuggingFace、Civitai、ModelScope、这台 ComfyUI 自己),网页不是文件就说清楚;
- API 格式没有布局:按 object_info 把值排回 `widgets_values`、按连线重建 `links`、按依赖分层排位置,转回 API 和原来一样;
- 预览带着图摘要、识别出的参数、缺的节点(和节点包)和缺的模型;一张新的图 id,建议一个不撞名的路径;
- 存进去一律 `overwrite=false`,撞名回建议名;
- 装节点包:经 Manager 排队(registry 里的包按 `latest`,只在 git 上的按 `unknown`)、等历史出结果、说要重启;被安全策略
  拒绝时说人话和下一步;重启经 Manager,等它停下再起来。
"""

from __future__ import annotations

import base64
import io
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pytest

from tests.fake_comfyui import MANAGER_POLICY_MESSAGE, OBJECT_INFO, FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service", "shared_models", "workflows",
            "tooling", "library", "sources", "install", "model_files", "families", "workflow_library", "workflow_import")

#: 文生图的 API 格式(ComfyUI「导出 (API)」那种):没有位置,值和连线都在 inputs 里。
TXT2IMG_API: dict[str, Any] = {
    "3": {"class_type": "KSampler", "_meta": {"title": "采样"}, "inputs": {
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
        "seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
    "4": {"class_type": "CheckpointLoaderSimple", "_meta": {"title": "Load Checkpoint"},
          "inputs": {"ckpt_name": "sd_xl_base.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "_meta": {"title": "Empty Latent Image"},
          "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "_meta": {"title": "正向"}, "inputs": {"text": "一只猫", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "_meta": {"title": "反向"}, "inputs": {"text": "", "clip": ["4", 1]}},
    "8": {"class_type": "VAEDecode", "_meta": {"title": "VAE Decode"}, "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "_meta": {"title": "保存"}, "inputs": {"images": ["8", 0], "filename_prefix": "mosael"}},
}

#: 节点的输出口(真的 object_info 里有;假 ComfyUI 那份子集里没写)。
OUTPUTS = {
    "KSampler": (["LATENT"], ["LATENT"]),
    "CheckpointLoaderSimple": (["MODEL", "CLIP", "VAE"], ["MODEL", "CLIP", "VAE"]),
    "EmptyLatentImage": (["LATENT"], ["LATENT"]),
    "CLIPTextEncode": (["CONDITIONING"], ["CONDITIONING"]),
    "VAEDecode": (["IMAGE"], ["IMAGE"]),
    "SaveImage": ([], []),
    "LoadImage": (["IMAGE", "MASK"], ["IMAGE", "MASK"]),
}

#: 一张界面格式的工作流:一个没装的节点、一个声明了下载地址又缺的模型。
UI_FLOW: dict[str, Any] = {
    "id": "6f1b8c5e-2f0e-4b8a-9d55-1a2b3c4d5e6f", "revision": 0, "last_node_id": 3, "last_link_id": 1,
    "nodes": [
        {"id": 1, "type": "CheckpointLoaderSimple", "pos": [0, 0], "size": [300, 100], "mode": 0,
         "outputs": [{"name": "MODEL", "type": "MODEL", "links": [1]}], "widgets_values": ["sd_xl_base.safetensors"]},
        {"id": 2, "type": "CR Prompt Text", "pos": [400, 0], "size": [300, 120], "mode": 0, "widgets_values": ["猫"]},
        {"id": 3, "type": "LoraLoader", "pos": [400, 200], "size": [300, 120], "mode": 0,
         "inputs": [{"name": "model", "type": "MODEL", "link": 1}],
         "properties": {"models": [{"name": "detail_v2.safetensors", "directory": "loras",
                                    "url": "https://huggingface.co/x/y/resolve/main/detail_v2.safetensors"}]},
         "widgets_values": ["detail_v2.safetensors", 1.0, 1.0]},
    ],
    "links": [[1, 1, 0, 3, 0, "MODEL"]], "groups": [], "config": {}, "extra": {}, "version": 0.4,
}


def _object_info() -> dict[str, Any]:
    info = json.loads(json.dumps(OBJECT_INFO))
    for name, (types, names) in OUTPUTS.items():
        if name in info:
            info[name]["output"], info[name]["output_name"] = types, names
    info["LoraLoader"] = {"input": {"required": {
        "model": ["MODEL"], "clip": ["CLIP"], "lora_name": [["detail.safetensors"]],
        "strength_model": ["FLOAT", {"default": 1.0}], "strength_clip": ["FLOAT", {"default": 1.0}]}},
        "output": ["MODEL", "CLIP"], "output_name": ["MODEL", "CLIP"]}
    return info


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        server.state.object_info = _object_info()
        server.state.manager = "V4.2.1"
        server.state.manager_mappings = {
            "ComfyUI_Comfyroll_CustomNodes": [["CR Prompt Text", "CR Text"], {"title_aux": "Comfyroll Studio"}],
            "https://github.com/someone/ComfyUI-Only-On-Git": [["CR Prompt Text"], {"title_aux": "Only on git"}],
        }
        yield server


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path / "data"))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import convert
        import install
        import workflow_import
        from comfy_http import Comfy

        monkeypatch.setattr(install, "MANAGER_POLL_SECONDS", 0.01)
        monkeypatch.setattr(workflow_import, "REBOOT_POLL_SECONDS", 0.01)
        yield workflow_import, Comfy, convert
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _inspect(plugin, comfy, **payload) -> dict[str, Any]:
    module, Comfy, _convert = plugin
    return module.inspect_import({"op": "inspect_import", **payload}, Comfy(comfy.url), "zh")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png(texts: dict[str, str], *, itxt: bool = False) -> bytes:
    """一张 1×1 的 PNG,带着 ComfyUI 存图时写的那几段文字(tEXt;`itxt` 时写成压缩过的 iTXt)。"""
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    for key, value in texts.items():
        if itxt:
            out += _chunk(b"iTXt", key.encode() + b"\x00\x01\x00\x00\x00" + zlib.compress(value.encode("utf-8")))
        else:
            out += _chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1"))
    return out + _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + _chunk(b"IEND", b"")


def _webp(tags: dict[int, str]) -> bytes:
    """一张 WebP,EXIF 里放着 ComfyUI 写的那几项(Make = `workflow:…`、Model = `prompt:…`),带 PIL 写的 `Exif\\0\\0` 头。"""
    values = [text.encode("utf-8") + b"\x00" for text in tags.values()]
    offset = 8 + 2 + 12 * len(tags) + 4
    ifd, body = struct.pack("<H", len(tags)), b""
    for tag, value in zip(tags, values):
        ifd += struct.pack("<HHII", tag, 2, len(value), offset + len(body))
        body += value
    exif = b"Exif\x00\x00" + b"II*\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + body
    image = b"VP8L" + struct.pack("<I", 5) + b"/\x00\x00\x00\x00" + b"\x00"
    exif_chunk = b"EXIF" + struct.pack("<I", len(exif)) + exif + (b"\x00" if len(exif) % 2 else b"")
    payload = b"WEBP" + image + exif_chunk
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_界面格式的JSON_认出来_预览带缺的节点和节点包_缺的模型_新的图id(plugin, comfy) -> None:
    out = _inspect(plugin, comfy, text=json.dumps(UI_FLOW, ensure_ascii=False), filename="人像 精修.json")
    assert out["format"] == "ui" and out["source"] == "json"
    assert out["workflow"]["nodes"] == UI_FLOW["nodes"]
    assert out["workflow"]["id"] != UI_FLOW["id"], "存进去是一张新的图:换一个图 id,不和原来那张的工具名撞"
    assert out["suggested_path"] == "人像 精修.json"
    assert [node["role"] for node in out["graph"]["nodes"]] == ["model", "missing", "model"]
    assert out["missing_nodes"] == [{"type": "CR Prompt Text", "count": 1, "packs": [
        {"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll Studio", "installed": False},
        {"id": "https://github.com/someone/ComfyUI-Only-On-Git", "title": "Only on git", "installed": False}]}]
    assert out["missing_models"] == [{"folder": "loras", "name": "detail_v2.safetensors",
                                      "url": "https://huggingface.co/x/y/resolve/main/detail_v2.safetensors"}]
    assert out["notes"] == []


def test_建议的路径不撞已有的(plugin, comfy) -> None:
    out = _inspect(plugin, comfy, text=json.dumps(UI_FLOW), filename="portrait.json")
    assert out["suggested_path"] == "portrait (1).json"
    assert _inspect(plugin, comfy, text=json.dumps(UI_FLOW))["suggested_path"] == "导入的工作流.json"


def test_API格式换成界面格式_位置按依赖排_值和连线排回去_转回API和原来一样(plugin, comfy) -> None:
    out = _inspect(plugin, comfy, text=json.dumps(TXT2IMG_API, ensure_ascii=False))
    assert out["format"] == "api"
    assert any("没有布局" in note for note in out["notes"])
    flow = out["workflow"]
    assert isinstance(flow["nodes"], list) and len(flow["nodes"]) == 7
    by_type = {node["type"]: node for node in flow["nodes"]}
    assert by_type["KSampler"]["widgets_values"] == [42, "fixed", 20, 7.0, "euler", "normal", 1.0], \
        "seed 后面跟着「生成后怎样」那一格:定成 fixed,导进来的值不被前端换掉"
    assert by_type["KSampler"]["title"] == "采样"
    assert by_type["CheckpointLoaderSimple"]["outputs"][1]["name"] == "CLIP"
    assert len(by_type["CheckpointLoaderSimple"]["outputs"][1]["links"]) == 2, "CLIP 接给了两个文本编码"
    assert by_type["SaveImage"]["pos"][0] > by_type["VAEDecode"]["pos"][0] > by_type["KSampler"]["pos"][0] > \
        by_type["CheckpointLoaderSimple"]["pos"][0], "按依赖从左往右排"
    column = [node for node in flow["nodes"] if node["pos"][0] == by_type["CLIPTextEncode"]["pos"][0]]
    tops = sorted((node["pos"][1], node["pos"][1] + node["size"][1]) for node in column)
    assert all(upper[1] <= lower[0] for upper, lower in zip(tops, tops[1:])), "同一列里不叠在一起"
    _module, _Comfy, convert = plugin
    back = convert.to_api(flow, comfy.state.object_info)
    assert {key: (node["class_type"], node["inputs"]) for key, node in back.items()} == \
        {key: (node["class_type"], node["inputs"]) for key, node in TXT2IMG_API.items()}
    assert out["kind"] == "image" and any(one["key"].endswith("steps") for one in out["parameters"])


def test_新版的动态下拉_API里是值的也排回widget(plugin, comfy) -> None:
    comfy.state.object_info["SaveVideo"] = {"input": {"required": {
        "video": ["VIDEO"], "filename_prefix": ["STRING", {"default": "video/ComfyUI"}],
        "format": ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "auto", "inputs": {"required": {}}}]}]},
        "optional": {"codec": ["COMFY_DYNAMICCOMBO_V3", {"options": []}]}}, "output": [], "output_node": True}
    comfy.state.object_info["LoadVideo"] = {"input": {"required": {"file": [["a.mp4"]]}}, "output": ["VIDEO"]}
    api = {"1": {"class_type": "LoadVideo", "inputs": {"file": "a.mp4"}},
           "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0], "filename_prefix": "v", "format": "mp4",
                                                       "format.codec": "h264", "codec": "auto"}}}
    out = _inspect(plugin, comfy, text=json.dumps(api))
    _module, _Comfy, convert = plugin
    back = convert.to_api(out["workflow"], comfy.state.object_info)
    assert back["2"]["inputs"] == api["2"]["inputs"]


def test_缺节点的API格式_值和连线也留着(plugin, comfy) -> None:
    api = {"1": {"class_type": "CR Prompt Text", "inputs": {"prompt": "猫", "extra": 3}},
           "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0], "clip": ["3", 1]}},
           "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}}}
    out = _inspect(plugin, comfy, text=json.dumps(api))
    nodes = {node["type"]: node for node in out["workflow"]["nodes"]}
    assert nodes["CR Prompt Text"]["widgets_values"] == ["猫", 3]
    assert nodes["CR Prompt Text"]["outputs"][0]["links"], "缺的节点的输出口照连线补出来"
    text_input = next(one for one in nodes["CLIPTextEncode"]["inputs"] if one["name"] == "text")
    assert text_input["widget"] == {"name": "text"} and text_input["link"] is not None, "接了线的 widget 变成输入口"
    assert out["missing_nodes"][0]["type"] == "CR Prompt Text"


def test_PNG里的工作流_界面格式优先_只有prompt时按API格式(plugin, comfy) -> None:
    both = _png({"prompt": json.dumps(TXT2IMG_API), "workflow": json.dumps(UI_FLOW)})
    out = _inspect(plugin, comfy, data=_b64(both), filename="ComfyUI_00012_.png")
    assert out["source"] == "png" and out["format"] == "ui" and out["suggested_path"] == "ComfyUI_00012_.json"
    only_prompt = _png({"prompt": json.dumps(TXT2IMG_API, ensure_ascii=False)}, itxt=True)
    out = _inspect(plugin, comfy, data=_b64(only_prompt), filename="mosael.png")
    assert out["source"] == "png" and out["format"] == "api" and len(out["workflow"]["nodes"]) == 7
    assert any("没有布局" in note for note in out["notes"])


def test_WebP的EXIF里的工作流(plugin, comfy) -> None:
    data = _webp({0x010F: "workflow:" + json.dumps(UI_FLOW), 0x0110: "prompt:" + json.dumps(TXT2IMG_API)})
    out = _inspect(plugin, comfy, data=_b64(data), filename="x.webp")
    assert out["source"] == "webp" and out["format"] == "ui"


def test_压缩包里取第一张_另外几张写在说明里(plugin, comfy) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._a.json", b"junk")
        archive.writestr("readme.txt", "说明")
        archive.writestr("flows/a.json", json.dumps(UI_FLOW))
        archive.writestr("flows/b.json", json.dumps(TXT2IMG_API))
    out = _inspect(plugin, comfy, data=_b64(buffer.getvalue()), filename="pack.zip")
    assert out["source"] == "zip" and out["format"] == "ui" and out["suggested_path"] == "a.json"
    assert any("b.json" in note for note in out["notes"])


def test_链接_这台ComfyUI自己的地址去取_别的站不替你去取(plugin, comfy) -> None:
    url = f"{comfy.url}/api/userdata/workflows%2Fportrait.json"
    out = _inspect(plugin, comfy, url=url)
    assert out["source"] == "url" and out["format"] == "ui" and out["suggested_path"] == "portrait (1).json"
    module, Comfy, _convert = plugin
    from lines import ComfyError

    with pytest.raises(ComfyError, match="下载下来拖进来"):
        module.inspect_import({"op": "inspect_import", "url": "https://example.com/flow.json"}, Comfy(comfy.url), "zh")


def test_网页不是文件_说清楚(plugin, comfy) -> None:
    comfy.state.static["/some/page"] = ("text/html; charset=utf-8", b"<html>workflow page</html>")
    module, Comfy, _convert = plugin
    from lines import ComfyError

    with pytest.raises(ComfyError, match="网页"):
        module.inspect_import({"op": "inspect_import", "url": f"{comfy.url}/some/page"}, Comfy(comfy.url), "zh")


@pytest.mark.parametrize("payload", [
    {"text": "随便写的几个字"},
    {"text": json.dumps({"hello": "world"})},
    {"data": _b64(_png({"parameters": "a cat, steps: 20"})), "filename": "sd-webui.png"},
])
def test_不是工作流的东西说清楚(plugin, comfy, payload) -> None:
    module, Comfy, _convert = plugin
    from lines import ComfyError

    with pytest.raises(ComfyError, match="认不出"):
        module.inspect_import({"op": "inspect_import", **payload}, Comfy(comfy.url), "zh")


def test_存进workflows_不覆盖_撞名给建议名(plugin, comfy) -> None:
    module, Comfy, _convert = plugin
    clash = module.save_workflow({"path": "portrait.json", "content": json.dumps(UI_FLOW)}, Comfy(comfy.url), "zh")
    assert clash == {"conflict": True, "suggestion": "portrait (1).json"}
    done = module.save_workflow({"path": "导入/人像.json", "content": json.dumps(UI_FLOW)}, Comfy(comfy.url), "zh")
    assert done == {"path": "导入/人像.json"}
    assert comfy.state.workflows["导入/人像.json"]["nodes"] == UI_FLOW["nodes"]
    writes = [one for one in comfy.state.calls if one[0] == "WRITE"]
    assert len(writes) == 2 and all(one[2]["overwrite"] is False for one in writes)
    with pytest.raises(Exception, match="不是一个能用的工作流路径"):
        module.save_workflow({"path": "../出去.json", "content": json.dumps(UI_FLOW)}, Comfy(comfy.url), "zh")
    with pytest.raises(Exception, match="不是一张界面格式的工作流"):
        module.save_workflow({"path": "x.json", "content": json.dumps(TXT2IMG_API)}, Comfy(comfy.url), "zh")


def test_装节点包_经Manager排队_registry里的按latest_git上的按unknown_装完说要重启(plugin, comfy) -> None:
    module, Comfy, _convert = plugin
    events: list[dict[str, Any]] = []
    out = module.install_nodes({"packs": ["ComfyUI_Comfyroll_CustomNodes", "https://github.com/someone/ComfyUI-Only-On-Git"]},
                               Comfy(comfy.url), "zh", events.append)
    tasks = [one[2] for one in comfy.state.calls if one[1] == "/v2/manager/queue/task"]
    assert [task["kind"] for task in tasks] == ["install", "install"]
    assert tasks[0]["params"] == {"id": "ComfyUI_Comfyroll_CustomNodes", "version": "latest", "selected_version": "latest",
                                  "mode": "cache", "channel": "default"}
    assert tasks[1]["params"]["id"] == "ComfyUI-Only-On-Git" and tasks[1]["params"]["selected_version"] == "unknown"
    assert out["installed"] == ["ComfyUI_Comfyroll_CustomNodes", "https://github.com/someone/ComfyUI-Only-On-Git"]
    assert out["restart"] is True
    assert any("重启" in (one.get("message") or "") for one in events)


def test_Manager的安全策略拒绝装节点_说人话和下一步(plugin, comfy) -> None:
    comfy.state.manager_outcome = "policy"
    module, Comfy, _convert = plugin
    from lines import ComfyError

    with pytest.raises(ComfyError, match="personal_cloud"):
        module.install_nodes({"packs": ["ComfyUI_Comfyroll_CustomNodes"]}, Comfy(comfy.url), "zh", lambda _event: None)
    assert any(MANAGER_POLICY_MESSAGE.split("\n")[0][:30] in entry["m"] for entry in comfy.state.log_entries)


def test_没装Manager_装不了_说怎么手动装(plugin, comfy) -> None:
    comfy.state.manager = None
    module, Comfy, _convert = plugin
    from lines import ComfyError

    with pytest.raises(ComfyError, match="custom_nodes"):
        module.install_nodes({"packs": ["ComfyUI_Comfyroll_CustomNodes"]}, Comfy(comfy.url), "zh", lambda _event: None)


def test_重启_经Manager_等它停下再起来(plugin, comfy) -> None:
    comfy.state.reboot_down_polls = 3
    module, Comfy, _convert = plugin
    out = module.reboot({"op": "reboot"}, Comfy(comfy.url), "zh")
    assert out == {"back": True}
    reboots = [one for one in comfy.state.calls if one[1] == "/v2/manager/reboot"]
    assert len(reboots) == 1 and reboots[0][2] == {}, "POST 带 JSON 正文(Manager 拒绝简单表单 POST)"


def test_本机服务_不经Manager重启_请宿主停了再起(plugin, comfy, monkeypatch) -> None:
    """宿主起停的本机服务(ADR 0041,宿主经 MOSAEL_LOCAL_SERVICE 告诉插件):Manager 在 Windows 上重启是另起一个进程、
    旧的退出,宿主会以为它崩了、再也停不掉它 —— 插件交回 host_restart,一个请求都不发给 Manager。"""
    monkeypatch.setenv("MOSAEL_LOCAL_SERVICE", "comfyui")
    module, Comfy, _convert = plugin
    assert module.reboot({"op": "reboot"}, Comfy(comfy.url), "zh") == {"host_restart": True}
    assert not [one for one in comfy.state.calls if one[1].startswith("/v2/manager")]


def test_Manager不让重启_说为什么(plugin, comfy) -> None:
    comfy.state.manager_reboot_allowed = False
    module, Comfy, _convert = plugin
    from lines import ComfyError

    with pytest.raises(ComfyError, match="security_level"):
        module.reboot({"op": "reboot"}, Comfy(comfy.url), "zh")
