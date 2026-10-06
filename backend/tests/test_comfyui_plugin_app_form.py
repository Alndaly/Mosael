"""应用表单(ADR 0038 第一刀):一张工作流**全部能填的项**、作者挑出来存进工作流文件的那张表、目录和工具只剩表单那几项、
改工作流文件的 `annotate`。

- `graph.items`:今天生成目录、工具入参各推各的那几步收成一份(提示词、读素材的节点、种子 / 尺寸 / 跑几遍、其余字面量);
  `tunable` 和缺省目录照旧从它出来;
- `app_form`:节点 `properties.mosael` + 图 `extra.mosael` 的读、核对、写 —— 标记跟着节点走(节点号变了还在、节点删了一起没),
  对不上的项(节点不在会跑的那部分图里、那一格被拉成连线、可选值不在下拉里)不进表单、列出原因,版本只认当前这一版;
- 目录(`describe`)有应用表单时**只剩作者挑的那几项**,按作者排的顺序、用作者起的名字,读素材的槽位按顺序带名字(`labels`);
  标成结果的输出节点是「结果取自」的缺省;
- `annotate` 只改 `mosael` 那几处标记、带着读到时的改动时间(被改过就不写),对着假 ComfyUI;
- 经插件进程跑:目录、工具、`generate` 只认表单里的键,没挑的项照工作流原样跑,产出带着它来自的节点(`source_node`)。

纯函数的部分不连任何服务;要写文件的对着 tests/fake_comfyui.py。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import (
    OBJECT_INFO,
    PORTRAIT_UI,
    TWO_PASS_HAND_DEPTH,
    FakeComfyUI,
    fixture_workflow,
    multi_reference_ui,
)

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
ENTRY = "tools/main.py"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service", "shared_models", "workflows",
            "tooling", "library", "sources", "install", "model_files", "families", "workflow_library",
            "workflow_import", "app_form")

#: 测试里那张「换装」应用:两张参考图(人物起了名、背景没起)、主提示词、收窄到一个文件的 LoRA、步数、种子;#17 标成结果。
APP: dict[str, Any] = {
    "title": "换装",
    "description": "上传人物和背景",
    "items": [
        {"node": "10", "input": "image", "label": "人物照片"},
        {"node": "14", "input": "image"},
        {"node": "6", "input": "text", "main": True},
        {"node": "20", "input": "lora_name", "label": "风格", "choices": ["detail.safetensors"]},
        {"node": "3", "input": "steps"},
        {"node": "", "input": "seed"},
    ],
}


@pytest.fixture(scope="module")
def plugin():
    """插件的模块名很普通(graph / models / run),用完就从 sys.modules 摘掉,不串到别的测试里。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import app_form
        import convert
        import graph

        yield graph, convert, app_form
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _api(plugin, ui: dict[str, Any], object_info: dict[str, Any] = OBJECT_INFO) -> tuple[dict[str, Any], dict[str, str]]:
    graph, convert, _ = plugin
    api = graph.live(convert.to_api(ui, object_info), object_info)
    return api, convert.titles_of(api)


def _form(plugin, ui: dict[str, Any], object_info: dict[str, Any] = OBJECT_INFO):
    _, _, app_form = plugin
    api, titles = _api(plugin, ui, object_info)
    marks = app_form.read(ui)
    form, invalid = app_form.resolve(marks, api, object_info, titles)
    return api, titles, marks, form, invalid


def _strip(ui: dict[str, Any]) -> dict[str, Any]:
    """去掉 Mosael 的标记(空出来的 properties / extra 当没有):两张图除了标记一样,就是只改了标记。"""
    out = copy.deepcopy(ui)
    for node in out.get("nodes") or []:
        props = node.get("properties")
        if isinstance(props, dict):
            props.pop("mosael", None)
            if not props:
                node.pop("properties")
    if isinstance(out.get("extra"), dict):
        out["extra"].pop("mosael", None)
        if not out["extra"]:
            out.pop("extra")
    return out


# --- 能填的项 -------------------------------------------------------------------


