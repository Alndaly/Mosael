"""ComfyUI 插件里的「图」:UI 格式 → API 格式、看出参数与槽位、把请求填进去、收产出。

这些知识原来在内核的 ComfyUI Adapter 里(`adapters/comfyui/client.py`),搬进插件之后照样钉住
那几个易碎点 —— control_after_generate 的隐藏项、转成输入的 widget 仍占位置、Reroute 透传、
muted 跳过、提示词递归穿过 ControlNet、占位符在解析之后填 —— 再加上搬过来之后才有的:一张图
怎么变成插件目录里的一个模型(ADR 0020)。纯函数,不连任何服务。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.fake_comfyui import (
    HAILUO_API,
    INPAINT_MUTED_FIRST_PASS_API,
    INPAINT_NODE_INFO,
    KLING_I2V_API,
    MINIMAX_H3_REFERENCE_API,
    MINIMAX_I2V_API,
    MINIMAX_T2V_API,
    OBJECT_INFO,
    PORTRAIT_UI,
    PREVIEWS_ONLY_API,
    TWO_PASS_HAND_DEPTH,
    TWO_SAVES_API,
    TWO_VIDEOS_API,
    UPSCALE_API,
    VEO_FLF_API,
    VIDEO_NODE_INFO,
    WAN_API,
    WAN_WRAPPER_API,
    conn,
    fixture_workflow,
    minimax_h3_ui,
    widget,
)

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "workflows",
            "tooling")


@pytest.fixture(scope="module")
def tools():
    """插件的模块名很普通(graph / models / run),用完就从 sys.modules 摘掉,不串到别的测试里。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import convert
        import graph

        yield graph, convert
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


@pytest.fixture(scope="module")
def graph(tools):
    return tools[0]


@pytest.fixture(scope="module")
def convert(tools):
    return tools[1]


# --- UI 图 → API 图 ----------------------------------------------------------


def test_control_after_generate_is_skipped_and_links_resolve(convert) -> None:
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [42, "randomize", 20],
             "inputs": [conn("model", 1), widget("seed"), widget("steps")]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"], "inputs": [widget("ckpt_name")]},
        ],
        "links": [[1, 4, 0, 3, 0, "MODEL"]],
    }
    api = convert.to_api(ui, OBJECT_INFO)
    assert api["3"]["inputs"]["seed"] == 42
    assert api["3"]["inputs"]["steps"] == 20, "'randomize' 是 seed 的隐藏项,必须跳过"
    assert api["3"]["inputs"]["model"] == ["4", 0]


def test_muted_and_ui_only_nodes_skipped(convert) -> None:
    ui = {
        "nodes": [
            {"id": 1, "type": "CLIPTextEncode", "mode": 0, "widgets_values": ["hi"], "inputs": [widget("text")]},
            {"id": 2, "type": "CLIPTextEncode", "mode": 2, "widgets_values": ["muted"], "inputs": [widget("text")]},
            {"id": 3, "type": "Note", "widgets_values": ["note"], "inputs": []},
        ],
        "links": [],
    }
    assert set(convert.to_api(ui, OBJECT_INFO)) == {"1"}


def test_rgthree只在前端的虚拟节点不进图(convert) -> None:
    """rgthree 的「Mute / Bypass Relay / Repeater」「Node Collector」「Random Unmuter」「Power Conductor」是前端的虚拟节点
    (isVirtualNode):ComfyUI 自己的前端提交时不带它们,后端也没有这几个类。带上的话 ComfyUI 回一句「Node … not found」
    把整张图拒掉 —— DaSiWa WAN 2.2 那张图就因为子图里的 Relay / Repeater 一次都跑不起来。"""
    ui = {
        "nodes": [
            {"id": 1, "type": "CLIPTextEncode", "widgets_values": ["hi"], "inputs": [widget("text")]},
            {"id": 2, "type": "Mute / Bypass Relay (rgthree)", "inputs": [{"name": "", "type": "*", "link": None}],
             "outputs": [{"name": "REPEATER", "type": "_NODE_REPEATER_", "links": [1]}]},
            {"id": 3, "type": "Mute / Bypass Repeater (rgthree)",
             "inputs": [{"name": "Mute / Bypass Relay (rgthree)", "type": "_NODE_REPEATER_", "link": 1}]},
            {"id": 4, "type": "Node Collector (rgthree)", "inputs": []},
            {"id": 5, "type": "Random Unmuter (rgthree)", "inputs": []},
            {"id": 6, "type": "Power Conductor (rgthree)", "inputs": []},
        ],
        "links": [[1, 2, 0, 3, 0, "_NODE_REPEATER_"]],
    }
    assert set(convert.to_api(ui, OBJECT_INFO)) == {"1"}


def test_reroute_is_transparent(convert) -> None:
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20], "inputs": [conn("model", 2), widget("seed"), widget("steps")]},
            {"id": 9, "type": "Reroute", "inputs": [conn("", 1)]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"], "inputs": [widget("ckpt_name")]},
        ],
        "links": [[1, 4, 0, 9, 0, "MODEL"], [2, 9, 0, 3, 0, "MODEL"]],
    }
    api = convert.to_api(ui, OBJECT_INFO)
    assert "9" not in api
    assert api["3"]["inputs"]["model"] == ["4", 0]


def test_converted_widget_keeps_index_aligned(convert) -> None:
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
    api = convert.to_api(ui, OBJECT_INFO)
    assert api["5"]["inputs"]["batch_size"] == 1
    assert api["5"]["inputs"]["width"] == ["8", 0]


def test_api_format_passes_through(convert) -> None:
    """用户「导出 (API)」后存进 workflows/ 的图本来就是 API 格式,原样用。"""
    assert convert.is_api_graph(WAN_API)
    assert convert.to_api(WAN_API, OBJECT_INFO) == WAN_API


def test_老版本前端存的图_widget不在inputs里也按节点定义取值(convert) -> None:
    """老版本前端存的图,`node.inputs` 只列连线:按 inputs 数 widget 的话 KSampler 一个值都拿不到,提交就被拒。"""
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [7, "randomize", 25, 6.5, "euler", "karras", 0.9],
             "inputs": [conn("model", 1)]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"]},
            {"id": 5, "type": "EmptyLatentImage", "widgets_values": [640, 768, 2]},
        ],
        "links": [[1, 4, 0, 3, 0, "MODEL"]],
    }
    api = convert.to_api(ui, OBJECT_INFO)
    assert api["3"]["inputs"] == {"seed": 7, "steps": 25, "cfg": 6.5, "sampler_name": "euler", "scheduler": "karras",
                                  "denoise": 0.9, "model": ["4", 0]}
    assert api["4"]["inputs"] == {"ckpt_name": "m.safetensors"}
    assert api["5"]["inputs"] == {"width": 640, "height": 768, "batch_size": 2}


def test_seed没声明control_after_generate也占一格_定义多了输入用缺省值(convert) -> None:
    info = {"MySampler": {"input": {"required": {
        "seed": ["INT", {"default": 0}], "steps": ["INT", {"default": 20}]},
        "optional": {"eta": ["FLOAT", {"default": 0.5}]}}}}
    ui = {"nodes": [{"id": 1, "type": "MySampler", "widgets_values": [11, "fixed", 30]}], "links": []}
    assert convert.to_api(ui, info)["1"]["inputs"] == {"seed": 11, "steps": 30, "eta": 0.5}


def test_按名字存的widgets_values_和上传按钮那一格(convert) -> None:
    """VHS 的节点把 widgets_values 存成对象;读素材的节点在必填输入之后多一个上传按钮。"""
    info = {
        "VHS_VideoCombine": {"input": {"required": {"images": ["IMAGE"], "frame_rate": ["FLOAT", {"default": 8}],
                                                    "format": [["video/h264-mp4", "image/gif"]]}}},
        "LoadImageMask": OBJECT_INFO["LoadImageMask"],
        "MaskTool": {"input": {"required": {"image": [["a.png"], {"image_upload": True}]},
                               "optional": {"feather": ["INT", {"default": 0}]}}},
    }
    ui = {"nodes": [
        {"id": 1, "type": "VHS_VideoCombine", "inputs": [conn("images", None)],
         "widgets_values": {"frame_rate": 24, "format": "video/h264-mp4", "videopreview": {"hidden": False}}},
        {"id": 2, "type": "LoadImageMask", "widgets_values": ["m.png", "red", "image"]},
        {"id": 3, "type": "MaskTool", "widgets_values": ["a.png", "image", 6]},
    ], "links": []}
    api = convert.to_api(ui, info)
    assert api["1"]["inputs"] == {"frame_rate": 24, "format": "video/h264-mp4"}
    assert api["2"]["inputs"] == {"image": "m.png", "channel": "red"}
    assert api["3"]["inputs"] == {"image": "a.png", "feather": 6}, "上传按钮那一格跳过,后面的不错位"


def test_值是数组的widget包一层_不被当成连线(convert) -> None:
    info = {"Points": {"input": {"required": {"points": ["STRING", {}]}}}}
    ui = {"nodes": [{"id": 1, "type": "Points", "widgets_values": [[1, 2]]}], "links": []}
    assert convert.to_api(ui, info)["1"]["inputs"]["points"] == {"__value__": [1, 2]}


def _chain(mode: int) -> dict:
    """checkpoint → LoRA(模式可调)→ KSampler / CLIPTextEncode。"""
    return {
        "nodes": [
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"],
             "outputs": [{"name": "MODEL", "type": "MODEL"}, {"name": "CLIP", "type": "CLIP"}, {"name": "VAE", "type": "VAE"}]},
            {"id": 10, "type": "LoraLoader", "mode": mode, "widgets_values": ["detail.safetensors", 0.8, 1.0],
             "inputs": [{"name": "model", "type": "MODEL", "link": 1}, {"name": "clip", "type": "CLIP", "link": 2}],
             "outputs": [{"name": "MODEL", "type": "MODEL"}, {"name": "CLIP", "type": "CLIP"}]},
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1],
             "inputs": [{"name": "model", "type": "MODEL", "link": 3}]},
            {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["a cat"],
             "inputs": [{"name": "clip", "type": "CLIP", "link": 4}]},
        ],
        "links": [[1, 4, 0, 10, 0, "MODEL"], [2, 4, 1, 10, 1, "CLIP"], [3, 10, 0, 3, 0, "MODEL"],
                  [4, 10, 1, 6, 0, "CLIP"]],
    }


