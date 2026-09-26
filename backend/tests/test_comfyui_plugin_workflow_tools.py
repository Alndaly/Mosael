"""ComfyUI 插件:**每张工作流一个工具**(`op: tools`,见 plugins/bundled/comfyui/tools/tooling.py)。

用户看到 `run_workflow` 的表单问:「参数是写死的吗?每个工作流应该参数是不同的吧」。是的 —— 所以插件在运行时
把每张工作流报成一个工具,入参从那张图里推:它自己的提示词、它自己读素材的节点、它自己能调的参数、它自己的
输出节点。后来又问:「它连要跑哪张工作流都不知道,却要人填参数」—— 通用的 `run_workflow` 于是删了,它能跑的
每一种图(内置文生图也算)都有自己的工具。这里对着假的 ComfyUI 钉住:

- 工具名稳:有 UUID 的图用 UUID(改名、挪目录都不变),没有的退到路径哈希,模板是 `wf_api_template`,
  内置文生图是 `wf_builtin_txt2img`;
- 入参:提示词 / 素材(带种类)/ 参数(人话名字、范围、可选值、高级)/ 种子尺寸张数(高级),必填的是真必须的;
- 输出按输出节点声明;`replaces` 说清楚老的 `run_workflow` 怎么改写过来(`values` 按节点 id 和按节点标题的都认);
- 跑起来:表单里的字符串按声明的类型转回来、素材接到对应节点、每个输出节点的第一份记成具名输出。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import PNG, PORTRAIT_ID, UPSCALE_API, FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
PORTRAIT_TOOL = "wf_" + PORTRAIT_ID.replace("-", "")[:12]
UPSCALE_TOOL = "wf_" + hashlib.sha1(b"upscale.json").hexdigest()[:12]


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        server.state.workflows["upscale.json"] = UPSCALE_API
        yield server


def _tools(url: str, data_dir: Path, **env: str) -> dict[str, dict[str, Any]]:
    output = runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "tools"},
                                  {"SERVER_URL": url, **env}, data_dir=data_dir, timeout=60).output
    assert output["fingerprint"]
    return {tool["name"]: tool for tool in output["tools"]}


def test_每张工作流一个工具_名字稳(comfy, tmp_path: Path) -> None:
    template = '{"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}}}'
    tools = _tools(comfy.url, tmp_path, API_WORKFLOW=template)
    assert set(tools) == {PORTRAIT_TOOL, UPSCALE_TOOL, "wf_api_template", "wf_builtin_txt2img",
                          "wf_" + hashlib.sha1(b"video/wan.json").hexdigest()[:12]}, "通用的 run_workflow 能跑的每一种图都有工具"
    assert tools[PORTRAIT_TOOL]["label"] == {"zh": "工作流 · portrait", "en": "Workflow · portrait"}
    assert tools[PORTRAIT_TOOL]["stream"] is True and tools[PORTRAIT_TOOL]["recommended"] is True
    # 在 ComfyUI 里改了名、挪了目录:图里的 id 没变,工具名就不变 —— 工作流节点和智能体记着的名字不失效
    comfy.state.workflows["people/人像.json"] = comfy.state.workflows.pop("portrait.json")
    renamed = _tools(comfy.url, tmp_path)
    assert PORTRAIT_TOOL in renamed and renamed[PORTRAIT_TOOL]["label"]["zh"] == "工作流 · people/人像"


def test_几张图撞了同一个id_都退到路径哈希_不抢名字(comfy, tmp_path: Path) -> None:
    """在 ComfyUI 外面拷了一份 portrait.json:按路径排在前面的副本不能抢走原来那张的工具名 ——
    否则存着的工作流节点从此悄悄跑的是副本。全零的 UUID(老版本前端的占位)也不算 id。"""
    comfy.state.workflows["a 副本.json"] = comfy.state.workflows["portrait.json"]
    comfy.state.workflows["zero.json"] = {**comfy.state.workflows["portrait.json"],
                                          "id": "00000000-0000-0000-0000-000000000000"}
    tools = _tools(comfy.url, tmp_path)
    assert PORTRAIT_TOOL not in tools
    for path in ("portrait.json", "a 副本.json", "zero.json"):
        assert "wf_" + hashlib.sha1(path.encode()).hexdigest()[:12] in tools, path


def test_入参从这张图里推(comfy, tmp_path: Path) -> None:
    tool = _tools(comfy.url, tmp_path)[PORTRAIT_TOOL]
    schema = tool["input_schema"]
    properties = schema["properties"]
    assert list(properties)[:2] == ["prompt", "image_10"], "提示词和素材在最前"
    assert properties["image_10"]["format"] == "asset" and properties["image_10"]["x-media"] == "image"
    assert properties["negative_prompt"]["x-advanced"] is True
    assert properties["steps_3"]["title"] == {"zh": "步数", "en": "Steps"} and properties["steps_3"]["default"] == 20
    assert properties["ckpt_name_4"]["enum"] == ["sd_xl_base.safetensors", "v1-5.ckpt"]
    assert "filename_prefix_9" not in properties and "text_6" not in properties and "seed_3" not in properties
    for advanced in ("seed", "width", "height", "num_images", "include_previews"):
        assert properties[advanced]["x-advanced"] is True, advanced
    assert properties["width"]["default"] == 832
    assert schema["required"] == [], "有提示词、有画布:参考图可给可不给"
    node = tool["node"]
    assert node["outputs"][0] == "image_9" and node["output_types"]["image_9"] == "asset"
    assert node["output_labels"]["image_9"] == {"zh": "图 · SaveImage", "en": "Image · SaveImage"}
    assert {"asset_id", "asset_ids", "texts", "summary"} <= set(node["outputs"])
    generic, by_path = tool["replaces"]
    rename = generic["rename"]
    assert generic["tool"] == "run_workflow" and generic["match"] == {"workflow": "portrait.json"}
    assert rename["image"] == "image_10" and rename["values.3.steps"] == "steps_3" and rename["prompt"] == "prompt"
    assert rename["values.采样.steps"] == "steps_3", "老的 values 也可以按节点标题写(graph.set_value 两种都认)"
    assert rename["values.3.seed"] == "seed" and rename["values.5.width"] == "width", "种子和尺寸写在 values 里的也有去处"
    assert by_path == {"tool": "wf_" + hashlib.sha1(b"portrait.json").hexdigest()[:12], "match": {}, "rename": {},
                       "drop_if": {}}, "老版本存的图没有 id、再存一次就有了:以前按路径哈希起的名字迁过来"


def test_内置文生图的工具_占位符就是它的入参(comfy, tmp_path: Path) -> None:
    tool = _tools(comfy.url, tmp_path)["wf_builtin_txt2img"]
    assert tool["label"] == {"zh": "工作流 · 内置文生图", "en": "Workflow · Built-in text-to-image"}
    properties = tool["input_schema"]["properties"]
    assert {"prompt", "negative_prompt", "steps", "seed", "width", "height"} <= set(properties)
    assert properties["steps"]["default"] == 20 and "x-advanced" not in properties["steps"]
    assert properties["ckpt_name_4"]["enum"] == ["sd_xl_base.safetensors", "v1-5.ckpt"]
    assert tool["replaces"] == [{"tool": "run_workflow", "match": {"workflow": "builtin:txt2img"},
                                 "rename": tool["replaces"][0]["rename"], "drop_if": {"wait": True}}], (
        "它没有路径,也就没有按路径哈希起过名字")
    assert tool["replaces"][0]["rename"]["steps"] == "steps"


def test_放大工作流_图必填_没有提示词(comfy, tmp_path: Path) -> None:
    tool = _tools(comfy.url, tmp_path)[UPSCALE_TOOL]
    properties = tool["input_schema"]["properties"]
    assert "prompt" not in properties
    assert tool["input_schema"]["required"] == ["image_1"]
    assert properties["model_name_2"]["title"] == {"zh": "放大模型", "en": "Upscale model"}
    assert tool["description"]["zh"].startswith("在 ComfyUI 上原样跑「upscale」这张工作流(放大)")
    assert [key for key in tool["node"]["outputs"] if key.startswith("image_")] == ["image_4", "image_5"]


def test_每张工作流的工具都上画板_按吃什么素材分组(comfy, tmp_path: Path) -> None:
    """画板上只放内容变换(ADR 0021 修订):每张工作流都交出素材(它的保存节点的产出是素材),所以都是
    内容变换;读图的放大归「处理图片」,只收提示词的文生图归「产出新素材」。(用得上同名生成模型的人画板上
    不列其中那几张 —— 见 test_board_tools_mirrored_by_generation;这里问的是规矩本身。)"""
    from app.domain.boards.transforms import board_group, is_content_transform
    from app.domain.plugins.nodes import node_meta

    tools = _tools(comfy.url, tmp_path)
    metas = {name: node_meta(tool) for name, tool in tools.items()}
    assert all(is_content_transform(meta) for meta in metas.values()), [
        name for name, meta in metas.items() if not is_content_transform(meta)]
    assert board_group(metas[UPSCALE_TOOL]) == "image"
    assert board_group(metas["wf_builtin_txt2img"]) == "new"


def test_跑一张工作流的工具_字符串转回类型_素材接上_具名输出(comfy, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _tools(comfy.url, data_dir)
    comfy.state.outputs = {"9": {"images": [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}]},
                           "40": {"text": ["一只猫"]}}
    image = tmp_path / "参考.png"
    image.write_bytes(PNG)
    scratch = tmp_path / "out"
    scratch.mkdir()
    result = runtime.stream_tool(
        PLUGIN, ENTRY, PORTRAIT_TOOL,
        {"prompt": "海边的柴犬", "image_10": str(image), "steps_3": "30", "cfg_3": "6.5", "width": "", "gone_99": "x"},
        {"SERVER_URL": comfy.url}, hooks=runtime.StreamHooks(lambda *_: None, lambda _: None, lambda: False),
        scratch_dir=scratch, data_dir=data_dir, timeout=60,
    ).output
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["3"]["inputs"]["steps"] == 30 and prompt["3"]["inputs"]["cfg"] == 6.5, "表单里的字符串按声明的类型转回来"
    assert prompt["6"]["inputs"]["text"] == "海边的柴犬"
    assert prompt["7"]["inputs"]["text"] == "blurry", "没给反向提示词就用工作流里写好的"
    assert prompt["3"]["inputs"]["seed"] != 42, "工作流里设的是每次随机(randomize):没给种子就换一个"
    assert prompt["5"]["inputs"]["width"] == 832, "空着的格子不接"
    assert prompt["10"]["inputs"]["image"].startswith("mosael/") and prompt["10"]["inputs"]["image"].endswith("参考.png")
    first, second = result["artifacts"]
    assert first["output"] == "image_9" and "output" not in second, "每个输出节点的第一份是那个具名输出"
    assert result["text_40"] == "一只猫"


def test_自定义输出节点的产出落在它声明的那个输出上(comfy, tmp_path: Path) -> None:
    """object_info 里标了 output_node 的自定义保存节点,工具声明的是 `output_12`:交回时也得记在 `output_12` 上,
    不能按文件后缀另起一个 `image_12` —— 那样下游接「那个保存节点的图」永远是空的。"""
    comfy.state.object_info["SaveImageExtended"] = {"input": {"required": {"images": ["IMAGE"]}}, "output_node": True}
    comfy.state.workflows["custom.json"] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "12": {"class_type": "SaveImageExtended", "inputs": {"images": ["1", 0]}},
    }
    tool_name = "wf_" + hashlib.sha1(b"custom.json").hexdigest()[:12]
    tool = _tools(comfy.url, tmp_path)[tool_name]
    assert "output_12" in tool["node"]["outputs"]
    comfy.state.outputs = {"12": {"images": [{"filename": "x.png", "type": "output"}]}}
    image = tmp_path / "x.png"
    image.write_bytes(PNG)
    scratch = tmp_path / "out"
    scratch.mkdir()
    result = runtime.stream_tool(
        PLUGIN, ENTRY, tool_name, {"image_1": str(image)}, {"SERVER_URL": comfy.url},
        hooks=runtime.StreamHooks(lambda *_: None, lambda _: None, lambda: False),
        scratch_dir=scratch, data_dir=tmp_path, timeout=60,
    ).output
    assert [one["output"] for one in result["artifacts"]] == ["output_12"]


def test_两台服务器的对照表各记各的_跑工具不用整个重扫(comfy, tmp_path: Path) -> None:
    """插件的持久目录是整个插件共用的:两台 ComfyUI 的工具对照表记在同一个文件里,就互相覆盖,
    每跑一次工具都要把那台服务器上的工作流整个拉一遍。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with FakeComfyUI() as other:
        _tools(comfy.url, data_dir)
        _tools(other.url, data_dir)
    comfy.state.calls.clear()
    comfy.state.outputs = {"4": {"images": [{"filename": "up.png", "type": "output"}]}}
    image = tmp_path / "x.png"
    image.write_bytes(PNG)
    scratch = tmp_path / "out"
    scratch.mkdir()
    runtime.stream_tool(PLUGIN, ENTRY, UPSCALE_TOOL, {"image_1": str(image)}, {"SERVER_URL": comfy.url},
                        hooks=runtime.StreamHooks(lambda *_: None, lambda _: None, lambda: False),
                        scratch_dir=scratch, data_dir=data_dir, timeout=60)
    listings = [call for call in comfy.state.calls if call[1] == "/api/userdata" and call[2].get("dir") == ["workflows"]]
    assert listings == [], "对照表里就有这台服务器上的这个工具,不必把工作流整个重扫一遍"