def test_能填的项_一份推导_提示词_素材_图级的项_其余按常用程度(plugin) -> None:
    graph, _, _ = plugin
    api, titles = _api(plugin, multi_reference_ui())
    found = graph.items(api, OBJECT_INFO, titles)
    assert [(one["key"], one["kind"]) for one in found] == [
        ("6.text", "text"), ("7.text", "text"),
        ("10.image", "media"), ("13.image", "media"), ("14.image", "media"),
        ("seed", "seed"), ("size", "size"), ("runs", "runs"),
        ("4.ckpt_name", "model"), ("20.lora_name", "model"), ("20.strength_model", "number"),
        ("20.strength_clip", "number"), ("3.steps", "number"), ("3.cfg", "number"),
        ("3.sampler_name", "choice"), ("3.scheduler", "choice"), ("3.denoise", "number"),
    ]
    by_key = {one["key"]: one for one in found}
    assert by_key["6.text"]["role"] == "prompt" and by_key["7.text"]["role"] == "negative"
    assert by_key["6.text"]["schema"]["default"] == "a girl in a garden"
    assert by_key["10.image"]["title"] == {"zh": "参考图 · 人物", "en": "Reference image · 人物"}, "起了名的读图节点用它的名字"
    assert by_key["13.image"]["title"] == {"zh": "参考图 · 加载图像 #13", "en": "Reference image · LoadImage #13"}, \
        "没起名的是「节点名 #节点」:中文用核心节点的中文名;夹具的 object_info 没写 display_name,英文退回类名"
    assert by_key["13.image"]["node_label"] == {"zh": "加载图像", "en": "LoadImage"}
    assert by_key["10.image"]["node_label"] == {"zh": "人物", "en": "人物"}, "用户起的标题压过 ComfyUI 给的名字"
    assert by_key["seed"].get("node_label") is None, "图级的项没有节点"
    assert by_key["20.lora_name"]["folder"] == "loras"
    assert by_key["seed"]["node"] == "" and by_key["size"]["schema"]["default"] == "1024x1024"
    assert by_key["20.strength_clip"]["common"] is False
    # tunable(给人调的那几格)就是能填的项里的那几种 —— 同一份推导,不各推各的
    tunable = graph.tunable(api, OBJECT_INFO, titles)
    assert tunable == {one["key"]: {"title": one["title"], **one["schema"]}
                       for one in found if one["kind"] in graph.VALUE_KINDS and not one.get("role")}


#: 一个自定义 LoRA 加载器(照维护者那台 ComfyUI 上 pysssss 的 `LoraLoader|pysssss` 的定义,裁掉下拉):`prompt` 是它存示例
#: 提示词的那一格,ComfyUI 标了 hidden,界面上没有;再加一个只有 object_info 名字的自定义节点和一格标了 advanced 的。
NAMED_INFO: dict[str, Any] = {
    "LoraLoader|pysssss": {
        "display_name": "Lora Loader 🐍",
        "input": {"required": {
            "model": ["MODEL"], "clip": ["CLIP"],
            "lora_name": [["detail.safetensors"], {"tooltip": "The name of the LoRA."}],
            "strength_model": ["FLOAT", {"default": 1.0, "tooltip": "How strongly to modify the diffusion model."}],
        }, "optional": {"prompt": ["STRING", {"hidden": True}]}},
        "output": ["MODEL", "CLIP"],
    },
    "FancyBlur": {
        "display_name": "Fancy Blur ✨",
        "input": {"required": {
            "image": ["IMAGE"],
            "blur_radius": ["INT", {"default": 3, "display_name": "Blur radius", "tooltip": "Bigger is softer."}],
            "steps": ["INT", {"default": 20, "advanced": True}],
        }},
        "output": ["IMAGE"],
    },
}
#: ComfyUI 的 `/i18n`(自定义节点包带的翻译):FancyBlur 有中文,LoRA 加载器没有。
NAMED_I18N: dict[str, Any] = {
    "zh": {"nodeDefs": {"FancyBlur": {"display_name": "花式模糊", "inputs": {"blur_radius": {"name": "模糊半径",
                                                                                         "tooltip": "越大越柔"}}},
                        "NotInstalled": {"display_name": "没装的节点"}}},
    "en": {"nodeDefs": {"FancyBlur": {"display_name": "Fancy Blur"}}},
    "fr": {"nodeDefs": {"FancyBlur": {"display_name": "Flou fantaisie"}}},
}


def _named_api() -> dict[str, Any]:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}},
        "13": {"class_type": "LoraLoader|pysssss", "inputs": {"model": ["4", 0], "clip": ["4", 1],
                                                               "lora_name": "detail.safetensors", "strength_model": 0.8,
                                                               "prompt": ""}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["13", 1], "text": "a girl"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"model": ["13", 0], "positive": ["6", 0], "negative": ["6", 0],
                                                   "latent_image": ["5", 0], "seed": 1, "steps": 20, "cfg": 7.0,
                                                   "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "20": {"class_type": "FancyBlur", "inputs": {"image": ["8", 0], "blur_radius": 3, "steps": 20}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["20", 0], "filename_prefix": "x"}},
    }