def test_旁路的节点透明_下游直通到它同类型的输入(convert) -> None:
    """用户关掉(bypass)一个 LoRA:模型和 CLIP 照样流下去,而不是留一根指向不存在节点的线让 ComfyUI 拒掉。"""
    api = convert.to_api(_chain(4), OBJECT_INFO)
    assert "10" not in api
    assert api["3"]["inputs"]["model"] == ["4", 0]
    assert api["6"]["inputs"]["clip"] == ["4", 1]


def test_静音的节点_连到它的插口去掉_widget留着自己的值(convert) -> None:
    ui = _chain(2)
    ui["nodes"][2]["inputs"].append({"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": 5})
    ui["links"].append([5, 10, 0, 3, 5, "INT"])
    api = convert.to_api(ui, OBJECT_INFO)
    assert "10" not in api
    assert "model" not in api["3"]["inputs"] and "clip" not in api["6"]["inputs"]
    assert api["3"]["inputs"]["steps"] == 20


def test_PrimitiveNode的值写进下游那一格_后端的PrimitiveInt照常进图(convert) -> None:
    info = {**OBJECT_INFO, "PrimitiveInt": {"input": {"required": {"value": ["INT", {"default": 0}]}}}}
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1],
             "inputs": [{"name": "seed", "type": "INT", "widget": {"name": "seed"}, "link": 1},
                        {"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": 2}]},
            {"id": 20, "type": "PrimitiveNode", "widgets_values": [123456, "randomize"],
             "outputs": [{"name": "INT", "type": "INT", "links": [1]}]},
            {"id": 21, "type": "PrimitiveInt", "widgets_values": [33]},
        ],
        "links": [[1, 20, 0, 3, 0, "INT"], [2, 21, 0, 3, 1, "INT"]],
    }
    api = convert.to_api(ui, info)
    assert "20" not in api
    assert api["3"]["inputs"]["seed"] == 123456
    assert api["21"] == {"class_type": "PrimitiveInt", "inputs": {"value": 33}, "_meta": {"title": "PrimitiveInt"}}
    assert api["3"]["inputs"]["steps"] == ["21", 0]


def test_GetNode接到同名SetNode的上游(convert) -> None:
    ui = {
        "nodes": [
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"]},
            {"id": 30, "type": "SetNode", "widgets_values": ["model"], "inputs": [{"name": "MODEL", "type": "MODEL", "link": 1}]},
            {"id": 31, "type": "GetNode", "widgets_values": ["model"], "outputs": [{"name": "MODEL", "type": "MODEL"}]},
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1],
             "inputs": [{"name": "model", "type": "MODEL", "link": 2}]},
        ],
        "links": [[1, 4, 0, 30, 0, "MODEL"], [2, 31, 0, 3, 0, "MODEL"]],
    }
    api = convert.to_api(ui, OBJECT_INFO)
    assert set(api) == {"4", "3"}
    assert api["3"]["inputs"]["model"] == ["4", 0]


def test_子图展开成里面的节点_id是外层冒号里层(convert) -> None:
    """新版前端的子图:一个节点的类型是子图的 id,里面的节点带着自己的连线(对象写法)和输入输出口。"""
    sub_id = "9f0c2d3e-1111-4a2b-8c3d-5e6f7a8b9c0d"
    ui = {
        "nodes": [
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"]},
            {"id": 50, "type": sub_id, "title": "采样组",
             "inputs": [{"name": "model", "type": "MODEL", "link": 1},
                        {"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": None}],
             "outputs": [{"name": "LATENT", "type": "LATENT", "links": [2]}],
             "widgets_values": [35]},
            {"id": 8, "type": "VAEDecode", "inputs": [{"name": "samples", "type": "LATENT", "link": 2}]},
        ],
        "links": [[1, 4, 0, 50, 0, "MODEL"], [2, 50, 0, 8, 0, "LATENT"]],
        "definitions": {"subgraphs": [{
            "id": sub_id, "name": "采样组",
            "inputNode": {"id": -10, "bounding": [0, 0, 1, 1]}, "outputNode": {"id": -20, "bounding": [0, 0, 1, 1]},
            "inputs": [{"id": "a", "name": "model", "type": "MODEL", "linkIds": [11]},
                       {"id": "b", "name": "steps", "type": "INT", "linkIds": [12]}],
            "outputs": [{"id": "c", "name": "LATENT", "type": "LATENT", "linkIds": [13]}],
            "nodes": [
                {"id": 3, "type": "KSampler", "title": "精修", "widgets_values": [5, "fixed", 20, 7, "euler", "normal", 1],
                 "inputs": [{"name": "model", "type": "MODEL", "link": 11},
                            {"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": 12}]},
            ],
            "links": [
                {"id": 11, "origin_id": -10, "origin_slot": 0, "target_id": 3, "target_slot": 0, "type": "MODEL"},
                {"id": 12, "origin_id": -10, "origin_slot": 1, "target_id": 3, "target_slot": 1, "type": "INT"},
                {"id": 13, "origin_id": 3, "origin_slot": 0, "target_id": -20, "target_slot": 0, "type": "LATENT"},
            ],
        }]},
    }
    api = convert.to_api(ui, OBJECT_INFO)
    assert set(api) == {"4", "50:3", "8"}
    assert api["50:3"]["inputs"]["model"] == ["4", 0]
    assert api["50:3"]["inputs"]["steps"] == 35, "子图节点上提升出来的那一格"
    assert api["50:3"]["_meta"]["title"] == "精修"
    assert api["8"]["inputs"]["samples"] == ["50:3", 0]
    assert convert.titles_of(api)["50:3"] == "精修"


def test_种子的生成后怎样记在_meta里_没给种子时照它办(graph, convert) -> None:
    api = convert.to_api(PORTRAIT_UI, OBJECT_INFO)
    assert api["3"]["_meta"]["control_after_generate"] == {"seed": "randomize"}
    assert graph.fill(api, {}, {})["3"]["inputs"]["seed"] != 42, "每次随机的:换一个"
    assert graph.fill(api, {"seed": 5}, {})["3"]["inputs"]["seed"] == 5
    fixed = convert.to_api({**PORTRAIT_UI, "nodes": [
        {**PORTRAIT_UI["nodes"][0], "widgets_values": [42, "fixed", 20, 7.0, "euler", "normal", 1.0]},
        *PORTRAIT_UI["nodes"][1:]]}, OBJECT_INFO)
    assert graph.fill(fixed, {}, {})["3"]["inputs"]["seed"] == 42, "固定的:留着"
    primitive = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1],
             "inputs": [{"name": "seed", "type": "INT", "widget": {"name": "seed"}, "link": 1}]},
            {"id": 20, "type": "PrimitiveNode", "widgets_values": [9, "randomize"]},
        ],
        "links": [[1, 20, 0, 3, 0, "INT"]],
    }
    assert convert.to_api(primitive, OBJECT_INFO)["3"]["_meta"]["control_after_generate"] == {"seed": "randomize"}


def test_rgthree的Seed后面那几格是按钮_不是每次随机(graph, convert) -> None:
    """用户的 moodyKrea24KHD_v20 里四个 rgthree「Seed」:widgets_values 是 [种子, "", "", ""] —— 后面三格是它的按钮
    (「每次随机」「新的固定种子」「用上一次的」),不是 ComfyUI 的「生成后怎样」。此前空串被当成「不是 fixed」,
    存着的固定种子每次都被换掉;rgthree 的种子只有存成 -1 才是每次随机(那由它自己处理)。"""
    info = {**OBJECT_INFO, "Seed (rgthree)": {"input": {"required": {"seed": ["INT", {"default": 0}]}}}}
    ui = {"nodes": [
        {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1],
         "inputs": [{"name": "seed", "type": "INT", "widget": {"name": "seed"}, "link": 1}]},
        {"id": 9, "type": "Seed (rgthree)", "widgets_values": [470193541057076, "", "", ""],
         "outputs": [{"name": "SEED", "type": "INT", "links": [1]}]},
    ], "links": [[1, 9, 0, 3, 0, "INT"]]}
    api = convert.to_api(ui, info)
    assert graph.fill(api, {}, {})["9"]["inputs"]["seed"] == 470193541057076
    assert graph.fill(api, {"seed": 5}, {})["9"]["inputs"]["seed"] == 5, "给了种子照样写进去"


def test_旧式组节点说清楚要转成子图(convert) -> None:
    ui = {"nodes": [{"id": 1, "type": "workflow>采样", "widgets_values": []}], "links": [],
          "extra": {"groupNodes": {"采样": {"nodes": []}}}}
    with pytest.raises(Exception, match="子图"):
        convert.to_api(ui, OBJECT_INFO)


# --- 一张图 → 插件目录里的一个模型 -----------------------------------------------


def _portrait(graph, convert):
    api = convert.to_api(PORTRAIT_UI, OBJECT_INFO)
    return graph.describe("portrait.json", "portrait", api, OBJECT_INFO, convert.titles_of(api))


def test_提示词种子尺寸对到宿主的控件上(graph, convert) -> None:
    model = _portrait(graph, convert)
    parameters = model["parameters"]
    assert model["kind"] == "image"
    assert parameters["negative_prompt"] == {"type": "string"}
    assert parameters["seed"]["type"] == "integer"
    # 这张图自己的尺寸是默认值,排在常备的几档前面
    assert parameters["size"]["default"] == "832x1216" and parameters["size"]["examples"][0] == "832x1216"
    assert "enum" not in parameters["size"], "推荐的几档,不是限制:任意宽高都收(按 8 的倍数取整)"
    assert (parameters["size"]["minimum"], parameters["size"]["multipleOf"]) == (16, 8)
    # 这些不再单独列:提示词、种子、宽高都由宿主的主控件填
    for gone in ("6.text", "7.text", "3.seed", "5.width", "5.height"):
        assert gone not in parameters