def test_没记住对照表也找得到(comfy, tmp_path: Path) -> None:
    """插件的持久目录是空的(刚升级、被清过):按名字重新扫一遍找到那张图。"""
    comfy.state.outputs = {"4": {"images": [{"filename": "up.png", "type": "output"}]}}
    image = tmp_path / "x.png"
    image.write_bytes(PNG)
    scratch = tmp_path / "out"
    scratch.mkdir()
    result = runtime.stream_tool(
        PLUGIN, ENTRY, UPSCALE_TOOL, {"image_1": str(image)}, {"SERVER_URL": comfy.url},
        hooks=runtime.StreamHooks(lambda *_: None, lambda _: None, lambda: False),
        scratch_dir=scratch, data_dir=tmp_path / "empty", timeout=60,
    ).output
    assert [one["output"] for one in result["artifacts"]] == ["image_4"]


def test_工作流删掉了说清楚(comfy, tmp_path: Path) -> None:
    scratch = tmp_path / "out"
    scratch.mkdir()
    with pytest.raises(runtime.PluginRuntimeError, match="刷新模型"):
        runtime.stream_tool(PLUGIN, ENTRY, "wf_000000000000", {}, {"SERVER_URL": comfy.url},
                            hooks=runtime.StreamHooks(lambda *_: None, lambda _: None, lambda: False),
                            scratch_dir=scratch, timeout=60)