def test_节点名_用户起的标题_再是ComfyUI按语言给的名字_核心节点中文_display_name_最后才是类名(plugin) -> None:
    sys.path.insert(0, str(TOOLS))
    try:
        import labels
    finally:
        sys.path.remove(str(TOOLS))
    info = labels.with_i18n({**OBJECT_INFO, **NAMED_INFO}, NAMED_I18N)
    assert "NotInstalled" not in info, "没装的节点不因为有翻译就冒出来"
    assert labels.node_name("FancyBlur", "", info) == {"zh": "花式模糊", "en": "Fancy Blur"}, "/i18n 按语言的名字在前"
    assert labels.node_name("FancyBlur", "FancyBlur", info) == {"zh": "花式模糊", "en": "Fancy Blur"}, "标题就是类名 = 没起名"
    assert labels.node_name("FancyBlur", "柔焦", info) == {"zh": "柔焦", "en": "柔焦"}, "用户起的标题压过一切"
    assert labels.node_name("LoraLoader|pysssss", "", info) == {"zh": "Lora Loader 🐍", "en": "Lora Loader 🐍"}, \
        "没有翻译:用 object_info 的 display_name,不用类名"
    assert labels.node_name("KSampler", "", info) == {"zh": "K 采样器", "en": "KSampler"}, "核心节点的中文名在插件里"
    assert labels.node_name("SomethingElse", "", info) == {"zh": "SomethingElse", "en": "SomethingElse"}, "什么都没有才是类名"
    assert labels.with_i18n(info, None) is info and labels.with_i18n(info, {"zh": "坏的"}) is info, "形状不对就不并"


def test_能填的项_ComfyUI给的名字和说明_hidden的不列_advanced的收进高级(plugin) -> None:
    graph, _, _ = plugin
    sys.path.insert(0, str(TOOLS))
    try:
        import labels
    finally:
        sys.path.remove(str(TOOLS))
    info = labels.with_i18n({**OBJECT_INFO, **NAMED_INFO}, NAMED_I18N)
    api = _named_api()
    found = {one["key"]: one for one in graph.items(api, info, {})}
    assert "13.prompt" not in found, "pysssss 存示例提示词的那一格 ComfyUI 标了 hidden:不是「LoraLoader|pysssss · Prompt」"
    assert found["13.lora_name"]["title"] == {"zh": "LoRA", "en": "LoRA"}, "认得的输入照旧用 Mosael 的名字"
    assert found["13.lora_name"]["node_label"] == {"zh": "Lora Loader 🐍", "en": "Lora Loader 🐍"}
    assert found["13.lora_name"]["hint"] == {"zh": "The name of the LoRA.", "en": "The name of the LoRA."}, \
        "ComfyUI 的 tooltip 是这一格的说明;没有中文就两种语言都用它"
    assert found["20.blur_radius"]["title"] == {"zh": "花式模糊 · 模糊半径", "en": "Fancy Blur · Blur radius"}, \
        "不认得的输入:节点名 + ComfyUI 给这一格的名字(中文从 /i18n,英文从 object_info 的 display_name)"
    assert found["20.blur_radius"]["hint"] == {"zh": "越大越柔", "en": "Bigger is softer."}
    assert found["20.steps"]["common"] is False, "ComfyUI 标了 advanced:步数在别的节点上常用,在这里也收进高级"
    assert found["3.steps"]["common"] is True
    assert found["4.ckpt_name"]["node_label"] == {"zh": "Checkpoint 加载器", "en": "CheckpointLoaderSimple"}
    assert found["6.text"]["node_label"] == {"zh": "CLIP 文本编码", "en": "CLIPTextEncode"}
    assert all("|" not in one["title"]["zh"] for one in found.values()), "类名不进名字"
    #: 同一份名字也进「结果取自」和节点:哪个界面都是同一个说法
    outputs = graph.output_nodes(api, info, {})
    assert [(one["node"], one["label"]) for one in outputs] == [("9", {"zh": "保存图像", "en": "SaveImage"})]


def test_读ComfyUI的节点定义时并上它给的各语言名字_没有i18n照旧(plugin) -> None:
    sys.path.insert(0, str(TOOLS))
    try:
        import comfy_http
        import labels
    finally:
        sys.path.remove(str(TOOLS))
    with FakeComfyUI() as server:
        server.state.object_info = json.loads(json.dumps({**OBJECT_INFO, **NAMED_INFO}))
        plain = comfy_http.Comfy(server.url).object_info()
        assert labels.I18N_KEY not in plain["FancyBlur"], "老版本没有 /i18n(404):只用 object_info 自己的名字"
        assert labels.node_name("FancyBlur", "", plain) == {"zh": "Fancy Blur ✨", "en": "Fancy Blur ✨"}
        server.state.static["/i18n"] = ("application/json", json.dumps(NAMED_I18N).encode())
        named = comfy_http.Comfy(server.url).object_info()
        assert labels.node_name("FancyBlur", "", named) == {"zh": "花式模糊", "en": "Fancy Blur"}
        assert set(named["FancyBlur"][labels.I18N_KEY]) == {"zh", "en"}, "只并界面有的两种语言"