def test_其余可调的输入带着ComfyUI给的类型和范围(graph, convert) -> None:
    parameters = _portrait(graph, convert)["parameters"]
    assert parameters["3.steps"] == {
        "title": {"zh": "步数", "en": "Steps"}, "type": "integer", "minimum": 1, "maximum": 10000, "default": 20,
        "description": "采样 · steps",
    }, "人话名字;原始的「节点 · 输入名」在说明里"
    assert parameters["3.cfg"]["type"] == "number" and parameters["3.cfg"]["multipleOf"] == 0.1
    assert parameters["3.sampler_name"]["enum"] == ["euler", "dpmpp_2m"]
    assert parameters["4.ckpt_name"]["enum"] == ["sd_xl_base.safetensors", "v1-5.ckpt"]
    assert parameters["4.ckpt_name"]["title"] == {"zh": "模型", "en": "Checkpoint"}
    assert "9.filename_prefix" not in parameters, "文件名前缀是 ComfyUI 那一侧的事,不在 Mosael 里调"
    assert "10.image" not in parameters, "LoadImage 是参考图槽位,不是一个文本参数"
    assert "3.model" not in parameters, "连线不可调"
    assert "5.batch_size" not in parameters, "一次几张是宿主的控件(num_images)"


def test_值不是一个标量的输入不列成参数(graph) -> None:
    """数组值的 widget 在 API 图里包成 {"__value__": [...]}(曲线、点列):参数表只有标量控件,列出来就是一个
    没有默认值的文本框,用户一填就把那一格的结构换成一串字。"""
    api = {"1": {"class_type": "Points", "inputs": {"points": {"__value__": [1, 2]}, "radius": 3}}}
    info = {"Points": {"input": {"required": {"points": ["STRING", {}], "radius": ["INT", {"default": 1}]}}}}
    assert list(graph.tunable(api, info)) == ["1.radius"]


def test_常用的在前_细节收进高级(graph, convert) -> None:
    parameters = _portrait(graph, convert)["parameters"]
    tuned = [key for key in parameters if "." in key]
    assert tuned[:5] == ["4.ckpt_name", "3.steps", "3.cfg", "3.sampler_name", "3.scheduler"], tuned
    assert not any(parameters[key].get("x-advanced") for key in ("4.ckpt_name", "3.steps", "3.cfg", "3.sampler_name"))


def test_撞名时才带上是哪个节点(graph) -> None:
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "positive": ["6", 0], "negative": ["7", 0]}},
        "8": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 10, "positive": ["6", 0], "negative": ["7", 0]}},
        "9": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 5, "positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "p"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "n"}},
    }
    parameters = graph.describe("x.json", "x", api, OBJECT_INFO, {"9": "精修"})["parameters"]
    assert parameters["3.steps"]["title"] == {"zh": "步数", "en": "Steps"}
    assert parameters["8.steps"]["title"] == {"zh": "步数 · 第 2 个 K 采样器", "en": "Steps · KSampler #2"}, \
        "撞名时带的是节点给人看的名字(中文是核心节点的中文名),不是类名"
    assert parameters["9.steps"]["title"] == {"zh": "步数 · 精修", "en": "Steps · 精修"}, "用户起了名字就用名字"


def test_LoRA和checkpoint是下拉_选项来自object_info(graph) -> None:
    api = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
        "10": {"class_type": "LoraLoader", "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": "detail.safetensors",
                                                      "strength_model": 0.8, "strength_clip": 1.0}},
    }
    parameters = graph.describe("x.json", "x", api, OBJECT_INFO)["parameters"]
    assert parameters["10.lora_name"]["enum"] == ["detail.safetensors", "anime.safetensors"]
    assert parameters["10.lora_name"]["title"] == {"zh": "LoRA", "en": "LoRA"}
    assert parameters["10.strength_model"]["default"] == 0.8 and "x-advanced" not in parameters["10.strength_model"]
    assert parameters["10.strength_clip"]["x-advanced"] is True


# --- 「张数」是跑几遍:每遍按工作流原样,画布上存着的 batch_size 照旧(1.12.3) -------------------------------
#
# 维护者拍板:工作流这里的张数 = 跑几遍。此前张数写进画布的 batch_size(缺省 1),存着 4 张的工作流在 Mosael 里只出 1 张;
# 现在每遍按工作流原样出它那一批,一共「跑几遍 × 一遍几张」。键名照旧是 num_images,标着 `x-count-unit: runs`。


def test_张数是跑几遍_一遍几张按画布上存着的批量(graph, convert) -> None:
    model = _portrait(graph, convert)
    assert model["parameters"]["num_images"] == {"type": "integer", "minimum": 1, "maximum": 4, "default": 1,
                                                 "x-count-unit": "runs", "x-batch": 1}
    assert model["outputs_per_run"] == 1 and model["max_outputs"] == 4
    two = graph.describe("two.json", "two", TWO_SAVES_API, OBJECT_INFO)
    assert two["parameters"]["num_images"]["x-batch"] == 2, "画布上存着一次两张:一遍每个保存节点 2 张"
    assert two["outputs_per_run"] == 4 and two["max_outputs"] == 16, "两个保存节点 × 批量 2,最多跑 4 遍"
    api = convert.to_api(PORTRAIT_UI, OBJECT_INFO)
    assert graph.fill(api, {"seed": 3}, {})["5"]["inputs"]["batch_size"] == api["5"]["inputs"]["batch_size"], (
        "张数不写进 batch_size")


def test_没有种子的图没有跑几遍_视频图也没有(graph) -> None:
    upscale = graph.describe("upscale.json", "upscale", UPSCALE_API, OBJECT_INFO)
    assert "num_images" not in upscale["parameters"], "放大跑几遍都是同一张"
    assert not graph.counts_runs(UPSCALE_API) and not graph.counts_runs(WAN_API)


def test_LoadImage_变成参考图槽位(graph, convert) -> None:
    model = _portrait(graph, convert)
    assert model["inputs"] == [{"role": "reference_image", "max": 1}], "有提示词和画布的图:参考图可给可不给"
    assert model["modes"] == ["text-to-image", "image-to-image"]
    assert model["prompt_dialect"] == "sd-tags"


def test_视频图_接到start_image的是首帧(graph) -> None:
    model = graph.describe("video/wan.json", "wan", WAN_API, OBJECT_INFO)
    assert model["kind"] == "video"
    assert model["inputs"] == [{"role": "first_frame", "max": 1, "required": True}], "图生视频:首帧必须给"
    assert model["modes"] == ["image-to-video"]
    assert model["parameters"]["size"]["default"] == "832x480", "WanImageToVideo 决定成片尺寸"
    assert model["parameters"]["20.length"]["default"] == 81


def test_首帧先过一道缩放再进图生视频节点_照样是首帧_而且必须给(graph) -> None:
    """DaSiWa WAN 2.2 i2v:First-Frame-Image → BatchResizeWithLanczos → WanImageToVideo.start_image。只看 LoadImage
    直接接到哪儿,它成了「参考图」,这张图生视频的工作流被说成文生视频 / 参考生视频;不给图也让跑,ComfyUI 就拿
    工作流里存着的 example.png 生成一段 —— 用户拿回来的不是自己的图动起来。"""
    info = {**OBJECT_INFO, "BatchResizeWithLanczos": {"input": {"required": {
        "image": ["IMAGE"], "width": ["INT", {"default": 1280}], "height": ["INT", {"default": 1280}]}}}}
    api = json.loads(json.dumps(WAN_API))
    api["13"] = {"class_type": "BatchResizeWithLanczos", "inputs": {"image": ["12", 0], "width": 1280, "height": 1280}}
    api["20"]["inputs"]["start_image"] = ["13", 0]
    model = graph.describe("dasiwa.json", "dasiwa", graph.live(api, info), info)
    assert model["inputs"] == [{"role": "first_frame", "max": 1, "required": True}]
    assert model["modes"] == ["image-to-video"]
    uploaded = graph.wire_inputs(api, "video", {"first_frame": ["mosael/start.png"]})
    assert uploaded["12"]["inputs"]["image"] == "mosael/start.png", "给的首帧接到那个 LoadImage 上"


def test_放大这类处理一张图的工作流_图必须给(graph) -> None:
    model = graph.describe("upscale.json", "upscale", UPSCALE_API, OBJECT_INFO)
    assert model["kind"] == "image"
    assert model["modes"] == ["image-to-image"], "没有提示词、没有画布:它不是文生图"
    assert model["inputs"] == [{"role": "reference_image", "max": 1, "required": True}]
    assert model["parameters"]["2.model_name"]["title"] == {"zh": "放大模型", "en": "Upscale model"}
    assert "upscale" in graph.features(UPSCALE_API)


# --- 只看 ComfyUI 真会跑的那部分图 ----------------------------------------------------


def test_没接到能跑的输出上的节点不算_局部重绘图没有假的尺寸张数和第二个产出(graph) -> None:
    """用户的 inpainting.json:第一遍文生图的 KSampler 静音了,它前面的 EmptyLatentImage 什么都不影响,后面的
    VAEDecode 缺了 samples、那个 PreviewImage 永远出不来。此前目录照它们说「尺寸 1280x1920、张数可调、一次交回 2 份」:
    选 2 张,batch_size 写进那个悬空的 EmptyLatentImage,只拿回 1 张;画板摆两格,一格永远空着。"""
    info = {**OBJECT_INFO, **INPAINT_NODE_INFO}
    api = graph.live(INPAINT_MUTED_FIRST_PASS_API, info)
    assert set(api) == {"4", "7", "13", "14", "15", "16", "21", "23", "24"}
    model = graph.describe("inpainting.json", "inpainting", api, info, {})
    assert "size" not in model["parameters"]
    assert model["parameters"]["num_images"]["x-count-unit"] == "runs", "没有画布、有种子:照样跑几遍"
    assert "x-batch" not in model["parameters"]["num_images"], "上游没有存着的批量:一遍几张判不出来,不报"
    assert model["outputs_per_run"] == 1 and "output_node" not in model["parameters"]
    assert "6.text" not in model["parameters"], "没接上的那句提示词不是一个可调的参数"
    assert model["inputs"] == [{"role": "reference_image", "max": 1, "required": True}, {"role": "mask", "max": 1}], (
        "没有自己的画布:图必须给,否则拿工作流里存着的那张跑"
    )
    assert model["modes"] == ["image-to-image"]