def test_list_workflows_说出每张工作流自己的工具(comfy) -> None:
    listed = runtime.execute_tool(PLUGIN, ENTRY, "list_workflows", {}, {"SERVER_URL": comfy.url}, timeout=60).output
    tools = {one["id"]: one.get("tool") for one in listed["workflows"]}
    assert tools["portrait.json"] == PORTRAIT_TOOL and tools["builtin:txt2img"] == "wf_builtin_txt2img"


# ── 画板上落什么、和生成模型是不是同一件事 ─────────────────────────────────────────

#: 一张**只交出一段字**的工作流(打标签 / 反推提示词):读一张图 → 标签节点 → ShowText。
TAGGER_API: dict[str, Any] = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
    "2": {"class_type": "WD14Tagger|pysssss", "inputs": {"image": ["1", 0], "threshold": 0.35}},
    "3": {"class_type": "ShowText|pysssss", "inputs": {"text": ["2", 0]}},
}
#: 一张**拿 LoadImage 的 alpha 当蒙版**的局部重绘:图和它的 alpha 两路都接下去 —— 只有工具会把蒙版合进 alpha。
ALPHA_API: dict[str, Any] = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
    "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["4", 2]}},
    "6": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["5", 0], "mask": ["1", 1]}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "x"}},
}
TAGGER_TOOL = "wf_" + hashlib.sha1(b"tagger.json").hexdigest()[:12]
ALPHA_TOOL = "wf_" + hashlib.sha1(b"alpha.json").hexdigest()[:12]
WAN_TOOL = "wf_" + hashlib.sha1(b"video/wan.json").hexdigest()[:12]


