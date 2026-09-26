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

from tests.fake_comfyui import OBJECT_INFO, PORTRAIT_UI, UPSCALE_API, WAN_API, conn, widget

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
    assert parameters["size"]["default"] == "832x1216" and parameters["size"]["enum"][0] == "832x1216"
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
    assert parameters["8.steps"]["title"] == {"zh": "步数 · 第 2 个 KSampler", "en": "Steps · KSampler #2"}
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


def test_一次几张对到宿主的num_images(graph, convert) -> None:
    model = _portrait(graph, convert)
    assert model["parameters"]["num_images"] == {"type": "integer", "minimum": 1, "maximum": 4, "default": 1}
    assert model["max_outputs"] == 4
    api = convert.to_api(PORTRAIT_UI, OBJECT_INFO)
    assert graph.fill(api, {"batch": 3}, {})["5"]["inputs"]["batch_size"] == 3
    assert graph.fill(api, {"batch": 99}, {})["5"]["inputs"]["batch_size"] == 4, "不超过宿主一次的上限"


def test_LoadImage_变成参考图槽位(graph, convert) -> None:
    model = _portrait(graph, convert)
    assert model["inputs"] == [{"role": "reference_image", "max": 1}], "有提示词和画布的图:参考图可给可不给"
    assert model["modes"] == ["text-to-image", "image-to-image"]
    assert model["prompt_dialect"] == "sd-tags"


def test_视频图_接到start_image的是首帧(graph) -> None:
    model = graph.describe("video/wan.json", "wan", WAN_API, OBJECT_INFO)
    assert model["kind"] == "video"
    assert model["inputs"] == [{"role": "first_frame", "max": 1}]
    assert model["modes"] == ["image-to-video"]
    assert model["parameters"]["size"]["default"] == "832x480", "WanImageToVideo 决定成片尺寸"
    assert model["parameters"]["20.length"]["default"] == 81


def test_放大这类处理一张图的工作流_图必须给(graph) -> None:
    model = graph.describe("upscale.json", "upscale", UPSCALE_API, OBJECT_INFO)
    assert model["kind"] == "image"
    assert model["modes"] == ["image-to-image"], "没有提示词、没有画布:它不是文生图"
    assert model["inputs"] == [{"role": "reference_image", "max": 1, "required": True}]
    assert model["parameters"]["2.model_name"]["title"] == {"zh": "放大模型", "en": "Upscale model"}
    assert "upscale" in graph.features(UPSCALE_API)


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
    assert {"role": "mask", "max": 2, "required": True} in model["inputs"]
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
    assert graph.text_roles(api) == {"30": "prompt", "7": "negative"}
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
    assert [item["filename"] for item in graph.collect_outputs(entry, "image")] == ["a.png"]
    only_preview = {"outputs": {"12": {"images": [{"filename": "p.png", "type": "temp"}]}}}
    assert [item["filename"] for item in graph.collect_outputs(only_preview, "image")] == ["p.png"]


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
    assert [item["filename"] for item in graph.collect_outputs(entry, "video")] == ["out.mp4"]


def test_视频只在预览里_也不拿存下来的第一帧顶替(graph) -> None:
    """VHS 合成节点关了 save_output:视频是临时文件(type=temp),存下来的只有逐帧的图。
    要的是视频,就该交回那段临时的视频,而不是把第一帧当成「视频」交回去。"""
    entry = {"outputs": {
        "8": {"images": [{"filename": "frame_00001.png", "type": "output"}]},
        "12": {"gifs": [{"filename": "out.mp4", "subfolder": "", "type": "temp"}]},
    }}
    assert [item["filename"] for item in graph.collect_outputs(entry, "video")] == ["out.mp4"]


def test_校验错误和执行错误说得出是哪个节点(graph) -> None:
    detail = {"error": {"message": "Prompt outputs failed validation"},
              "node_errors": {"4": {"errors": [{"message": "Value not in list", "details": "ckpt_name: 'x' not in [...]"}]}}}
    said = graph.validation_errors(detail)
    assert "Prompt outputs failed validation" in said and "#4 Value not in list: ckpt_name" in said
    status = {"messages": [["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]]}
    assert graph.execution_error(status) == "KSampler: CUDA out of memory"