def test_只预览预处理结果的预览节点不是产出(graph) -> None:
    """用户的 beautiful girl:LoadImage → AIO_Preprocessor(OpenPose)→ PreviewImage,只是看一眼骨架;ControlNet 被旁路了,
    骨架图什么都不影响。此前它算一个产出:一次交回 4 份里有一张骨架图,参考图还成了一格输入。判据:一张会生成东西的图
    (有解码节点)里,上游一个解码节点都没经过的预览节点只是在看预处理 / 读进来的原图,不是产出;它的上游随之不在
    会跑的那部分图里。整张图都没有解码的(放大、抠图)预览照旧算。"""
    info = {**OBJECT_INFO, "AIO_Preprocessor": {"input": {"required": {
        "image": ["IMAGE"], "preprocessor": [["OpenposePreprocessor", "CannyEdgePreprocessor"]],
        "resolution": ["INT", {"default": 512}]}}, "output": ["IMAGE"]}}
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 7.5, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": 1.0, "model": ["4", 0],
                                                    "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1080, "height": 1920, "batch_size": 4}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "12": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
        "39": {"class_type": "AIO_Preprocessor", "inputs": {"image": ["41", 0], "preprocessor": "OpenposePreprocessor",
                                                             "resolution": 512}},
        "41": {"class_type": "LoadImage", "inputs": {"image": "pose.png"}},
        "42": {"class_type": "PreviewImage", "inputs": {"images": ["39", 0]}},
    }
    assert [one["node"] for one in graph.output_nodes(api, info)] == ["12"]
    kept = graph.live(api, info)
    assert not {"39", "41", "42"} & set(kept), "骨架那一路不跑"
    model = graph.describe("beautiful girl.json", "beautiful girl", kept, info)
    assert model["outputs_per_run"] == 4, "画布上存着一次 4 张:跑一遍交回 4 张"
    assert model["inputs"] == [] and model["modes"] == ["text-to-image"]
    assert [one["node"] for one in graph.output_nodes(UPSCALE_API, OBJECT_INFO)] == ["4", "5"], (
        "没有解码的图(放大):预览照旧是产出")


def test_没接到输出上的读图节点不是输入槽(graph) -> None:
    """DaSiWa WAN 2.2 里「Last-Frame-Image」那个 LoadImage 的下游全被旁路了:给它的图什么都不影响,不该是一格输入。"""
    api = {**WAN_API, "14": {"class_type": "LoadImage", "inputs": {"image": "last.png"}}}
    model = graph.describe("wan.json", "wan", graph.live(api, OBJECT_INFO), OBJECT_INFO)
    assert [one["role"] for one in model["inputs"]] == ["first_frame"]


def test_能跑的输出一个都没有_或者节点没装_原样交给ComfyUI去说(graph) -> None:
    """判不了的不替 ComfyUI 拿主意:输出全断了、或者用了这台机器没装的节点,原样提交,让 ComfyUI 说出缺什么。"""
    broken = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
              "8": {"class_type": "VAEDecode", "inputs": {"vae": ["4", 2]}},
              "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "x"}}}
    assert graph.live(broken, OBJECT_INFO) == broken
    missing = {**UPSCALE_API, "7": {"class_type": "CR Prompt Text", "inputs": {"prompt": "田园"}}}
    assert "7" in graph.live(missing, OBJECT_INFO)
    no_output = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "hi"}}}
    assert graph.live(no_output, OBJECT_INFO) == no_output
    assert graph.live(UPSCALE_API, {}) == UPSCALE_API, "没有节点定义时什么都判不了"


# --- 提示词要不要写:从图里读 -------------------------------------------------------


def test_放大这类图没有喂给采样器的文字_不收提示词(graph) -> None:
    """放大、抠图这类「处理一张图」的工作流:宿主不摆提示词框,也不逼人敲一句没用的话。"""
    assert graph.describe("upscale.json", "upscale", UPSCALE_API, OBJECT_INFO)["prompt"] == "none"
    assert graph.prompt_requirement(UPSCALE_API) == "none"


def test_没接上采样器的文字节点不算提示词(graph) -> None:
    """判的是**喂进采样器的**文字,不是图里有没有 CLIPTextEncode —— 一个没接上的文字节点什么都不影响。"""
    api = {**UPSCALE_API, "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "孤零零的一句"}}}
    assert graph.prompt_requirement(api) == "none"


def test_存着提示词的图_可以不写(graph, convert) -> None:
    """不写就用这张图自己那句,写了换成你的。"""
    assert _portrait(graph, convert)["prompt"] == "optional"
    assert graph.describe("video/wan.json", "wan", WAN_API, OBJECT_INFO)["prompt"] == "optional", "穿过视频节点的条件也认"
    flux = {
        "13": {"class_type": "SamplerCustomAdvanced", "inputs": {"guider": ["22", 0]}},
        "22": {"class_type": "BasicGuider", "inputs": {"conditioning": ["6", 0]}},
        "6": {"class_type": "CLIPTextEncodeFlux", "inputs": {"clip_l": "", "t5xxl": "a fox", "guidance": 3.5}},
    }
    assert graph.prompt_requirement(flux) == "optional", "Flux 那种一个节点几格字:有一格存着话就够"


def test_提示词节点存的是空串_或者模板里是占位符_要写(graph) -> None:
    empty = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "  "}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
    }
    assert graph.prompt_requirement(empty) == "required", "反向提示词存着话不算:它有自己的控件"
    template = {
        "3": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "positive": ["6", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}},
    }
    assert graph.describe("api-workflow", "t", template, OBJECT_INFO)["prompt"] == "required"


def test_蒙版_单独的蒙版节点和只接了alpha的LoadImage(graph) -> None:
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["20", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "p"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "n"}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "11": {"class_type": "LoadImageMask", "inputs": {"image": "m.png", "channel": "alpha"}},
        "12": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
        "20": {"class_type": "VAEEncodeForInpaint", "inputs": {"pixels": ["10", 0], "mask": ["11", 0], "grow_mask_by": 6}},
        "21": {"class_type": "SetLatentNoiseMask", "inputs": {"mask": ["12", 1]}},
    }
    slots = {slot["node"]: slot["role"] for slot in graph.slots(api, "image")}
    assert slots == {"10": "reference_image", "11": "mask", "12": "mask"}, "只用了 alpha 那一路的 LoadImage 是蒙版"
    model = graph.describe("inpaint.json", "inpaint", api, OBJECT_INFO)
    assert {"role": "mask", "max": 2, "required": True, "labels": [
        {"zh": "加载图像(作为蒙版) #11", "en": "LoadImageMask #11"}, {"zh": "加载图像 #12", "en": "LoadImage #12"},
    ]} in model["inputs"], "一个角色几个槽位:按槽位顺序带名字(没起名的是「节点名 #节点」)"
    assert model["modes"] == ["image-to-image"]
    assert "11.channel" not in model["parameters"], "读蒙版的节点是槽位,不是参数"
    assert "inpaint" in graph.features(api)


def test_视频输入是待编辑的视频_音频是驱动音频(graph) -> None:
    api = {
        "1": {"class_type": "LoadVideo", "inputs": {"file": "clip.mp4"}},
        "2": {"class_type": "LoadAudio", "inputs": {"audio": "voice.wav"}},
        "3": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0], "audio": ["2", 0]}},
    }
    slots = graph.slots(api, "video")
    assert [(slot["role"], slot["field"]) for slot in slots] == [("source_video", "file"), ("driving_audio", "audio")]
    model = graph.describe("v2v.json", "v2v", api, OBJECT_INFO)
    assert model["kind"] == "video" and model["modes"] == ["video-edit"]
    assert {"role": "source_video", "max": 1, "required": True} in model["inputs"]


def test_核心的_Advanced_保存节点也是成品_文生音乐是音频模型(graph) -> None:
    """维护者真实的「minimax+music3+文生音乐」:唯一的输出是 ComfyUI 0.39 核心的 SaveAudioAdvanced(选格式的保存节点)。
    此前它不在音频输出里,整张图被兜成图像模型、输出是 any。SaveImageAdvanced 同理。"""
    music = {
        "10": {"class_type": "EmptyMiniMaxMusic3LatentAudio", "inputs": {"seconds": 120.0, "batch_size": 1}},
        "56": {"class_type": "SaveAudioAdvanced", "inputs": {"audio": ["10", 0], "filename_prefix": "audio/ComfyUI",
                                                             "format": "flac"}},
    }
    assert graph.kind_of(music) == "audio"
    assert [(one["node"], one["media"]) for one in graph.output_nodes(music, OBJECT_INFO)] == [("56", "audio")]
    still = {
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "9": {"class_type": "SaveImageAdvanced", "inputs": {"images": ["5", 0], "filename_prefix": "x", "format": "webp"}},
    }
    assert graph.kind_of(still) == "image"
    assert [(one["node"], one["media"]) for one in graph.output_nodes(still, OBJECT_INFO)] == [("9", "image")]


def test_输出节点认object_info的output_node(graph) -> None:
    api = {
        "4": {"class_type": "SaveImage", "inputs": {}},
        "5": {"class_type": "ShowText|pysssss", "inputs": {}},
        "6": {"class_type": "SomeCustomSaver", "inputs": {}},
        "7": {"class_type": "VAEDecode", "inputs": {}},
    }
    info = {**OBJECT_INFO, "SomeCustomSaver": {"input": {}, "output_node": True}}
    found = [(one["node"], one["media"]) for one in graph.output_nodes(api, info)]
    assert found == [("4", "image"), ("5", "text"), ("6", "any")]


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


def test_提示词写在后端的一段文字节点上_连进CLIPTextEncode(graph) -> None:
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["30", 0], "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
        "30": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "a red fox"}},
    }
    assert graph.text_slots(api) == {("30", "value"): "prompt", ("7", "text"): "negative"}
    assert graph.prompt_requirement(api) == "optional"
    assert graph.fill(api, {"prompt": "a cat"}, {})["30"]["inputs"]["value"] == "a cat"
    assert "30.value" not in graph.tunable(api, {"PrimitiveStringMultiline": {"input": {"required": {
        "value": ["STRING", {"multiline": True}]}}}}), "提示词由宿主的主控件填,不再单列"


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
    wired = graph.wire_inputs(api, "image", {"reference_image": ["mosael/x.png"]})
    assert wired["10"]["inputs"]["image"] == "mosael/x.png"
    assert wired["11"]["inputs"]["image"] == "b.png", "给得比槽位少,剩下的用它原来那张"