def _with_tagger_and_alpha(comfy) -> None:
    comfy.state.object_info["WD14Tagger|pysssss"] = {"input": {"required": {
        "image": ["IMAGE"], "threshold": ["FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0}]}}}
    comfy.state.object_info["SetLatentNoiseMask"] = {"input": {"required": {"samples": ["LATENT"], "mask": ["MASK"]}}}
    comfy.state.workflows["tagger.json"] = TAGGER_API
    comfy.state.workflows["alpha.json"] = ALPHA_API


def _models(comfy) -> dict[str, dict[str, Any]]:
    output = runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "models"}, {"SERVER_URL": comfy.url},
                                  timeout=60).output
    return {model["id"]: model for model in output["models"]}


def test_画板上只落每个输出节点自己的产出_给连线用的五个不落(comfy, tmp_path: Path) -> None:
    """此前一次运行落五格:`image_9`、同一个文件的 `asset_id`、一张 `asset_ids` 的 JSON 便签、摘要、任务号。
    现在五个给连线用的声明成 `wiring_outputs`,画板上只落那个保存节点的图。工作流里它们照样接得上。"""
    from app.domain.boards.tools import board_outputs, landing_outputs
    from app.domain.plugins.nodes import node_meta

    tools = _tools(comfy.url, tmp_path)
    for name, tool in tools.items():
        node = tool["node"]
        assert node["wiring_outputs"] == ["asset_id", "asset_ids", "texts", "summary", "prompt_id"], name
        assert node["board_outputs"] == [key for key in node["outputs"] if key not in node["wiring_outputs"]], name
    assert landing_outputs(node_meta(tools[PORTRAIT_TOOL])) == ["image_9"]
    assert landing_outputs(node_meta(tools[UPSCALE_TOOL])) == ["image_4", "image_5"]
    collected = {"image_9": "a1", "asset_id": "a1", "asset_ids": ["a1"], "texts": [], "summary": "1 张图", "prompt_id": "p1"}
    assert board_outputs(node_meta(tools[PORTRAIT_TOOL]), collected) == [{"type": "asset", "asset_id": "a1"}]


def test_只有一个图视频音频输出节点的图_声明它和生成模型是同一件事(comfy, tmp_path: Path) -> None:
    _with_tagger_and_alpha(comfy)
    tools = _tools(comfy.url, tmp_path)
    portrait = tools[PORTRAIT_TOOL]["mirrors"]
    assert portrait["generation_model"] == "portrait.json" and portrait["kind"] == "image"
    assert portrait["prompt"] == "prompt"
    assert portrait["sources"] == {"image_10": "reference_image"}
    #: 入参按生成参数的键改名:可调参数是 `节点 id.输入名`,种子 / 反向提示词 / 张数同名;宽高对不过去。
    assert portrait["parameters"]["steps_3"] == "3.steps" and portrait["parameters"]["negative_prompt"] == "negative_prompt"
    assert portrait["parameters"]["seed"] == "seed" and portrait["parameters"]["num_images"] == "num_images"
    assert "width" not in portrait["parameters"]
    #: 同一个 id 就在插件的模型目录里,改名后的键就是那个模型的生成参数。
    models = _models(comfy)
    assert set(portrait["parameters"].values()) <= set(models["portrait.json"]["parameters"])
    assert tools[WAN_TOOL]["mirrors"]["kind"] == "video" and tools[WAN_TOOL]["mirrors"]["generation_model"] == "video/wan.json"
    assert tools[WAN_TOOL]["mirrors"]["sources"] == {"image_12": "first_frame"}
    assert models["video/wan.json"]["kind"] == "video"
    assert tools["wf_builtin_txt2img"]["mirrors"]["generation_model"] == "builtin:txt2img"
    #: 只有工具做得到的:两个输出节点(保存 + 预览)、只交出一段字、拿 alpha 当蒙版 —— 不声明。
    for only_tool in (UPSCALE_TOOL, TAGGER_TOOL, ALPHA_TOOL):
        assert "mirrors" not in tools[only_tool], only_tool
    assert "mask" in tools[ALPHA_TOOL]["input_schema"]["properties"]


def test_只交出一段字的图不是生成模型_照样是工具(comfy, tmp_path: Path) -> None:
    """打标签、反推提示词这类图交不出成片:`kind_of` 会把它兜成 image,此前它就这样出现在图片模型的选择器里,
    选了永远拿不回一张图。现在模型目录跳过它;工具照旧在,交出的那段字点名落板,吃的是一张图 ——
    画板上归「处理图片」(按吃什么分组),不是「处理文字」。"""
    from app.domain.boards.transforms import board_group, content_transform_gap
    from app.domain.plugins.nodes import node_meta

    _with_tagger_and_alpha(comfy)
    models = _models(comfy)
    assert "tagger.json" not in models and {"portrait.json", "alpha.json", "upscale.json"} <= set(models)
    tool = _tools(comfy.url, tmp_path)[TAGGER_TOOL]
    assert tool["node"]["board_outputs"] == ["text_3"] and tool["node"]["output_types"]["text_3"] == "text"
    meta = node_meta(tool)
    assert content_transform_gap(meta) is None
    assert board_group(meta) == "image"