def test_缺省的目录_一个角色几个槽位按顺序带名字(plugin) -> None:
    graph, _, _ = plugin
    api, titles = _api(plugin, multi_reference_ui())
    model = graph.describe("multi.json", "multi", api, OBJECT_INFO, titles)
    assert model["inputs"] == [{"role": "reference_image", "max": 3,
                                "labels": ["人物", {"zh": "加载图像 #13", "en": "LoadImage #13"}, "背景"]}]
    assert list(model["parameters"]) == [
        "negative_prompt", "seed", "size", "num_images", "output_node", "4.ckpt_name", "20.lora_name",
        "20.strength_model", "20.strength_clip", "3.steps", "3.cfg", "3.sampler_name", "3.scheduler", "3.denoise",
    ]
    assert model["label"] == "multi" and model["prompt"] == "optional" and model["outputs_per_run"] == 2


def test_缺省的目录_唯一一个没起名的槽位不挂名字(plugin) -> None:
    graph, _, _ = plugin
    api, titles = _api(plugin, PORTRAIT_UI)
    assert graph.describe("portrait.json", "portrait", api, OBJECT_INFO, titles)["inputs"] == [
        {"role": "reference_image", "max": 1}], "一个角色就一格、也没起名:给它挂一个「加载图像 #10」没有用"


# --- 应用表单:读、核对 ---------------------------------------------------------------


def test_应用表单_目录里只有作者挑的那几项_按作者排的顺序和名字(plugin) -> None:
    graph, _, app_form = plugin
    ui = app_form.apply(multi_reference_ui(), APP, ["17"])
    api, titles, marks, form, invalid = _form(plugin, ui)
    assert marks.status == "ok" and marks.app and invalid == []
    assert [field.key for field in form.fields] == ["10.image", "14.image", "6.text", "20.lora_name", "3.steps", "seed"]
    model = graph.describe("multi.json", "multi", api, OBJECT_INFO, titles, form)
    assert model["label"] == "换装", "应用的标题换掉模型下拉里那一项的名字"
    assert list(model["parameters"]) == ["seed", "output_node", "20.lora_name", "3.steps"], \
        "没挑的项不出现:反向提示词、尺寸、跑几遍、checkpoint、CFG……照工作流原样跑"
    lora = model["parameters"]["20.lora_name"]
    assert lora["title"] == "风格" and lora["enum"] == ["detail.safetensors"] and lora["x-model-folder"] == "loras"
    assert "x-advanced" not in model["parameters"]["3.steps"], "作者挑出来的每一项都在第一屏"
    assert model["parameters"]["3.steps"]["title"] == {"zh": "步数", "en": "Steps"}, "没起名就用这一项自己的名字"
    assert model["inputs"] == [{"role": "reference_image", "max": 2, "labels": ["人物照片", "背景"]}], \
        "#13 没挑:它照工作流原样读 style.png;槽位按表单的顺序、用作者起的名字(没起名的用节点名)"
    assert model["prompt"] == "optional"
    choice = model["parameters"]["output_node"]
    assert choice["default"] == "final" and choice["x-enum-labels"]["final"]["zh"] == "你选的结果(保存图像 #17)"
    assert model["outputs_per_run"] == 1 and model["max_outputs"] == 2, "标了一个结果:缺省只交回它;没挑跑几遍就是一遍"


def test_应用表单_填图只写表单那几格_素材按表单的顺序接(plugin) -> None:
    graph, _, app_form = plugin
    ui = app_form.apply(multi_reference_ui(), APP, [])
    api, _, _, form, _ = _form(plugin, ui)
    filled = graph.fill(api, {"prompt": "a cat", "negative": "ugly"}, {}, OBJECT_INFO, form.prompts())
    assert filled["6"]["inputs"]["text"] == "a cat"
    assert filled["7"]["inputs"]["text"] == "blurry", "反向提示词没挑:保留工作流里存的那句"
    wired = graph.wire_inputs(filled, "image", {"reference_image": ["mosael/a.png", "mosael/b.png"]}, form.slots())
    assert (wired["10"]["inputs"]["image"], wired["13"]["inputs"]["image"], wired["14"]["inputs"]["image"]) == \
        ("mosael/a.png", "style.png", "mosael/b.png"), "第 i 份接到表单上这个角色的第 i 个槽位,没挑的那个不动"