def test_视频接到LoadVideo的file上(graph) -> None:
    api = {"1": {"class_type": "LoadVideo", "inputs": {"file": "clip.mp4"}},
           "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}}}
    assert graph.wire_inputs(api, "video", {"source_video": ["mosael/v.mp4"]})["1"]["inputs"]["file"] == "mosael/v.mp4"


def test_没有蒙版节点时_给的蒙版替掉LoadImage的alpha那一路(graph) -> None:
    api = {
        "10": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "20": {"class_type": "VAEEncodeForInpaint", "inputs": {"pixels": ["10", 0], "mask": ["10", 1]}},
    }
    wired = graph.wire_inputs(api, "image", {"reference_image": ["mosael/img.png"], "mask": ["mosael/m.png"]})
    new_id = wired["20"]["inputs"]["mask"][0]
    assert wired[new_id]["class_type"] == "LoadImageMask" and wired[new_id]["inputs"]["image"] == "mosael/m.png"
    assert wired["20"]["inputs"]["pixels"] == ["10", 0], "图那一路不动"
    assert wired["10"]["inputs"]["image"] == "mosael/img.png"


def test_给的蒙版按白色是要改的地方读_不读alpha(graph) -> None:
    """宿主的蒙版是「白色是要改的地方」的黑白图,没有透明通道:照 alpha 读出来是一张全空的蒙版,什么都不重绘。

    - LoadImageMask 读 alpha 的,改成读红色通道;
    - 只用了 alpha 那一路的 LoadImage(蒙版槽位),就地换成读红色通道的 LoadImageMask,下游改接它唯一的输出。
    """
    api = {
        "11": {"class_type": "LoadImageMask", "inputs": {"image": "m.png", "channel": "alpha"}},
        "12": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
        "20": {"class_type": "VAEEncodeForInpaint", "inputs": {"mask": ["11", 0]}},
        "21": {"class_type": "SetLatentNoiseMask", "inputs": {"mask": ["12", 1]}},
    }
    wired = graph.wire_inputs(api, "image", {"mask": ["mosael/a.png", "mosael/b.png"]})
    assert wired["11"]["inputs"] == {"image": "mosael/a.png", "channel": "red"}
    assert wired["12"]["class_type"] == "LoadImageMask"
    assert wired["12"]["inputs"] == {"image": "mosael/b.png", "channel": "red"}
    assert wired["21"]["inputs"]["mask"] == ["12", 0]
    assert graph.put_input(api, "11", "mosael/c.png")["11"]["inputs"]["channel"] == "red", "每张工作流自己的工具走同一条"


def test_按节点标题改值(graph) -> None:
    api = {"3": {"class_type": "KSampler", "inputs": {"steps": 20, "cfg": 7.0}}}
    assert graph.set_value(api, "采样.steps", 30, {"3": "采样"}) and api["3"]["inputs"]["steps"] == 30
    assert graph.set_value(api, "3.cfg", 5.5) and api["3"]["inputs"]["cfg"] == 5.5
    assert not graph.set_value(api, "没有这个节点.steps", 1, {"3": "采样"})


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
    assert [one["item"]["filename"] for one in graph.collect_outputs(entry, "image")] == ["a.png"]
    only_preview = {"outputs": {"12": {"images": [{"filename": "p.png", "type": "temp"}]}}}
    assert [one["item"]["filename"] for one in graph.collect_outputs(only_preview, "image")] == ["p.png"]


def test_全部产出_每个节点的每个文件和文字(graph) -> None:
    entry = {
        "prompt": [1, "p1", {"9": {"class_type": "SaveImage"}, "12": {"class_type": "PreviewImage"},
                             "30": {"class_type": "VHS_VideoCombine"}, "40": {"class_type": "ShowText|pysssss"}}, {}, []],
        "outputs": {
            "9": {"images": [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}]},
            "12": {"images": [{"filename": "p.png", "type": "temp"}]},
            "30": {"gifs": [{"filename": "v.mp4", "type": "output"}]},
            "40": {"text": ["a cat on a sofa"]},
        },
    }
    files, texts = graph.all_outputs(entry)
    assert [(one["node"], one["item"]["filename"], one["media"]) for one in files] == [
        ("9", "a.png", "image"), ("9", "b.png", "image"), ("30", "v.mp4", "video")]
    assert texts == [{"node": "40", "class_type": "ShowText|pysssss", "text": "a cat on a sofa"}]
    with_previews, _ = graph.all_outputs(entry, include_previews=True)
    assert "p.png" in [one["item"]["filename"] for one in with_previews]


def test_视频要的是合成的那一段_不是第一帧(graph) -> None:
    entry = {"outputs": {
        "8": {"images": [{"filename": "frame_00001.png", "type": "output"}]},
        "12": {"gifs": [{"filename": "out.mp4", "subfolder": "video", "type": "output"}]},
    }}
    assert [one["item"]["filename"] for one in graph.collect_outputs(entry, "video")] == ["out.mp4"]


def test_视频只在预览里_也不拿存下来的第一帧顶替(graph) -> None:
    """VHS 合成节点关了 save_output:视频是临时文件(type=temp),存下来的只有逐帧的图。
    要的是视频,就该交回那段临时的视频,而不是把第一帧当成「视频」交回去。"""
    entry = {"outputs": {
        "8": {"images": [{"filename": "frame_00001.png", "type": "output"}]},
        "12": {"gifs": [{"filename": "out.mp4", "subfolder": "", "type": "temp"}]},
    }}
    assert [one["item"]["filename"] for one in graph.collect_outputs(entry, "video")] == ["out.mp4"]


