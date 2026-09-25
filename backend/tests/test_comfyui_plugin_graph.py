"""ComfyUI 插件里的「图」:UI 格式 → API 格式、看出参数与槽位、把请求填进去、收产出。

这些知识原来在内核的 ComfyUI Adapter 里(`adapters/comfyui/client.py`),搬进插件之后照样钉住
那几个易碎点 —— control_after_generate 的隐藏项、转成输入的 widget 仍占位置、Reroute 透传、
muted 跳过、提示词递归穿过 ControlNet、占位符在解析之后填 —— 再加上搬过来之后才有的:一张图
怎么变成插件目录里的一个模型(ADR 0020)。纯函数,不连任何服务。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.fake_comfyui import OBJECT_INFO, PORTRAIT_UI, WAN_API, conn, widget

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
_MODULES = ("graph", "models", "run", "lines", "ws", "comfy_http", "main")


@pytest.fixture(scope="module")
def graph():
    """插件的模块名很普通(graph / models / run),用完就从 sys.modules 摘掉,不串到别的测试里。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import graph as module

        yield module
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


# --- UI 图 → API 图 ----------------------------------------------------------


def test_control_after_generate_is_skipped_and_links_resolve(graph) -> None:
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [42, "randomize", 20],
             "inputs": [conn("model", 1), widget("seed"), widget("steps")]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"], "inputs": [widget("ckpt_name")]},
        ],
        "links": [[1, 4, 0, 3, 0, "MODEL"]],
    }
    api = graph.graph_to_api_prompt(ui, OBJECT_INFO)
    assert api["3"]["inputs"]["seed"] == 42
    assert api["3"]["inputs"]["steps"] == 20, "'randomize' 是 seed 的隐藏项,必须跳过"
    assert api["3"]["inputs"]["model"] == ["4", 0]


def test_muted_and_ui_only_nodes_skipped(graph) -> None:
    ui = {
        "nodes": [
            {"id": 1, "type": "CLIPTextEncode", "mode": 0, "widgets_values": ["hi"], "inputs": [widget("text")]},
            {"id": 2, "type": "CLIPTextEncode", "mode": 2, "widgets_values": ["muted"], "inputs": [widget("text")]},
            {"id": 3, "type": "Note", "widgets_values": ["note"], "inputs": []},
        ],
        "links": [],
    }
    assert set(graph.graph_to_api_prompt(ui, OBJECT_INFO)) == {"1"}


def test_reroute_is_transparent(graph) -> None:
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20], "inputs": [conn("model", 2), widget("seed"), widget("steps")]},
            {"id": 9, "type": "Reroute", "inputs": [conn("", 1)]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"], "inputs": [widget("ckpt_name")]},
        ],
        "links": [[1, 4, 0, 9, 0, "MODEL"], [2, 9, 0, 3, 0, "MODEL"]],
    }
    api = graph.graph_to_api_prompt(ui, OBJECT_INFO)
    assert "9" not in api
    assert api["3"]["inputs"]["model"] == ["4", 0]


def test_converted_widget_keeps_index_aligned(graph) -> None:
    """widget 拉成连接之后仍占 widgets_values 一个位置 —— 不步进的话 batch_size 会取到 width 的旧值。"""
    ui = {
        "nodes": [
            {"id": 5, "type": "EmptyLatentImage", "widgets_values": [512, 768, 1],
             "inputs": [{"name": "width", "widget": {"name": "width"}, "link": 1},
                        {"name": "height", "widget": {"name": "height"}, "link": 2},
                        {"name": "batch_size", "widget": {"name": "batch_size"}, "link": None}]},
            {"id": 8, "type": "CheckpointLoaderSimple", "widgets_values": ["m"], "inputs": [widget("ckpt_name")]},
        ],
        "links": [[1, 8, 0, 5, 0, "INT"], [2, 8, 1, 5, 1, "INT"]],
    }
    api = graph.graph_to_api_prompt(ui, OBJECT_INFO)
    assert api["5"]["inputs"]["batch_size"] == 1
    assert api["5"]["inputs"]["width"] == ["8", 0]


def test_api_format_passes_through(graph) -> None:
    """用户「导出 (API)」后存进 workflows/ 的图本来就是 API 格式,原样用。"""
    assert graph.is_api_graph(WAN_API)
    assert graph.graph_to_api_prompt(WAN_API, OBJECT_INFO) == WAN_API