def test_节点号变了_标记跟着节点走(plugin) -> None:
    graph, _, app_form = plugin
    ui = app_form.apply(multi_reference_ui(), APP, [])
    for node in ui["nodes"]:
        if node["id"] == 10:
            node["id"] = 110
    for link in ui["links"]:
        if link[1] == 10:
            link[1] = 110
    api, titles, _, form, invalid = _form(plugin, ui)
    assert invalid == []
    assert [field.key for field in form.fields][:2] == ["110.image", "14.image"], \
        "参数键仍是 <节点 id>.<输入名>:节点号变了,键跟着变(存着的旧值对不上就不用,和今天一样)"
    assert graph.describe("m.json", "m", api, OBJECT_INFO, titles, form)["inputs"][0]["labels"] == ["人物照片", "背景"]


def test_节点删了_标记一起没_别的照旧(plugin) -> None:
    graph, _, app_form = plugin
    ui = app_form.apply(multi_reference_ui(), APP, [])
    ui["nodes"] = [node for node in ui["nodes"] if node["id"] != 14]
    for link in ui["links"]:
        if link[0] == 6:
            link[1] = 13  # 背景那一路改接 #13
    api, titles, _, form, invalid = _form(plugin, ui)
    assert invalid == [] and "14.image" not in [field.key for field in form.fields]
    assert graph.describe("m.json", "m", api, OBJECT_INFO, titles, form)["inputs"] == [
        {"role": "reference_image", "max": 1, "labels": ["人物照片"]}]


def test_对不上的项不进表单_说出原因(plugin) -> None:
    graph, _, app_form = plugin
    app = {"title": "", "description": "", "items": [
        *APP["items"],
        {"node": "13", "input": "image"},
        {"node": "3", "input": "gone"},
        {"node": "9", "input": "filename_prefix"},
        {"node": "3", "input": "sampler_name", "choices": ["euler", "removed_sampler"]},
    ]}
    ui = app_form.apply(multi_reference_ui(), app, [])
    for node in ui["nodes"]:
        if node["id"] == 13:
            node["mode"] = 2  # 静音:不在会跑的那部分图里
    _, _, marks, form, invalid = _form(plugin, ui)
    problems = {one["key"]: one["problem"]["zh"] for one in invalid}
    assert set(problems) == {"13.image", "3.gone", "9.filename_prefix", "3.sampler_name"}
    assert "不在会跑的那部分图里" in problems["13.image"]
    assert "没有「gone」这一格了" in problems["3.gone"]
    assert "不是一个能放进应用表单的项" in problems["9.filename_prefix"]
    assert "removed_sampler" in problems["3.sampler_name"], "收窄的可选值不在下拉里了"
    assert "13.image" not in [field.key for field in form.fields]
    summary = app_form.summary(marks, form, invalid, "zh")
    assert summary["invalid"] == 4 and summary["fields"] == len(form.fields)
    assert {one["key"]: bool(one.get("problem")) for one in summary["items"]}["3.gone"] is True
    titles = {one["key"]: one.get("title") for one in summary["items"]}
    assert titles["10.image"] == "人物照片" and titles["14.image"] == "参考图 · 背景" and titles["3.steps"] == "步数", \
        "有效的项带着它在表单上的名字(没起名就是这一项自己的名字);对不上的没有"
    assert titles["3.gone"] is None


def test_拉成连线的那一格不再能填(plugin) -> None:
    _, _, app_form = plugin
    info = {**OBJECT_INFO, "PrimitiveInt": {"input": {"required": {"value": ["INT", {"default": 0}]}}, "output": ["INT"]}}
    ui = app_form.apply(multi_reference_ui(), APP, [])
    ui["nodes"].append({"id": 30, "type": "PrimitiveInt", "widgets_values": [40], "inputs": [{"name": "value", "widget": {"name": "value"}}]})
    ui["links"].append([40, 30, 0, 3, 4, "INT"])
    for node in ui["nodes"]:
        if node["id"] == 3:
            node["inputs"] = [*node["inputs"][:4], {"name": "steps", "widget": {"name": "steps"}, "link": 40},
                              *node["inputs"][5:]]
    _, _, _, form, invalid = _form(plugin, ui, info)
    assert [one["key"] for one in invalid] == ["3.steps"]
    assert "拉成了连线" in invalid[0]["problem"]["zh"]


def test_版本不认识_按没有应用表单处理(plugin) -> None:
    graph, _, app_form = plugin
    ui = app_form.apply(multi_reference_ui(), APP, ["17"])
    ui["extra"]["mosael"]["version"] = 2
    api, titles, marks, form, invalid = _form(plugin, ui)
    assert (marks.status, marks.version) == ("unsupported", 2)
    assert not form.app and not form.results and invalid == [], "读的一侧不留认别的版本的分支:当作没有应用表单"
    default = graph.describe("m.json", "m", api, OBJECT_INFO, titles)
    assert graph.describe("m.json", "m", api, OBJECT_INFO, titles, form) == default
    assert app_form.summary(marks, form, invalid)["status"] == "unsupported"