def test_校验错误和执行错误说得出是哪个节点(graph) -> None:
    detail = {"error": {"message": "Prompt outputs failed validation"},
              "node_errors": {"4": {"errors": [{"message": "Value not in list", "details": "ckpt_name: 'x' not in [...]"}]}}}
    said = graph.validation_errors(detail)
    assert "Prompt outputs failed validation" in said and "#4 Value not in list: ckpt_name" in said
    status = {"messages": [["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]]}
    assert graph.execution_error(status) == "KSampler: CUDA out of memory"


# --- 没有 ComfyUI 认得的采样器的视频图:提示词写在生成节点自己身上 -------------------------------
#
# 用户在视频格选了「video_minimax_h3_t2v.json」和「…MiniMax+H3-多参考生视频…」,面板说「这个模型不收提示词」:
# 此前只从 KSampler / 引导器的 positive、conditioning 往上追到 CLIPTextEncode 这一类(`text` / `clip_l` …),
# 而 API 节点(MiniMax、海螺、Kling、Veo…)没有采样器,提示词是节点自己的 `prompt_text` / `prompt`;MiniMax H3
# 的引导器追到的 MiniMaxH3ImageToVideo 把提示词放在 `prompt` 上;WanVideoWrapper 的采样器不在认得的那几个里。

VIDEO_INFO = {**OBJECT_INFO, **VIDEO_NODE_INFO}


def test_API节点的文生视频_提示词是它自己的prompt_text(graph) -> None:
    model = graph.describe("minimax_t2v.json", "t2v", MINIMAX_T2V_API, VIDEO_INFO)
    assert model["kind"] == "video" and model["modes"] == ["text-to-video"]
    assert model["prompt"] == "optional", "存着一句话:不写就用它,写了换成你的"
    assert "1.prompt_text" not in model["parameters"], "提示词由宿主的主控件填,不再单列成参数"
    assert model["parameters"]["seed"] == {"type": "integer", "minimum": 0}
    filled = graph.fill(MINIMAX_T2V_API, {"prompt": "a koi"}, {}, VIDEO_INFO)
    assert filled["1"]["inputs"]["prompt_text"] == "a koi"
    empty = {**MINIMAX_T2V_API, "1": {**MINIMAX_T2V_API["1"], "inputs": {**MINIMAX_T2V_API["1"]["inputs"], "prompt_text": ""}}}
    assert graph.prompt_requirement(empty, object_info=VIDEO_INFO) == "required"


def test_API节点的图生视频_接到image和first_frame_image上的是首帧(graph) -> None:
    for api in (MINIMAX_I2V_API, HAILUO_API):
        model = graph.describe("i2v.json", "i2v", api, VIDEO_INFO)
        assert model["inputs"] == [{"role": "first_frame", "max": 1, "required": True}], api["1"]["class_type"]
        assert model["modes"] == ["image-to-video"]
    assert graph.describe("hailuo.json", "h", HAILUO_API, VIDEO_INFO)["prompt"] == "required", "存的是空串:要写"
    assert graph.fill(HAILUO_API, {"prompt": "P"}, {}, VIDEO_INFO)["1"]["inputs"]["prompt_text"] == "P"


def test_正反两句在同一个节点上_各归各的(graph) -> None:
    """Kling、Veo 的 API 节点,WanVideoWrapper 的 WanVideoTextEncode:正向和反向提示词是同一个节点的两格。"""
    slots = graph.text_slots(KLING_I2V_API, VIDEO_INFO)
    assert slots == {("1", "prompt"): "prompt", ("1", "negative_prompt"): "negative"}
    model = graph.describe("kling.json", "kling", KLING_I2V_API, VIDEO_INFO)
    assert model["prompt"] == "optional" and "negative_prompt" in model["parameters"]
    assert model["inputs"] == [{"role": "first_frame", "max": 1, "required": True}], "Kling 的首帧叫 start_frame"
    assert not {"1.prompt", "1.negative_prompt"} & set(model["parameters"])
    filled = graph.fill(KLING_I2V_API, {"prompt": "P", "negative": "N"}, {}, VIDEO_INFO)
    assert (filled["1"]["inputs"]["prompt"], filled["1"]["inputs"]["negative_prompt"]) == ("P", "N")

    veo = graph.describe("veo.json", "veo", VEO_FLF_API, VIDEO_INFO)
    assert veo["modes"] == ["keyframes-to-video"]
    assert {(one["role"], one["max"]) for one in veo["inputs"]} == {("first_frame", 1), ("last_frame", 1)}
    assert veo["prompt"] == "optional"

    wan = graph.describe("wan_wrapper.json", "wan", WAN_WRAPPER_API, VIDEO_INFO)
    assert wan["prompt"] == "optional" and "negative_prompt" in wan["parameters"]
    assert wan["inputs"] == [{"role": "first_frame", "max": 1, "required": True}] and wan["modes"] == ["image-to-video"]
    filled = graph.fill(WAN_WRAPPER_API, {"prompt": "P", "negative": "N"}, {}, VIDEO_INFO)
    assert filled["11"]["inputs"] == {"positive_prompt": "P", "negative_prompt": "N"}


def test_不是多行文字的同名输入不当提示词(graph) -> None:
    """判的是 ComfyUI 说的输入类型(多行的 STRING),不只看名字:一格单行的 `prompt`(比如一个文件名前缀、一个 id)不是提示词。"""
    api = _api_video_with("1", "SomeVideoNode", {"prompt": "x_", "description": "y"})
    info = {**VIDEO_INFO, "SomeVideoNode": {"input": {"required": {"prompt": ["STRING", {"multiline": False}],
                                                                    "description": ["STRING", {"multiline": True}]}},
                                            "output": ["VIDEO"]}}
    assert graph.text_slots(api, info) == {}
    assert graph.prompt_requirement(api, object_info=info) == "none"


def _api_video_with(node: str, class_type: str, inputs: dict) -> dict:
    return {node: {"class_type": class_type, "inputs": inputs},
            "90": {"class_type": "SaveVideo", "inputs": {"video": [node, 0], "filename_prefix": "video/out"}}}


def test_MiniMax_H3_子图里的提示词_展开之后写进里面那个节点(graph, convert) -> None:
    api = convert.to_api(minimax_h3_ui(), VIDEO_INFO)
    assert api["105:104"]["inputs"]["prompt"] == "Realistic live-action cinematic look", "子图节点上提升出来的那一格"
    assert graph.text_slots(api, VIDEO_INFO) == {("105:104", "prompt"): "prompt"}
    model = graph.describe("video_minimax_h3_t2v.json", "h3", api, VIDEO_INFO, convert.titles_of(api))
    assert model["kind"] == "video" and model["prompt"] == "optional" and model["modes"] == ["text-to-video"]
    assert "105:104.prompt" not in model["parameters"]
    assert graph.fill(api, {"prompt": "a goldfish"}, {}, VIDEO_INFO)["105:104"]["inputs"]["prompt"] == "a goldfish"
    #: CreateVideo 只是把帧合成一段视频交下去,存下来的是 SaveVideo —— 一次交回一段,不是两段。
    assert [one["node"] for one in graph.output_nodes(api, VIDEO_INFO)] == ["92"]
    assert [one["node"] for one in graph.generation_nodes(api, "video", VIDEO_INFO)] == ["92"]

    framed = convert.to_api(minimax_h3_ui(frames=True), VIDEO_INFO)
    roles = {slot["node"]: slot["role"] for slot in graph.slots(framed, "video")}
    assert roles == {"201": "first_frame", "202": "last_frame"}, "外面接进子图首帧 / 尾帧口的图"
    assert graph.describe("h3_flf.json", "h3", framed, VIDEO_INFO)["modes"] == ["keyframes-to-video"]


def _with_promoted_unet(ui: dict) -> dict:
    """维护者那张 video_minimax_h3_t2v 的样子:UNET 也提升到了子图节点上,子图节点上选的是另一个文件(子图里那个
    UNETLoader 存着的还是模板默认的那个)。"""
    ui = json.loads(json.dumps(ui))
    instance = next(node for node in ui["nodes"] if node["id"] == 105)
    instance["inputs"].append({"name": "unet_name", "type": "COMBO", "widget": {"name": "unet_name"}, "link": None})
    instance["widgets_values"].append("minimaxH3INT8INT4_fl2vaINT8Pruned.safetensors")
    sub = ui["definitions"]["subgraphs"][0]
    sub["inputs"].append({"id": "i6", "name": "unet_name", "type": "COMBO", "linkIds": [221]})
    unet = next(node for node in sub["nodes"] if node["id"] == 6)
    unet["widgets_values"][0] = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    unet["inputs"][0]["link"] = 221
    sub["links"].append({"id": 221, "origin_id": -10, "origin_slot": 6, "target_id": 6, "target_slot": 0, "type": "COMBO"})
    return ui


def _compressed(ui: dict) -> dict:
    """前端导出时(graphToPrompt 的 workflow)做的 compressWidgetInputSlots:没连线、没起名的 widget 输入口从 `inputs` 里删掉,
    子图里的节点也一样;`widgets_values` 不动(ComfyUI 1.53.10 实测)。"""
    ui = json.loads(json.dumps(ui))
    keep = lambda entry: not ("widget" in entry and entry.get("link") is None and not entry.get("label"))  # noqa: E731
    for node in [*ui["nodes"], *(one for sub in ui["definitions"]["subgraphs"] for one in sub["nodes"])]:
        node["inputs"] = [entry for entry in node.get("inputs") or [] if keep(entry)]
    return ui


def test_子图节点的输入口被前端压掉之后_提升出来的值照样按名字取(convert) -> None:
    """沙盒实测(ComfyUI 前端 1.53.10):工作台导出画布上的 video_minimax_h3_t2v,子图节点的 `inputs` 只剩连了线、起了名的
    几格,`widgets_values` 还是九个值。此前按下标找输入口 —— 错位或者取不到,落回子图里 UNETLoader 存着的模板默认值:
    缺失项报的是没在用的 minimax_h3_fl2va_pruned_int8_convrot,真正选的那个反倒没列。"""
    saved = _with_promoted_unet(minimax_h3_ui())
    exported = _compressed(saved)
    assert [entry["name"] for entry in next(n for n in exported["nodes"] if n["id"] == 105)["inputs"]] == \
        ["first_frame", "last_frame"], "前提:压完只剩两个插口"
    for ui in (saved, exported):
        api = convert.to_api(ui, VIDEO_INFO)
        assert api["105:6"]["inputs"]["unet_name"] == "minimaxH3INT8INT4_fl2vaINT8Pruned.safetensors"
        assert api["105:104"]["inputs"]["prompt"] == "Realistic live-action cinematic look"
        assert (api["105:104"]["inputs"]["width"], api["105:104"]["inputs"]["height"]) == (1344, 768)
        assert api["105:15"]["inputs"]["noise_seed"] == 556589502035082


def test_多参考生视频_提示词写在连进来的文字节点上(graph) -> None:
    """「…MiniMax+H3-多参考生视频…」:提示词在一个自定义的 `Text` 节点上(ComfyUI 不认识它的类型,按名字认),
    连进 MiniMaxH3ReferenceToVideo 的 `prompt`。只存下来一个 VHS 合成(另一个关了 save_output)。"""
    api = MINIMAX_H3_REFERENCE_API
    assert graph.text_slots(api, VIDEO_INFO) == {("263", "text"): "prompt"}
    model = graph.describe("reference.json", "ref", api, VIDEO_INFO)
    assert model["prompt"] == "optional"
    #: 接在 `ref_*` 上的是参考:参考视频不是「要改的那段视频」(那是必给的),参考音频也不是驱动口型的音频
    #: (那要数字人授权)。有提示词:都可给可不给。
    assert model["inputs"] == [{"role": "reference_video", "max": 1}, {"role": "reference_audio", "max": 1},
                               {"role": "reference_image", "max": 1}]
    assert model["modes"] == ["text-to-video", "reference-to-video"]
    assert graph.fill(api, {"prompt": "P"}, {}, VIDEO_INFO)["263"]["inputs"]["text"] == "P"
    assert [one["node"] for one in graph.generation_nodes(api, "video", VIDEO_INFO)] == ["214"]


def test_认得的采样器那一路照旧_没接上的文字节点不算(graph) -> None:
    """往上游找只在采样器那一路什么都没找到时才找,也只找**接到产出节点上**的。"""
    api = {**MINIMAX_T2V_API, "50": {"class_type": "MinimaxTextToVideoNode", "inputs": {"prompt_text": "孤零零的一句"}}}
    assert graph.text_slots(api, VIDEO_INFO) == {("1", "prompt_text"): "prompt"}


# --- 跑一遍交回几张:这一种里交回的(都没存就是预览)节点,各按它收到的批量 ---------------------------------
#
# 用户在画板上选「1×」,落出来两三格:一次运行交回的是这一种**全部**存下来的文件,而工作流里常常不止一个保存节点
# (原图 + 放大、几个预览)。插件在目录里照实说跑一遍交回几张(`outputs_per_run`:每个节点收到的批量加起来),多个
# 保存节点时给一项「结果取自」(`output_node`):选其中一个,一遍就只交回它那一批。宿主再乘上跑几遍。


def test_一次交回几份_按这一种的保存节点数(graph, convert) -> None:
    assert _portrait(graph, convert)["outputs_per_run"] == 1
    upscale = graph.describe("upscale.json", "upscale", UPSCALE_API, OBJECT_INFO)
    assert upscale["outputs_per_run"] == 1, "保存 + 看一眼原图的预览:预览不交回"
    assert "output_node" not in upscale["parameters"], "只有一个保存节点:没得选"
    two = graph.describe("two.json", "two", TWO_SAVES_API, OBJECT_INFO, {"9": "原图", "12": "高清"})
    assert two["outputs_per_run"] == 4 and two["max_outputs"] == 16, "两个节点 × 批量 2,最多跑 4 遍"
    previews = graph.describe("previews.json", "p", PREVIEWS_ONLY_API, OBJECT_INFO)
    assert previews["outputs_per_run"] == 3, "一个保存节点都没有:交回的是那三个预览"
    videos = graph.describe("two_videos.json", "v", TWO_VIDEOS_API, OBJECT_INFO, {"30": "原速", "31": "补帧"})
    assert videos["kind"] == "video" and videos["outputs_per_run"] == 2 and videos["max_outputs"] == 2
    assert "num_images" not in videos["parameters"], "视频图没有张数"


def test_多个保存节点时_结果取自列出每一个(graph) -> None:
    two = graph.describe("two.json", "two", TWO_SAVES_API, OBJECT_INFO, {"9": "原图", "12": "高清"})
    choice = two["parameters"]["output_node"]
    assert choice["type"] == "string" and choice["title"] == {"zh": "结果取自", "en": "Results from"}
    assert choice["enum"] == ["all", "9", "12"] and choice["default"] == "all"
    assert choice["x-enum-labels"] == {"all": {"zh": "全部(2 个保存节点)", "en": "All (2 save nodes)"},
                                       "9": "原图", "12": "高清"}
    assert choice["x-outputs-per-run"] == {"all": 4, "9": 2, "12": 2}, "每一项跑一遍交回几张:各自的批量"
    assert "x-advanced" not in choice, "在「参数」里一眼看得到"
    #: 节点没改标题(都叫「预览图像」):带上节点号才分得清。
    labels = graph.describe("previews.json", "p", PREVIEWS_ONLY_API, OBJECT_INFO)["parameters"]["output_node"]["x-enum-labels"]
    assert labels == {"all": {"zh": "全部(3 个预览节点)", "en": "All (3 preview nodes)"},
                      **{node: {"zh": f"预览图像 #{node}", "en": f"PreviewImage #{node}"} for node in ("13", "17", "18")}}


def test_收产出时只要选中的那个节点的(graph) -> None:
    entry = {"outputs": {
        "9": {"images": [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}]},
        "12": {"images": [{"filename": "hd.png", "type": "output"}]},
    }}
    assert [one["item"]["filename"] for one in graph.collect_outputs(entry, "image")] == ["a.png", "b.png", "hd.png"]
    assert [one["item"]["filename"] for one in graph.collect_outputs(entry, "image", nodes={"12"})] == ["hd.png"]
    assert graph.collect_outputs(entry, "image", nodes={"99"}) == [], "选中的节点什么都没交出:不拿别的顶替"


def test_只要一个节点时_别的保存节点不跑(graph) -> None:
    assert graph.chosen_outputs(TWO_SAVES_API, "image", "12", OBJECT_INFO) == {"12"}
    kept = graph.keep_outputs(TWO_SAVES_API, "image", {"12"}, OBJECT_INFO)
    assert "9" not in kept and {"11", "12"} <= set(kept), "原图那个保存节点摘掉;放大那一路照跑"
    assert "9" in TWO_SAVES_API, "不改入参"
    with pytest.raises(Exception, match="结果取自"):
        graph.chosen_outputs(TWO_SAVES_API, "image", "99", OBJECT_INFO)
    assert graph.chosen_outputs(TWO_SAVES_API, "image", "all", OBJECT_INFO) is None
    assert graph.chosen_outputs(TWO_SAVES_API, "image", "", OBJECT_INFO) is None, "两个保存节点:缺省照旧是全部"


# --- 缺省的「结果取自」是最终结果:中间一步的预览不交回 -----------------------------------------
#
# 维护者在 AI 工作台选了「古风女孩1」,张数 1,出来三张,一张几乎全黑(1.9.1)。那张工作流只接了预览节点:第一遍的图、
# 从它算出来的手部深度图(MeshGraphormer,没认出手时整张是黑的)、拿深度图控制的第二遍。三个都过了 1.7.0 的「上游有
# 解码」,缺省「全部」于是三张都交回。用户说「结果」指的是最后那一张:**一个预览显示的东西被接着做下去、成了另一个
# 输出的图,它就是那一个的中间一步**;ControlNet 的控制图、蒙版是**辅助图**,从不当结果。缺省都不交回。只看连线和
# 节点定义(类别、插口类型),不看节点标题。


def _hand_depth(graph, convert):
    ui, info = fixture_workflow(TWO_PASS_HAND_DEPTH)
    object_info = {**OBJECT_INFO, **info}
    api = graph.live(convert.to_api(ui, object_info), object_info)
    return api, object_info, convert.titles_of(api)


def test_古风女孩1_缺省只交回最终结果(graph, convert) -> None:
    api, info, titles = _hand_depth(graph, convert)
    assert [node["node"] for node in graph.generation_nodes(api, "image", info, titles)] == ["8", "17", "18"]
    model = graph.describe("古风女孩1.json", "古风女孩1", api, info, titles)
    assert model["outputs_per_run"] == 4, "跑一遍交回最终结果那一批:画布上存着一次 4 张"
    assert model["max_outputs"] == 48, "选「全部」时三个节点各 4 张 × 最多跑 4 遍"
    assert model["parameters"]["num_images"]["x-batch"] == 4
    choice = model["parameters"]["output_node"]
    assert choice["default"] == "final" and choice["enum"] == ["final", "all", "8", "17", "18"]
    assert choice["x-enum-labels"] == {
        "final": {"zh": "最终结果(预览图像 #17)", "en": "Final result (Preview Image #17)"},
        "all": {"zh": "全部(3 个预览节点)", "en": "All (3 preview nodes)"},
        "8": {"zh": "预览图像 #8(中间一步)", "en": "Preview Image #8 (intermediate)"},
        "17": {"zh": "预览图像 #17", "en": "Preview Image #17"},
        "18": {"zh": "预览图像 #18(控制图)", "en": "Preview Image #18 (control image)"},
    }
    assert choice["x-outputs-per-run"] == {"final": 4, "all": 12, "8": 4, "17": 4, "18": 4}
    assert "不是最终结果" in choice["description"]["zh"]
    assert graph.auxiliary_view(api, "18", info) == "control", "MeshGraphormer 是 ControlNet 预处理器:那张黑图是控制图"


def test_古风女孩1_没选和选了最终结果一样_全部照旧三张(graph, convert) -> None:
    """宿主只发用户动过的参数:没带「结果取自」和选了缺省是同一件事,跑的时候按同一个判据再判一遍。"""
    api, info, titles = _hand_depth(graph, convert)
    assert graph.chosen_outputs(api, "image", "", info, titles) == {"17"}
    assert graph.chosen_outputs(api, "image", "final", info, titles) == {"17"}
    assert graph.chosen_outputs(api, "image", "all", info, titles) is None, "明说「全部」:三个都交回"
    assert graph.chosen_outputs(api, "image", "18", info, titles) == {"18"}, "要看深度图也挑得到"
    kept = graph.keep_outputs(api, "image", {"17"}, info, titles)
    assert not {"8", "18"} & set(kept), "中间一步的预览不跑"
    assert {"6", "10", "11", "14", "16", "17"} <= set(kept), "它们的上游照样为最终结果跑"


def _txt2img(**extra) -> dict:
    """第一遍文生图:checkpoint → KSampler #5 → VAEDecode #6 → PreviewImage #7。"""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": 1.0, "model": ["1", 0],
                                                    "positive": ["2", 0], "negative": ["3", 0],
                                                    "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
        **extra,
    }


def _second_pass(latent: list, *, model: list | None = None, positive: list | None = None,
                 negative: list | None = None, output: str = "PreviewImage") -> dict:
    """第二遍:KSampler #21 → VAEDecode #22 → #23(缺省也是预览)。"""
    return {
        "21": {"class_type": "KSampler", "inputs": {"seed": 2, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                                                     "scheduler": "normal", "denoise": 0.5,
                                                     "model": model or ["1", 0], "positive": positive or ["2", 0],
                                                     "negative": negative or ["3", 0], "latent_image": latent}},
        "22": {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["1", 2]}},
        "23": {"class_type": output, "inputs": {"images": ["22", 0]}},
    }