# --- 一张图 → 插件目录里的一个模型 -----------------------------------------------


def _portrait(graph):
    api = graph.graph_to_api_prompt(PORTRAIT_UI, OBJECT_INFO)
    return graph.describe("portrait.json", "portrait", api, OBJECT_INFO, graph.ui_titles(PORTRAIT_UI))


def test_提示词种子尺寸对到宿主的控件上(graph) -> None:
    model = _portrait(graph)
    parameters = model["parameters"]
    assert model["kind"] == "image"
    assert parameters["negative_prompt"] == {"type": "string"}
    assert parameters["seed"]["type"] == "integer"
    # 这张图自己的尺寸是默认值,排在常备的几档前面
    assert parameters["size"]["default"] == "832x1216" and parameters["size"]["enum"][0] == "832x1216"
    # 这些不再单独列:提示词、种子、宽高都由宿主的主控件填
    for gone in ("6.text", "7.text", "3.seed", "5.width", "5.height"):
        assert gone not in parameters


def test_其余可调的输入带着ComfyUI给的类型和范围(graph) -> None:
    parameters = _portrait(graph)["parameters"]
    assert parameters["3.steps"] == {"type": "integer", "minimum": 1, "maximum": 10000, "default": 20, "title": "采样 · steps"}
    assert parameters["3.cfg"]["type"] == "number" and parameters["3.cfg"]["multipleOf"] == 0.1
    assert parameters["3.sampler_name"]["enum"] == ["euler", "dpmpp_2m"]
    assert parameters["4.ckpt_name"]["enum"] == ["sd_xl_base.safetensors", "v1-5.ckpt"]
    assert parameters["9.filename_prefix"]["x-advanced"] is True, "保存节点的输入收进高级"
    assert "10.image" not in parameters, "LoadImage 是参考图槽位,不是一个文本参数"
    assert "3.model" not in parameters, "连线不可调"


def test_LoadImage_变成参考图槽位(graph) -> None:
    model = _portrait(graph)
    assert model["inputs"] == [{"role": "reference_image", "max": 1}]
    assert model["modes"] == ["text-to-image", "image-to-image"]
    assert model["prompt_dialect"] == "sd-tags"


def test_视频图_接到start_image的是首帧(graph) -> None:
    model = graph.describe("video/wan.json", "wan", WAN_API, OBJECT_INFO)
    assert model["kind"] == "video"
    assert model["inputs"] == [{"role": "first_frame", "max": 1}]
    assert model["modes"] == ["image-to-video"]
    assert model["parameters"]["size"]["default"] == "832x480", "WanImageToVideo 决定成片尺寸"
    assert model["parameters"]["20.length"]["default"] == 81


# --- 把请求填进图里 ---------------------------------------------------------------


def test_提示词递归穿过ControlNet_正负不混(graph) -> None:
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 0, "positive": ["11", 0], "negative": ["11", 1]}},
        "11": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old pos"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old neg"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
    }
    filled = graph.fill(api, {"prompt": "P", "negative": "N", "seed": 99, "width": 768, "height": 768}, {})
    assert filled["6"]["inputs"]["text"] == "P" and filled["7"]["inputs"]["text"] == "N"
    assert filled["3"]["inputs"]["seed"] == 99
    assert filled["5"]["inputs"] == {"width": 768, "height": 768}
    assert api["6"]["inputs"]["text"] == "old pos", "不改入参"


def test_没选尺寸就用这张图自己的尺寸(graph) -> None:
    """此前的 Adapter 不管三七二十一填 1024x1024 —— 一张存好的 832x1216 人像被悄悄改成了方图。"""
    api = {"5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}}}
    assert graph.fill(api, {"prompt": "P"}, {})["5"]["inputs"]["width"] == 832


def test_Flux与SDXL的写提示词节点_每一格都写(graph) -> None:
    api = {
        "13": {"class_type": "SamplerCustomAdvanced", "inputs": {"guider": ["22", 0], "noise": ["25", 0]}},
        "22": {"class_type": "BasicGuider", "inputs": {"conditioning": ["26", 0]}},
        "26": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": 3.5}},
        "6": {"class_type": "CLIPTextEncodeFlux", "inputs": {"clip_l": "x", "t5xxl": "y", "guidance": 3.5}},
        "25": {"class_type": "RandomNoise", "inputs": {"noise_seed": 5}},
    }
    filled = graph.fill(api, {"prompt": "P", "seed": 7}, {})
    assert (filled["6"]["inputs"]["clip_l"], filled["6"]["inputs"]["t5xxl"]) == ("P", "P")
    assert filled["25"]["inputs"]["noise_seed"] == 7, "RandomNoise 的种子也是种子"


def test_连线来的文字不被字面量盖掉(graph) -> None:
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 0, "positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["8", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"}},
    }
    filled = graph.fill(api, {"prompt": "P", "negative": "N", "seed": 1}, {})
    assert filled["6"]["inputs"]["text"] == ["8", 0]
    assert filled["7"]["inputs"]["text"] == "N"