def test_没有图上的那一份_节点上的标记不算(plugin) -> None:
    _, _, app_form = plugin
    ui = app_form.apply(multi_reference_ui(), APP, ["17"])
    del ui["extra"]["mosael"]
    assert app_form.read(ui) == app_form.NONE, "从别的工作流拷过来的节点带着的标记:没有版本,不当应用表单"


def test_只标了结果_听标记不再猜(plugin) -> None:
    graph, _, app_form = plugin
    ui, info = fixture_workflow(TWO_PASS_HAND_DEPTH)
    api, titles = _api(plugin, ui, info)
    guessed = graph.describe("hand.json", "hand", api, info, titles)
    assert guessed["parameters"]["output_node"]["x-enum-labels"]["final"]["zh"] == "最终结果(预览图像 #17)"
    marked = app_form.apply(ui, None, ["8"])
    assert marked["extra"]["mosael"] == {"version": 1}, "只有结果标记:没有应用表单"
    _, _, marks, form, _ = _form(plugin, marked, info)
    assert marks.results == ("8",) and not form.app
    model = graph.describe("hand.json", "hand", api, info, titles, form)
    choice = model["parameters"]["output_node"]
    assert choice["default"] == "final" and choice["x-enum-labels"]["final"]["zh"] == "你选的结果(预览图像 #8)"
    assert choice["x-enum-labels"]["17"] == {"zh": "预览图像 #17", "en": "Preview Image #17"}, \
        "标了结果时别的节点不再标「中间一步」"
    assert model["outputs_per_run"] == 4, "第一遍那张一遍出 4 张(画布批量 4)"
    assert graph.chosen_outputs(api, "image", "", info, titles, marked=form.results) == {"8"}
    assert list(model["parameters"]) == list(guessed["parameters"]), "没有应用表单:别的项照旧全列"


# --- 应用表单:写 ---------------------------------------------------------------


def test_写标记_只改mosael那几处_别的扩展写的键原样留着(plugin) -> None:
    _, _, app_form = plugin
    ui = multi_reference_ui()
    marked = app_form.apply(ui, APP, ["17"])
    assert _strip(marked) == _strip(ui) == ui
    assert marked["extra"]["ue_links"] == [] and marked["extra"]["0246.VERSION"] == [0, 0, 4]
    by_id = {node["id"]: node for node in marked["nodes"]}
    assert by_id[10]["properties"]["ue_properties"] == {"version": "7.1"}
    assert by_id[10]["properties"]["mosael"] == {"expose": {"image": {"order": 0, "label": "人物照片"}}}
    assert by_id[20]["properties"]["mosael"] == {"expose": {"lora_name": {"order": 3, "label": "风格",
                                                                          "choices": ["detail.safetensors"]}}}
    assert by_id[6]["properties"]["mosael"] == {"expose": {"text": {"order": 2, "main": True}}}
    assert by_id[17]["properties"]["mosael"] == {"result": True}
    assert marked["extra"]["mosael"] == {"version": 1, "app": {"title": "换装", "description": "上传人物和背景",
                                                               "graph_items": {"seed": {"order": 5}}}}
    # 改一次:旧的标记先摘干净,不留指着不再挑的项的配置
    again = app_form.apply(marked, {"title": "", "description": "", "items": [{"node": "3", "input": "cfg"}]}, [])
    assert sum("mosael" in (node.get("properties") or {}) for node in again["nodes"]) == 1
    assert _strip(app_form.apply(again, None, [])) == _strip(ui)
    assert "mosael" not in app_form.apply(again, None, [])["extra"], "去掉应用表单、也没有结果标记:图上那一份也没了"


def test_写标记_指着不存在的节点或子图里的节点就拒_什么都不写(plugin) -> None:
    _, _, app_form = plugin
    from lines import ComfyError

    for bad in ("99", "12:5"):
        with pytest.raises(ComfyError):
            app_form.apply(multi_reference_ui(), {"items": [{"node": bad, "input": "text"}]}, [])
    with pytest.raises(ComfyError):
        app_form.apply(multi_reference_ui(), {"items": [{"node": "", "input": "steps"}]}, [])
    with pytest.raises(ComfyError):
        app_form.apply({"3": {"class_type": "KSampler", "inputs": {}}}, None, ["3"])


# --- 对着假 ComfyUI:app / annotate,和经插件进程跑的目录、工具、生成 --------------------------


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