#: 判辅助图要的那几类节点定义(形状照真实的 /object_info):蒙版画成图的 MaskToImage、comfyui_controlnet_aux 的预处理器。
AUX_INFO = {
    "MaskToImage": {"input": {"required": {"mask": ["MASK"]}}, "output": ["IMAGE"], "category": "image/mask"},
    "DepthAnythingPreprocessor": {"input": {"required": {"image": ["IMAGE"]}}, "output": ["IMAGE"],
                                  "category": "ControlNet Preprocessors/Normal and Depth Estimators"},
}


def _finals(graph, api: dict, info: dict | None = None) -> list[str]:
    return [node["node"] for node in graph.final_outputs(api, graph.generation_nodes(api, "image"), info)]


def test_两遍出图_第一遍是中间一步(graph) -> None:
    """潜空间放大(第二遍接着用第一遍的潜空间,第一遍的图只是解码出来看一眼)、像素放大后重绘(VAEEncode 回去再采样)、
    拿第一遍的图当 IP-Adapter 参考再出一张:第一遍都是中间一步。"""
    latent = _txt2img(**{"10": {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["5", 0], "scale_by": 1.5,
                                                                            "upscale_method": "nearest-exact"}}},
                      **_second_pass(["10", 0]))
    assert _finals(graph, latent) == ["23"]
    pixels = _txt2img(**{"10": {"class_type": "ImageScaleBy", "inputs": {"image": ["6", 0], "scale_by": 1.5,
                                                                         "upscale_method": "lanczos"}},
                         "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["1", 2]}}},
                      **_second_pass(["11", 0]))
    assert _finals(graph, pixels) == ["23"]
    ip_adapter = _txt2img(**{"10": {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["1", 0],
                                                                                       "preset": "PLUS"}},
                             "11": {"class_type": "IPAdapter", "inputs": {"model": ["10", 0], "ipadapter": ["10", 1],
                                                                          "image": ["6", 0], "weight": 1.0}}},
                          **_second_pass(["4", 0], model=["11", 0]))
    assert _finals(graph, ip_adapter) == ["23"]


def test_ControlNet的控制图_不论接的是读进来的图还是第一遍的图_都不是结果(graph) -> None:
    """控制图从第一遍的图里算出来(上游有解码,1.7.0 的规矩拦不住):它接着控制了第二遍,是中间一步。
    从读进来的图算出来的控制图照旧在 1.7.0 那一步就不算输出。"""
    from_first = _txt2img(**{
        "10": {"class_type": "DepthAnythingPreprocessor", "inputs": {"image": ["6", 0], "resolution": 512}},
        "11": {"class_type": "PreviewImage", "inputs": {"images": ["10", 0]}},
        "12": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "depth.safetensors"}},
        "13": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["2", 0], "negative": ["3", 0],
                                                                   "control_net": ["12", 0], "image": ["10", 0],
                                                                   "strength": 1.0, "start_percent": 0.0,
                                                                   "end_percent": 1.0}},
    }, **_second_pass(["4", 0], positive=["13", 0], negative=["13", 1]))
    assert _finals(graph, from_first) == ["23"]
    from_loaded = _txt2img(**{
        "10": {"class_type": "LoadImage", "inputs": {"image": "pose.png"}},
        "11": {"class_type": "OpenposePreprocessor", "inputs": {"image": ["10", 0]}},
        "12": {"class_type": "PreviewImage", "inputs": {"images": ["11", 0]}},
    })
    assert [node["node"] for node in graph.generation_nodes(from_loaded, "image")] == ["7"]