def test_参数表里动过的值按节点写回_不在的跳过(graph) -> None:
    api = {"3": {"class_type": "KSampler", "inputs": {"steps": 20, "model": ["4", 0]}}}
    filled = graph.fill(api, {}, {"3.steps": 30, "3.model": "x", "99.steps": 1, "nodot": 1})
    assert filled["3"]["inputs"] == {"steps": 30, "model": ["4", 0]}


def test_参考图按角色接到LoadImage上(graph) -> None:
    api = {
        "10": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "11": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
    }
    wired = graph.wire_images(api, "image", {"reference_image": ["mosael/x.png"]})
    assert wired["10"]["inputs"]["image"] == "mosael/x.png"
    assert wired["11"]["inputs"]["image"] == "b.png", "给得比槽位少,剩下的用它原来那张"


class TestPlaceholders:
    def test_exact_placeholder_keeps_the_raw_type(self, graph) -> None:
        filled = graph.substitute_placeholders({"3": {"inputs": {"seed": "{{seed}}"}}}, {"seed": 42})
        assert filled["3"]["inputs"]["seed"] == 42

    def test_embedded_placeholder_splices_text(self, graph) -> None:
        filled = graph.substitute_placeholders({"6": {"inputs": {"text": "masterpiece, {{prompt}}, 4k"}}}, {"prompt": "柴犬"})
        assert filled["6"]["inputs"]["text"] == "masterpiece, 柴犬, 4k"

    def test_quotes_and_backslashes_cannot_break_the_graph(self, graph) -> None:
        evil = 'she said "hi" \\ {"not": "json"}'
        assert graph.substitute_placeholders({"6": {"inputs": {"text": "{{prompt}}"}}}, {"prompt": evil})["6"]["inputs"]["text"] == evil

    def test_unknown_placeholder_is_left_visible(self, graph) -> None:
        assert graph.substitute_placeholders({"1": {"inputs": {"x": "{{nope}}"}}}, {})["1"]["inputs"]["x"] == "{{nope}}"


# --- 收产出 -----------------------------------------------------------------------


def test_存下来的优先_预览兜底(graph) -> None:
    entry = {"outputs": {
        "9": {"images": [{"filename": "a.png", "type": "output", "subfolder": ""}]},
        "12": {"images": [{"filename": "p.png", "type": "temp", "subfolder": ""}]},
    }}
    assert [item["filename"] for item in graph.collect_outputs(entry, "image")] == ["a.png"]
    only_preview = {"outputs": {"12": {"images": [{"filename": "p.png", "type": "temp"}]}}}
    assert [item["filename"] for item in graph.collect_outputs(only_preview, "image")] == ["p.png"]


def test_视频要的是合成的那一段_不是第一帧(graph) -> None:
    entry = {"outputs": {
        "8": {"images": [{"filename": "frame_00001.png", "type": "output"}]},
        "12": {"gifs": [{"filename": "out.mp4", "subfolder": "video", "type": "output"}]},
    }}
    assert [item["filename"] for item in graph.collect_outputs(entry, "video")] == ["out.mp4"]


def test_校验错误和执行错误说得出是哪个节点(graph) -> None:
    detail = {"error": {"message": "Prompt outputs failed validation"},
              "node_errors": {"4": {"errors": [{"message": "Value not in list", "details": "ckpt_name: 'x' not in [...]"}]}}}
    said = graph.validation_errors(detail)
    assert "Prompt outputs failed validation" in said and "#4 Value not in list: ckpt_name" in said
    status = {"messages": [["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]]}
    assert graph.execution_error(status) == "KSampler: CUDA out of memory"