def test_读应用表单_全部能填的项和读到时的改动时间(comfy) -> None:
    out = _host("app", comfy.url, path="multi.json")
    assert out["path"] == "multi.json" and out["editable"] is True and out["kind"] == "image"
    assert out["modified"] == 1.0, "列目录给的改动时间(没存过的那张在假 ComfyUI 上是 1)"
    assert [one["key"] for one in out["items"]][:5] == ["6.text", "7.text", "10.image", "13.image", "14.image"]
    by_key = {one["key"]: one for one in out["items"]}
    assert by_key["13.image"]["node_label"] == {"zh": "加载图像", "en": "LoadImage"}, "节点给人看的名字一路带到编辑器"
    assert "node_label" not in by_key["seed"], "图级的项没有节点"
    assert [one["node"] for one in out["outputs"]] == ["9", "17"]
    #: 每个节点给人看的名字(工作台「运行与结果」用):和「结果取自」同一种叫法,不是类名
    assert out["names"]["17"]["zh"] == "保存图像", "核心节点没起标题:ComfyUI 给这类节点的中文名,不是 SaveImage"
    assert out["names"]["17"] == next(one["label"] for one in out["outputs"] if one["node"] == "17")
    assert out["names"]["13"] == by_key["13.image"]["node_label"]
    assert out["app"]["status"] == "none" and out["app"]["items"] == []


def test_annotate_写回_目录和工具只剩表单那几项(comfy, tmp_path: Path) -> None:
    seen = _host("app", comfy.url, path="multi.json")
    written = _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], app=APP, results=["17"])
    assert written["path"] == "multi.json" and written["modified"] != seen["modified"]
    writes = [call for call in comfy.state.calls if call[0] == "WRITE"]
    assert len(writes) == 1 and writes[0][1] == "workflows/multi.json" and writes[0][2]["overwrite"] is True, \
        "Mosael 唯一一处覆盖写:只写这一张、只写一次"
    stored = comfy.state.workflows["multi.json"]
    assert _strip(stored) == multi_reference_ui()
    assert stored["extra"]["mosael"]["app"]["title"] == "换装"

    again = _host("app", comfy.url, path="multi.json")
    assert again["modified"] == written["modified"]
    assert [one["key"] for one in again["app"]["items"]] == ["10.image", "14.image", "6.text", "20.lora_name", "3.steps",
                                                            "seed"]
    assert again["app"]["results"] == ["17"] and again["app"]["fields"] == 6

    model = next(one for one in _host("models", comfy.url)["models"] if one["id"] == "multi.json")
    assert model["label"] == "换装" and list(model["parameters"]) == ["seed", "output_node", "20.lora_name", "3.steps"]
    assert model["inputs"] == [{"role": "reference_image", "max": 2, "labels": ["人物照片", "背景"]}]

    tool = next(one for one in _host("tools", comfy.url)["tools"] if one["mirrors"]["generation_model"] == "multi.json")
    properties = tool["input_schema"]["properties"]
    assert list(properties) == ["prompt", "image_10", "image_14", "lora_name_20", "steps_3", "seed", "include_previews"], \
        "一张工作流的工具和生成说的是同一张表"
    assert properties["image_10"]["title"] == "人物照片" and properties["lora_name_20"]["enum"] == ["detail.safetensors"]

    listed = runtime.execute_tool(PLUGIN, ENTRY, "list_workflows", {}, {"SERVER_URL": comfy.url}, timeout=60).output
    flow = next(one for one in listed["workflows"] if one["id"] == "multi.json")
    assert flow["app"] == {"title": "换装", "description": "上传人物和背景"}
    assert [one["key"] for one in flow["parameters"]] == ["20.lora_name", "3.steps"]
    assert [one["title"] for one in flow["inputs"]] == ["人物照片", "背景"]


def _integral_floats_as_ints(value: Any) -> Any:
    """JSON.stringify 把 1.0 写成 1:读回来就是整数。夹具照它的样子。"""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _integral_floats_as_ints(one) for key, one in value.items()}
    if isinstance(value, list):
        return [_integral_floats_as_ints(one) for one in value]
    return value