def test_修脸和放大_之前那张是中间一步(graph) -> None:
    """图到图的加工也是「接着做下去」:修脸(FaceDetailer)、放大模型之前的那张是中间一步,缺省只交回加工完的那张。
    (维护者 ComfyUI 上的「beautiful girl」:原图 → 修脸 → 放大,三个预览;「controlnet」:原图 → 修脸,两个预览。)"""
    chain = _txt2img(**{
        "10": {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": "bbox/face_yolov8m.pt"}},
        "11": {"class_type": "FaceDetailer", "inputs": {"image": ["6", 0], "model": ["1", 0], "clip": ["1", 1],
                                                        "vae": ["1", 2], "positive": ["2", 0], "negative": ["3", 0],
                                                        "bbox_detector": ["10", 0], "seed": 3, "denoise": 0.5}},
        "12": {"class_type": "PreviewImage", "inputs": {"images": ["11", 0]}},
        "13": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "14": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": ["11", 0]}},
        "15": {"class_type": "PreviewImage", "inputs": {"images": ["14", 0]}},
    })
    assert _finals(graph, chain) == ["15"]
    detailed = {key: value for key, value in chain.items() if key not in ("13", "14", "15")}
    assert _finals(graph, detailed) == ["12"]


def test_从成图里算出来拿去看的蒙版和控制图_是辅助图_成图照样是结果(graph) -> None:
    """往下没接着做、只是从成图里抠一张蒙版或算一张深度图拿去看:它们是辅助图,不当结果,也不让成图变成「中间一步」。
    (只比「上游是不是子集」的话,成图会被当成蒙版那一张的中间一步,缺省成了一张蒙版。)"""
    masked = _txt2img(**{
        "10": {"class_type": "GroundingDinoSAMSegment (segment anything)", "inputs": {"image": ["6", 0],
                                                                                     "prompt": "cat"}},
        "11": {"class_type": "MaskToImage", "inputs": {"mask": ["10", 1]}},
        "12": {"class_type": "PreviewImage", "inputs": {"images": ["11", 0]}},
    })
    assert graph.auxiliary_view(masked, "12", AUX_INFO) == "mask"
    assert _finals(graph, masked, AUX_INFO) == ["7"]
    assert graph.chosen_outputs(masked, "image", "", AUX_INFO) == {"7"}
    depth = _txt2img(**{
        "10": {"class_type": "DepthAnythingPreprocessor", "inputs": {"image": ["6", 0], "resolution": 512}},
        "11": {"class_type": "PreviewImage", "inputs": {"images": ["10", 0]}},
    })
    assert graph.auxiliary_view(depth, "11", AUX_INFO) == "control"
    assert _finals(graph, depth, AUX_INFO) == ["7"]
    labels = graph.describe("depth.json", "d", depth, {**OBJECT_INFO, **AUX_INFO})["parameters"]["output_node"]["x-enum-labels"]
    assert labels["final"] == {"zh": "最终结果(预览图像 #7)", "en": "Final result (PreviewImage #7)"}
    assert labels["11"] == {"zh": "预览图像 #11(控制图)", "en": "PreviewImage #11 (control image)"}


def test_整张图没有解码节点的不挑(graph) -> None:
    """放大、预处理这类工具图(没有解码节点)和 1.7.0 的规矩同一条线:不判,几个预览照旧都是结果。"""
    tool = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "photo.png"}},
        "2": {"class_type": "DepthAnythingPreprocessor", "inputs": {"image": ["1", 0], "resolution": 512}},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
        "4": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "5": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["4", 0], "image": ["1", 0]}},
        "6": {"class_type": "PreviewImage", "inputs": {"images": ["5", 0]}},
    }
    assert _finals(graph, tool, AUX_INFO) == ["3", "6"]


def test_同一份潜空间解码两次_互不相干的两路_都是结果(graph) -> None:
    twice = _txt2img(**{
        "10": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["5", 0], "vae": ["1", 2], "tile_size": 512}},
        "11": {"class_type": "PreviewImage", "inputs": {"images": ["10", 0]}},
    })
    assert _finals(graph, twice) == ["7", "11"], "看的是同一遍的结果:谁也不是谁的中间一步"
    apart = _txt2img(**_second_pass(["4", 0], positive=["3", 0], negative=["2", 0]))
    assert _finals(graph, apart) == ["7", "23"], "两句提示词各出一张:共用模型和画布不算接着生成"


def test_几路都有中间一步时_最终结果是几个(graph) -> None:
    """两路各自两遍出图:缺省交回两路各自的最后一张。"""
    api = _txt2img(**{"10": {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["5", 0], "scale_by": 1.5,
                                                                         "upscale_method": "nearest-exact"}}},
                   **_second_pass(["10", 0]))
    api.update({
        "30": {"class_type": "KSampler", "inputs": {**api["5"]["inputs"], "positive": ["3", 0], "negative": ["2", 0]}},
        "31": {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0], "vae": ["1", 2]}},
        "32": {"class_type": "PreviewImage", "inputs": {"images": ["31", 0]}},
        "33": {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["30", 0], "scale_by": 1.5,
                                                           "upscale_method": "nearest-exact"}},
        "34": {"class_type": "KSampler", "inputs": {**api["21"]["inputs"], "latent_image": ["33", 0]}},
        "35": {"class_type": "VAEDecode", "inputs": {"samples": ["34", 0], "vae": ["1", 2]}},
        "36": {"class_type": "PreviewImage", "inputs": {"images": ["35", 0]}},
    })
    assert _finals(graph, api) == ["23", "36"]
    model = graph.describe("two.json", "two", api, OBJECT_INFO)
    choice = model["parameters"]["output_node"]
    assert choice["default"] == "final" and model["outputs_per_run"] == 2
    assert choice["x-enum-labels"]["final"] == {"zh": "最终结果(2 个预览节点)", "en": "Final results (2 preview nodes)"}
    assert choice["x-outputs-per-run"]["final"] == 2 and choice["x-outputs-per-run"]["all"] == 4


def test_保存节点不挑_存下来的照旧压过预览(graph) -> None:
    """保存节点是工作流作者明说要存的:第一遍也存着的照样交回(缺省「全部」)。存了第一遍、只预览第二遍的,交回的是
    存下来的那张(1.6.0 起的规矩,不因为第二遍在下游就改)。"""
    saved_twice = _txt2img(**{"10": {"class_type": "LatentUpscaleBy", "inputs": {"samples": ["5", 0], "scale_by": 1.5,
                                                                                 "upscale_method": "nearest-exact"}}},
                           **_second_pass(["10", 0], output="SaveImage"))
    saved_twice["7"] = {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "base"}}
    model = graph.describe("saved.json", "saved", saved_twice, OBJECT_INFO)
    assert model["outputs_per_run"] == 2
    assert model["parameters"]["output_node"]["default"] == "all"
    assert "final" not in model["parameters"]["output_node"]["enum"]
    first_saved = {**saved_twice, "23": {"class_type": "PreviewImage", "inputs": {"images": ["22", 0]}}}
    assert [node["node"] for node in graph.generation_nodes(first_saved, "image")] == ["7"]
    assert graph.describe("first.json", "first", first_saved, OBJECT_INFO)["outputs_per_run"] == 1


def test_三个预览看的是同一张图_照旧全部(graph) -> None:
    assert _finals(graph, PREVIEWS_ONLY_API) == ["13", "17", "18"]
    choice = graph.describe("previews.json", "p", PREVIEWS_ONLY_API, OBJECT_INFO)["parameters"]["output_node"]
    assert choice["default"] == "all" and "final" not in choice["enum"]


def test_选模型文件的参数写明是哪个模型目录的文件(graph) -> None:
    """生成表单要按它从模型库取缩略图、底模和触发词(ADR 0034 后续):大模型、LoRA、VAE……各是哪个目录,
    同名输入按节点分(CLIPLoader 的 clip_name 是文本编码器,CLIPVisionLoader 的是 clip_vision)。"""
    api = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}},
        "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "l.safetensors", "strength_model": 1.0,
                                                     "strength_clip": 1.0, "model": ["1", 0], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t.safetensors", "type": "wan"}},
        "4": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "v.safetensors"}},
        "5": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x.pth"}},
        "6": {"class_type": "KSampler", "inputs": {"sampler_name": "euler"}},
    }
    info = {
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["a.safetensors"]]}}},
        "LoraLoader": {"input": {"required": {"lora_name": [["l.safetensors"]], "strength_model": ["FLOAT", {}],
                                              "strength_clip": ["FLOAT", {}], "model": ["MODEL"], "clip": ["CLIP"]}}},
        "CLIPLoader": {"input": {"required": {"clip_name": [["t.safetensors"]], "type": [["wan", "sd3"]]}}},
        "CLIPVisionLoader": {"input": {"required": {"clip_name": [["v.safetensors"]]}}},
        "UpscaleModelLoader": {"input": {"required": {"model_name": [["4x.pth"]]}}},
        "KSampler": {"input": {"required": {"sampler_name": [["euler", "dpmpp_2m"]]}}},
    }
    folders = {key: spec.get("x-model-folder") for key, spec in graph.tunable(api, info).items()}
    assert folders["1.ckpt_name"] == "checkpoints"
    assert folders["2.lora_name"] == "loras"
    assert folders["3.clip_name"] == "text_encoders"
    assert folders["4.clip_name"] == "clip_vision"
    assert folders["5.model_name"] == "upscale_models"
    assert folders["6.sampler_name"] is None, "不是模型文件的下拉不写"
    assert folders["3.type"] is None