def test_annotate_照原来的排版写回_没改的字节一个不变(comfy) -> None:
    """沙盒实测:annotate 一律按两格缩进写回,ComfyUI 自己存的紧凑 JSON(JSON.stringify)整份重排 —— 那台机器上的版本
    记录、同步盘里每次都是「整个文件都改了」。照原来的写:紧凑的还是紧凑的,数字照 JavaScript 的写法(0.00001 不写成
    1e-05)、中文不转义;缩进的照它的缩进和冒号后面有没有空格。"""
    source = _integral_floats_as_ints(copy.deepcopy(comfy.state.workflows["multi.json"]))
    source["extra"] = {**source.get("extra", {}), "ds": {"scale": 0.00001, "offset": [1222.054086911212, -3.5]}}
    source["备注"] = "中文,不转义"
    #: JSON.stringify 写出来的样子:Python 的紧凑写法,只有浮点数的写法不一样
    compact = json.dumps(source, ensure_ascii=False, separators=(",", ":")).replace("1e-05", "0.00001")
    comfy.state.workflows["multi.json"] = source
    comfy.state.raw_texts["workflows/multi.json"] = compact

    # 什么都不改(没有表单、没标结果):写回去的就是原文,一个字节不差
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], app=None, results=[])
    assert comfy.state.raw_texts["workflows/multi.json"] == compact

    # 改了:还是紧凑的、JS 的数字写法、中文原样;再写一遍同样的,一个字节都不变
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], app=APP, results=["17"])
    once = comfy.state.raw_texts["workflows/multi.json"]
    assert "\n" not in once and '": ' not in once and '", "' not in once, "紧凑的还是紧凑的"
    assert '"scale":0.00001' in once and "1e-05" not in once and "中文,不转义" in once
    assert json.loads(once)["extra"]["mosael"]["app"]["title"] == "换装"
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], app=APP, results=["17"])
    assert comfy.state.raw_texts["workflows/multi.json"] == once, "同样的标记再写一遍:不多一个字节的改动"

    # 缩进的(制表符、冒号后面没空格,有的编辑器就这么存):照它的
    tabbed = json.dumps(source, ensure_ascii=False, indent="\t", separators=(",", ":")).replace("1e-05", "0.00001") + "\n"
    comfy.state.raw_texts["workflows/multi.json"] = tabbed
    comfy.state.workflows["multi.json"] = json.loads(tabbed)
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], app=None, results=[])
    assert comfy.state.raw_texts["workflows/multi.json"] == tabbed


def test_annotate_文件在这之间被改过_不写(comfy) -> None:
    seen = _host("app", comfy.url, path="multi.json")
    comfy.state.touch("multi.json")  # 有人在 ComfyUI 里存了一次
    before = copy.deepcopy(comfy.state.workflows["multi.json"])
    out = _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], app=APP, results=[])
    assert out["stale"] is True and out["modified"] != seen["modified"]
    assert not [call for call in comfy.state.calls if call[0] == "WRITE"], "对不上就一个字都不写"
    assert comfy.state.workflows["multi.json"] == before


def test_annotate_没有这张了说清楚(comfy) -> None:
    with pytest.raises(runtime.PluginRuntimeError, match="已经没有工作流"):
        _host("annotate", comfy.url, path="gone.json", modified=1, app=None, results=[])


def test_生成_有应用表单时只认表单里的键_没挑的照工作流原样跑_产出标来源节点(comfy, tmp_path: Path) -> None:
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"],
          app={**APP, "items": [item for item in APP["items"] if item["input"] != "seed"]}, results=["17"])
    comfy.state.outputs = {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
                           "17": {"images": [{"filename": "b.png", "subfolder": "", "type": "output"}]}}
    scratch = tmp_path / "out"
    scratch.mkdir()
    request = {"op": "generate", "kind": "image", "model": "multi.json", "prompt": "a cat", "negative_prompt": "ugly",
               "parameters": {"3.steps": 30, "3.cfg": 9.5, "size": "512x512"}, "inputs": [], "resume": None}
    hooks = runtime.StreamHooks(on_progress=lambda *_: None, on_task=lambda _: None, is_cancelled=lambda: False)
    result = runtime.stream_tool(PLUGIN, ENTRY, "comfyui_generation", request, {"SERVER_URL": comfy.url},
                                 hooks=hooks, scratch_dir=scratch, timeout=60).output
    submitted = next(call[2]["prompt"] for call in comfy.state.calls if call[1] == "/prompt")
    assert submitted["6"]["inputs"]["text"] == "a cat"
    assert submitted["7"]["inputs"]["text"] == "blurry", "反向提示词没挑:不写"
    assert submitted["3"]["inputs"]["steps"] == 30
    assert submitted["3"]["inputs"]["cfg"] == 6.5, "画板格子里存着的旧键(没挑的 CFG)不再写进图"
    assert (submitted["5"]["inputs"]["width"], submitted["5"]["inputs"]["height"]) == (1024, 1024), "尺寸没挑:照工作流原样"
    assert submitted["3"]["inputs"]["seed"] == 42, "种子没挑、工作流里是固定的:留着"
    assert "9" not in submitted, "标了 #17 是结果:另一个保存节点不跑"
    assert [one["parameters"] for one in result["outputs"]] == [{"source_node": "17"}]
