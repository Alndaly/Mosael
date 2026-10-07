"""工作台里的智能体(ADR 0042 第一步:读和诊断)插件这一侧的几个只读操作。

夹具是录下来的真回答(tests/fixtures/comfyui/agent/):沙盒里 ComfyUI 0.39(模板包 0.11.76)的节点定义和模板索引、那张
Qwen-Image 2.1 编辑模板、维护者那台的 Manager(V4.2.1)装了哪些包和节点映射、Comfy 注册表对 rgthree-comfy(最新几版被标记)、
comfyui-sharpfin(依赖直接有 torch)、comfyui-reactor-node(封禁)的回答。下拉里的模型按这几条测试要的「这台机器」改过,见
各测试。

对着 tests/fake_comfyui.py 直接调插件的函数;注册表换成同一台假服务器上的 `/registry`。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fake_comfyui import FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "comfyui" / "agent"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service",
            "shared_models", "workflows", "tooling", "library", "sources", "install", "model_files", "families",
            "workflow_library", "workflow_import", "canvas", "diagnose", "templates", "node_types", "node_packs",
            "node_catalog", "app_form", "json_style", "weights", "nsfw", "previews", "provenance", "civitai", "lookup",
            "pinned", "managed", "versions", "model_search", "workbench")


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


QWEN = fixture("image_qwen_image_2_1_image_edit.json")
SUB = QWEN["definitions"]["subgraphs"][0]["id"]


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path / "data"))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    with FakeComfyUI() as server:
        state = server.state
        state.object_info = fixture("object_info.json")
        state.templates = {
            "index.mcp.json": fixture("templates.index.mcp.json"),
            "index.json": fixture("templates.index.json"),
            "index.zh.json": fixture("templates.index.zh.json"),
            "image_qwen_image_2_1_image_edit.json": copy.deepcopy(QWEN),
        }
        state.pack_templates = fixture("workflow_templates.json")
        state.manager = "V4.2.1"
        state.manager_installed = fixture("manager.installed.json")
        state.manager_mappings = fixture("manager.getmappings.json")
        state.registry = fixture("registry.json")
        #: 模型库那份数据(`/experiment/models/<目录>`):和夹具里加载节点的下拉一致
        state.model_folders = {
            "checkpoints": ["sd_xl_base_1.0.safetensors", "illustrious/waiNSFW_v140.safetensors", "flux1-dev-fp8.safetensors"],
            "loras": ["add_detail.safetensors", "pony/ponyStyle_pdxl.safetensors", "flux/flux_realism_lora.safetensors"],
            "diffusion_models": ["qwen_image_2.1_fp8_e4m3fn.safetensors"],
            "text_encoders": ["qwen3vl_8b_int8_convrot.safetensors"],
            "vae": ["qwen/qwen_image_2.1_vae_bf16.safetensors", "ae.safetensors"],
            "controlnet": ["control_v11p_sd15_canny.safetensors"],
        }
        yield server


@pytest.fixture
def plugin(monkeypatch, comfy):
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import main
        import node_packs
        from comfy_http import Comfy

        monkeypatch.setattr(node_packs, "REGISTRY", f"{comfy.url}/registry")

        def call(op: str, locale: str = "zh", **payload: Any) -> dict[str, Any]:
            return main._generation({"op": op, **payload}, Comfy(comfy.url, locale), locale)

        yield call
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _gets(server: FakeComfyUI, path: str) -> int:
    return sum(1 for method, called, _ in server.state.calls if method == "GET" and called == path)


# --- 一张图在智能体眼里 ------------------------------------------------------------------

def test_画布摘要_每一层的节点_控件的值_谁连着谁_子图的口_只问图里那几类(plugin, comfy) -> None:
    out = plugin("canvas_summary", content=QWEN)
    root, inner = out["layers"]
    nodes = {one["ref"]: one for one in root["nodes"]}
    instance = nodes["459"]
    assert instance["type"] == "subgraph" and instance["subgraph"] == "Image Edit (Qwen Image 2.1)"
    assert instance["subgraph_id"] == SUB
    assert instance["widgets"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors", "提升出来的控件按名字"
    assert instance["widgets"]["steps"] == 25
    assert instance["in"] == {"images.image_1": "470.IMAGE", "images.image_2": "475.IMAGE"}
    assert nodes["461"]["in"] == {"images": "459.IMAGE"}
    assert nodes["470"]["widgets"] == {"image": "portrait_model_denim.png"}
    assert nodes["463"]["title"] == "Note: Usage" and nodes["463"]["widgets"]["text"].startswith("## Size")
    assert inner["layer"] == "subgraph" and inner["id"] == SUB and inner["instances"] == ["459"]
    assert "unet_name" in inner["inputs"] and inner["outputs"] == ["IMAGE"]
    loader = next(one for one in inner["nodes"] if one["type"] == "UNETLoader")
    assert loader["ref"] == "459:451", "子图里的节点按从根图往里走的写法"
    assert loader["in"] == {"unet_name": "@in.unet_name"}, "接在子图输入口上的"
    sampler = next(one for one in inner["nodes"] if one["type"] == "KSampler")
    assert sampler["in"]["model"].startswith("459:") and "steps" not in sampler.get("widgets", {}), "连了线的那一格不报存着的值"
    assert out["missing_types"] == [] and out["node_count"] == len(QWEN["nodes"]) + len(QWEN["definitions"]["subgraphs"][0]["nodes"])
    assert _gets(comfy, "/object_info") == 0, "不为一张图取整份节点定义"
    assert any(called.startswith("/object_info/") for _, called, _ in comfy.state.calls)
    assert len(json.dumps(out)) < len(json.dumps(QWEN)) / 4, "摘要不是原文"


# --- 诊断 ---------------------------------------------------------------------------------

def _graph(nodes: list[dict[str, Any]], links: list[list[Any]], **extra: Any) -> dict[str, Any]:
    return {"nodes": nodes, "links": links, **extra}


def _node(node_id: int, kind: str, widgets: list[Any] | None = None, inputs: list[dict[str, Any]] | None = None,
          outputs: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {"id": node_id, "type": kind, "widgets_values": widgets or [], "inputs": inputs or [], "outputs": outputs or [],
            "mode": 0, **extra}


def _in(name: str, kind: str, link: int | None = None, widget: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "type": kind, "link": link}
    if widget:
        entry["widget"] = {"name": name}
    return entry


def _txt2img(ckpt: str = "sd_xl_base_1.0.safetensors", *, width: int = 1024, steps: int = 20,
             sampler: str = "euler") -> dict[str, Any]:
    """一张最普通的文生图:4 读大模型、6/7 写提示词、5 画布、3 采样、8 解码、9 存图。"""
    return _graph(
        [
            _node(4, "CheckpointLoaderSimple", [ckpt], outputs=[{"name": "MODEL", "type": "MODEL"}, {"name": "CLIP", "type": "CLIP"},
                                                                 {"name": "VAE", "type": "VAE"}]),
            _node(6, "CLIPTextEncode", ["a cat"], [_in("clip", "CLIP", 3)], [{"name": "CONDITIONING", "type": "CONDITIONING"}]),
            _node(7, "CLIPTextEncode", ["blurry"], [_in("clip", "CLIP", 4)], [{"name": "CONDITIONING", "type": "CONDITIONING"}]),
            _node(5, "EmptyLatentImage", [width, 1024, 1], outputs=[{"name": "LATENT", "type": "LATENT"}]),
            _node(3, "KSampler", [42, "fixed", steps, 7.0, sampler, "normal", 1.0],
                  [_in("model", "MODEL", 1), _in("positive", "CONDITIONING", 5), _in("negative", "CONDITIONING", 6),
                   _in("latent_image", "LATENT", 7)], [{"name": "LATENT", "type": "LATENT"}]),
            _node(8, "VAEDecode", [], [_in("samples", "LATENT", 8), _in("vae", "VAE", 9)], [{"name": "IMAGE", "type": "IMAGE"}]),
            _node(9, "SaveImage", ["out"], [_in("images", "IMAGE", 10)]),
        ],
        [[1, 4, 0, 3, 0, "MODEL"], [3, 4, 1, 6, 0, "CLIP"], [4, 4, 1, 7, 0, "CLIP"], [5, 6, 0, 3, 1, "CONDITIONING"],
         [6, 7, 0, 3, 2, "CONDITIONING"], [7, 5, 0, 3, 3, "LATENT"], [8, 3, 0, 8, 0, "LATENT"], [9, 4, 2, 8, 1, "VAE"],
         [10, 8, 0, 9, 0, "IMAGE"]],
    )


def _kinds(out: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(one["ref"], one["kind"], one.get("input", "")) for one in out["findings"]]


def test_一张好图没有问题(plugin) -> None:
    out = plugin("check_graph", content=_txt2img())
    assert out["findings"] == [] and out["counts"] == {"error": 0, "warning": 0} and out["checked_nodes"] == 7


def test_缺的节点类型_带上哪个节点包能补_装没装(plugin) -> None:
    graph = _txt2img()
    graph["nodes"].append(_node(20, "WanVideoSampler", []))
    graph["nodes"].append(_node(21, "WanVideoSampler", []))
    graph["nodes"].append(_node(22, "Note", ["只在前端"]))
    out = plugin("check_graph", content=graph)
    assert _kinds(out) == [("20", "missing_type", "")]
    finding = out["findings"][0]
    assert finding["refs"] == ["20", "21"] and "2 处" in finding["cause"]
    assert "WanVideoWrapper" in finding["fix"] and "已装" in finding["fix"], "Manager 的映射:哪个包提供它、装着没有"


def test_缺的模型_同名文件在别的子目录就说改成哪个_没有就带下载地址(plugin) -> None:
    graph = _txt2img(ckpt="waiNSFW_v140.safetensors")
    out = plugin("check_graph", content=graph)
    assert _kinds(out) == [("4", "missing_model", "ckpt_name")]
    assert "illustrious/waiNSFW_v140.safetensors" in out["findings"][0]["fix"]
    graph = _txt2img(ckpt="juggernaut.safetensors")
    graph["nodes"][0]["properties"] = {"models": [{"name": "juggernaut.safetensors", "directory": "checkpoints",
                                                   "url": "https://huggingface.co/x/y/resolve/main/juggernaut.safetensors"}]}
    out = plugin("check_graph", content=graph)
    assert "https://huggingface.co/x/y/resolve/main/juggernaut.safetensors" in out["findings"][0]["fix"]
    assert out["findings"][0]["severity"] == "error"


def test_连线类型对不上(plugin) -> None:
    graph = _txt2img()
    graph["links"][5] = [7, 4, 1, 3, 3, "CLIP"]  # 把 CLIP 接到了 latent_image 上
    out = plugin("check_graph", content=graph)
    assert ("3", "link_type_mismatch", "latent_image") in _kinds(out)
    finding = next(one for one in out["findings"] if one["kind"] == "link_type_mismatch")
    assert "LATENT" in finding["cause"] and "CLIP" in finding["cause"] and "#4" in finding["cause"]


def test_必填的插口没连_上游被静音的说清楚(plugin) -> None:
    graph = _txt2img()
    graph["nodes"][5]["inputs"][1]["link"] = None  # VAEDecode 的 vae 没连
    graph["links"] = [link for link in graph["links"] if link[0] != 9]
    out = plugin("check_graph", content=graph)
    assert ("8", "unconnected_required", "vae") in _kinds(out)
    graph = _txt2img()
    graph["nodes"][4]["mode"] = 2  # 采样被静音:解码那一格接着它,等于没连
    out = plugin("check_graph", content=graph)
    finding = next(one for one in out["findings"] if one["ref"] == "8")
    assert finding["kind"] == "unconnected_required" and "#3" in finding["cause"] and "静音" in finding["cause"]


def test_下拉值不在列表里_数值超出范围_尺寸不是倍数(plugin) -> None:
    out = plugin("check_graph", content=_txt2img(sampler="euler_magic", steps=0, width=1001))
    assert ("3", "combo_not_in_list", "sampler_name") in _kinds(out)
    assert ("3", "number_out_of_range", "steps") in _kinds(out)
    size = next(one for one in out["findings"] if one["kind"] == "size_not_multiple")
    assert (size["ref"], size["input"], size["severity"]) == ("5", "width", "warning")
    assert "8 的倍数" in size["cause"] and "1000" in size["cause"]
    assert out["counts"] == {"error": 2, "warning": 1}
    assert [one["severity"] for one in out["findings"]] == ["error", "error", "warning"], "严重的排前面"


def _with_lora(graph: dict[str, Any], lora: str) -> dict[str, Any]:
    graph["nodes"].append(_node(10, "LoraLoader", [lora, 1.0, 1.0], [_in("model", "MODEL", 20), _in("clip", "CLIP", 21)],
                                [{"name": "MODEL", "type": "MODEL"}, {"name": "CLIP", "type": "CLIP"}]))
    graph["links"] += [[20, 4, 0, 10, 0, "MODEL"], [21, 4, 1, 10, 1, "CLIP"]]
    graph["links"][0] = [1, 10, 0, 3, 0, "MODEL"]
    return graph


def test_底模家族对不上_LoRA_和_ControlNet_同一家的几支不算(plugin) -> None:
    out = plugin("check_graph", content=_with_lora(_txt2img(), "flux/flux_realism_lora.safetensors"))
    assert _kinds(out) == [("10", "family_mismatch", "lora_name")]
    assert "Flux" in out["findings"][0]["cause"] and "SDXL" in out["findings"][0]["cause"]
    assert out["findings"][0]["severity"] == "warning"
    out = plugin("check_graph", content=_with_lora(_txt2img(), "pony/ponyStyle_pdxl.safetensors"))
    assert out["findings"] == [], "Pony 是 SDXL 上的一支"
    graph = _txt2img()
    graph["nodes"].append(_node(11, "ControlNetLoader", ["control_v11p_sd15_canny.safetensors"],
                                outputs=[{"name": "CONTROL_NET", "type": "CONTROL_NET"}]))
    out = plugin("check_graph", content=graph)
    assert _kinds(out) == [("11", "family_mismatch", "control_net_name")] and "SD 1.5" in out["findings"][0]["cause"]


def test_读素材的那一格要的文件不在_input_里(plugin) -> None:
    graph = _txt2img()
    graph["nodes"].append(_node(12, "LoadImage", ["portrait.png", "image"], outputs=[{"name": "IMAGE", "type": "IMAGE"}]))
    out = plugin("check_graph", content=graph)
    assert _kinds(out) == [("12", "missing_input_file", "image")]


def test_子图里的问题带上在哪个子图_用到它的节点_新式节点的特殊输入不误报(plugin) -> None:
    out = plugin("check_graph", content=QWEN)
    kinds = _kinds(out)
    assert ("459:451", "missing_model", "unet_name") in kinds, "子图里的加载节点(值是外面那个节点上提升出来的)"
    assert ("459:477", "missing_model", "clip_name") in kinds
    assert ("470", "missing_input_file", "image") in kinds and ("475", "missing_input_file", "image") in kinds
    finding = next(one for one in out["findings"] if one["ref"] == "459:451")
    assert finding["subgraph"] == {"id": SUB, "name": "Image Edit (Qwen Image 2.1)", "instances": ["459"]}
    assert "huggingface.co/Comfy-Org/Qwen-Image-2.1" in finding["fix"]
    vae = [one for one in out["findings"] if one.get("input") == "vae_name"]
    assert vae and "qwen/qwen_image_2.1_vae_bf16.safetensors" in vae[0]["fix"], "同一个文件在子目录里:说改成哪个"
    assert not [one for one in kinds if one[1] in ("link_type_mismatch", "unconnected_required")], \
        "MATCHTYPE / AUTOGROW / DYNAMICCOMBO 照它们自己的规矩看"


def test_子图里连错了线_报在子图里那个节点上(plugin) -> None:
    graph = copy.deepcopy(QWEN)
    definition = graph["definitions"]["subgraphs"][0]
    sampler = next(one for one in definition["nodes"] if one["type"] == "KSampler")
    vae = next(one for one in definition["nodes"] if one["type"] == "VAELoader")
    link = next(one for one in definition["links"] if one["target_id"] == sampler["id"] and one["target_slot"] == 0)
    link.update(origin_id=vae["id"], origin_slot=0, type="VAE")
    out = plugin("check_graph", content=graph)
    finding = next(one for one in out["findings"] if one["kind"] == "link_type_mismatch")
    assert finding["ref"] == f"459:{sampler['id']}" and finding["input"] == "model"
    assert finding["subgraph"]["name"] == "Image Edit (Qwen Image 2.1)"


def test_上一次运行的报错拆到节点(plugin) -> None:
    graph = _txt2img()
    error = ("ComfyUI 拒绝了这张工作流:Prompt outputs failed validation; #3 Value not in list: sampler_name: 'x' not in [...]; "
             "#8 Required input is missing: vae")
    out = plugin("check_graph", content=graph, error=error)
    found = {one["ref"]: one for one in out["findings"] if one["kind"] == "last_run_error"}
    assert set(found) == {"3", "8"}
    assert "Value not in list" in found["3"]["cause"] and "下拉里换成已有的" in found["3"]["fix"]
    out = plugin("check_graph", content=graph, error="ComfyUI 执行失败:KSampler: CUDA out of memory. Tried to allocate 2 GiB")
    finding = next(one for one in out["findings"] if one["kind"] == "last_run_error")
    assert finding["ref"] == "3" and "显存不够" in finding["fix"]
    out = plugin("check_graph", content=graph,
                 error="Model in folder 'checkpoints' with filename 'sd_xl_base_1.0.safetensors' not found.")
    assert [one["ref"] for one in out["findings"] if one["kind"] == "last_run_error"] == ["4"]
    out = plugin("check_graph", content=QWEN, error="#459:458 KSampler: Expected all tensors to be on the same device")
    finding = next(one for one in out["findings"] if one["kind"] == "last_run_error")
    assert finding["ref"] == "459:458" and finding["subgraph"]["instances"] == ["459"], "子图里的节点按 12:5 的写法"
    out = plugin("check_graph", content=graph, error="something odd happened")
    assert [(one["ref"], one["kind"]) for one in out["findings"]] == [("", "last_run_error")], "认不出节点就整句交回"


def test_英文界面说英文(plugin) -> None:
    out = plugin("check_graph", locale="en", content=_txt2img(sampler="euler_magic"))
    assert out["findings"][0]["cause"].startswith("“sampler_name”")


# --- 模板 -----------------------------------------------------------------------------------

def test_找模板_按任务模型关键词_带要的模型在不在_同款_缺的_多大_要哪一版(plugin, comfy) -> None:
    out = plugin("templates", query="qwen image 2.1 edit")
    first = out["templates"][0]
    assert first["name"] == "image_qwen_image_2_1_image_edit"
    assert first["title"] == "Qwen Image 2.1：图像编辑" and first["title_en"] == "Qwen Image 2.1: Image Edit", "界面语言的译文"
    assert first["task"] == "Image Edit" and first["min_comfyui"] == "0.37.0" and first["version_ok"] is False, \
        "假服务器是 0.3.60:不够"
    assert first["size"] == 26736171418
    models = {one["name"]: one for one in first["models"]}
    assert models["qwen3vl_8b_int8_convrot.safetensors"]["present"] is True
    assert models["qwen_image_2.1_vae_bf16.safetensors"]["found_as"] == "qwen/qwen_image_2.1_vae_bf16.safetensors"
    assert models["qwen_image_2.1_int8_convrot.safetensors"]["alternative"] == "qwen_image_2.1_fp8_e4m3fn.safetensors"
    assert first["missing"] == ["qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors"]
    assert models["qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors"]["url"].startswith("https://huggingface.co/")
    assert out["total"] == 5 and _gets(comfy, "/object_info") == 0
    en = plugin("templates", locale="en", task="Image Edit")
    assert [one["name"] for one in en["templates"]] == ["image_qwen_image_2_1_image_edit"]
    assert en["templates"][0]["title"] == "Qwen Image 2.1: Image Edit"
    assert plugin("templates", model="z-image")["templates"][0]["name"] == "image_z_image_turbo"
    packs = plugin("templates", query="faceid")["pack_templates"]
    assert {"pack": "comfyui_ipadapter_plus", "name": "ipadapter_faceid"} in packs, "节点包自带的模板一并列"


def test_模板索引按模板包的版本记着(plugin, comfy, monkeypatch) -> None:
    import tests.fake_comfyui as fake

    monkeypatch.setitem(fake.SYSTEM_STATS["system"], "installed_templates_version", "0.11.76")
    plugin("templates", query="qwen")
    plugin("templates", query="flux")
    assert _gets(comfy, "/templates/index.mcp.json") == 1, "第二次不再取三份索引"
    monkeypatch.setitem(fake.SYSTEM_STATS["system"], "installed_templates_version", "0.11.80")
    plugin("templates", query="qwen")
    assert _gets(comfy, "/templates/index.mcp.json") == 2, "模板包升级了就重取"


def test_取一张模板_照这台机器改好能改的_说改了什么_缺的说多大_不编文件(plugin, monkeypatch) -> None:
    import templates

    asked: list[str] = []

    class Answer:
        status = 302
        headers = {"x-linked-size": "9663676416"}

    def follow(url: str, **_: Any) -> Answer:
        asked.append(url)
        return Answer()

    monkeypatch.setattr(templates.sources, "follow", follow)
    out = plugin("template", name="image_qwen_image_2_1_image_edit")
    models = {one["name"]: one for one in out["models"]}
    assert models["qwen_image_2.1_vae_bf16.safetensors"] == {
        "name": "qwen_image_2.1_vae_bf16.safetensors", "folder": "vae", "node_type": "VAELoader", "input": "vae_name",
        "status": "adapted", "use": "qwen/qwen_image_2.1_vae_bf16.safetensors"}
    assert models["qwen_image_2.1_int8_convrot.safetensors"]["use"] == "qwen_image_2.1_fp8_e4m3fn.safetensors"
    assert models["qwen3vl_8b_int8_convrot.safetensors"]["status"] == "present"
    missing = models["qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors"]
    assert missing["status"] == "missing" and missing["size"] == 9663676416 and out["missing_size"] == 9663676416
    assert asked == [missing["url"]], "只问缺的那几个有多大"
    assert len(out["changes"]) == 2 and any("qwen/qwen_image_2.1_vae_bf16.safetensors" in one for one in out["changes"])
    graph = out["workflow"]
    instance = next(one for one in graph["nodes"] if one["id"] == 459)
    assert "qwen/qwen_image_2.1_vae_bf16.safetensors" in instance["widgets_values"], "提升到外面那个节点上的值也改了"
    assert "qwen_image_2.1_fp8_e4m3fn.safetensors" in instance["widgets_values"]
    text = json.dumps(graph)
    assert "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors" in text, "缺的照旧缺着,不编一个文件名"
    unet = next(one for one in graph["definitions"]["subgraphs"][0]["nodes"] if one["type"] == "UNETLoader")
    assert unet["properties"].get("models") == [], "换成另一种精度:为旧文件声明的下载去掉"
    vae = next(one for one in graph["definitions"]["subgraphs"][0]["nodes"] if one["type"] == "VAELoader")
    assert vae["properties"]["models"][0]["name"] == "qwen_image_2.1_vae_bf16.safetensors", "只是换了子目录:声明照旧"
    assert out["summary"]["layers"][1]["instances"] == ["459"] and out["missing_types"] == []
    assert out["title"] == "Qwen Image 2.1：图像编辑"


def test_没有这张模板_名字不对(plugin) -> None:
    from lines import ComfyError

    with pytest.raises(ComfyError, match="没有模板"):
        plugin("template", name="no_such_template")
    with pytest.raises(ComfyError, match="不是一个模板名"):
        plugin("template", name="../etc/passwd")


# --- 节点类型 ---------------------------------------------------------------------------------

def test_节点类型_一类一类问_或者在全部里找_全部的那份记着_变了才重取(plugin, comfy) -> None:
    out = plugin("node_types", classes=["KSampler", "NoSuchNode"])
    assert out["unknown"] == ["NoSuchNode"]
    sampler = out["types"][0]
    assert sampler["pack"] == "core" and sampler["outputs"] == [{"name": "LATENT", "type": "LATENT"}]
    inputs = {one["name"]: one for one in sampler["inputs"]}
    assert inputs["model"] == {"name": "model", "type": "MODEL", "required": True}
    assert inputs["steps"]["min"] == 1 and inputs["steps"]["default"] == 20
    assert "euler" in inputs["sampler_name"]["options"] and inputs["sampler_name"]["options_count"] > 30
    assert _gets(comfy, "/object_info") == 0

    found = plugin("node_types", query="lora loader")
    assert found["types"][0]["type"] == "LoraLoader", "名字连起来就是它"
    assert _gets(comfy, "/object_info") == 1
    plugin("node_types", query="switch")
    assert _gets(comfy, "/object_info") == 1, "记着的那份:先问一句多大(HEAD),没变不重取"
    assert any(method == "HEAD" and path == "/object_info" for method, path, _ in comfy.state.calls)
    comfy.state.object_info["NewlyInstalled"] = copy.deepcopy(comfy.state.object_info["KSampler"])
    assert plugin("node_types", query="newlyinstalled")["types"][0]["type"] == "NewlyInstalled"
    assert _gets(comfy, "/object_info") == 2, "装了新的节点(大小变了)就重取"


# --- 节点包 -----------------------------------------------------------------------------------

def test_装了哪些节点包_图里每个节点来自哪个包(plugin) -> None:
    graph = _txt2img()
    graph["nodes"].append(_node(30, "Any Switch (rgthree)", []))
    graph["nodes"].append(_node(31, "WanVideoSampler", []))
    out = plugin("node_packs", content=graph)
    packs = {one["id"]: one for one in out["packs"]}
    assert packs["rgthree-comfy"]["version"] == "1.0.2607232129" and packs["rgthree-comfy"]["source"] == "registry"
    assert packs["rgthree-comfy"]["node_count"] == 24
    manager = next(one for one in out["packs"] if one["folder"] == "ComfyUI-Manager")
    assert manager["source"] == "registry" and manager["enabled"] is True
    te = next(one for one in out["packs"] if one["folder"] == "TE_MAN")
    assert te["source"] == "git" and te["repository"] == "https://github.com/tl2012tl/TE_MAN"
    nodes = {one["type"]: one for one in out["graph_nodes"]}
    assert nodes["Any Switch (rgthree)"] == {"type": "Any Switch (rgthree)", "refs": ["30"], "pack": "rgthree-comfy"}
    assert nodes["KSampler"]["pack"] == "core"
    assert nodes["WanVideoSampler"]["missing"] is True and "ComfyUI-WanVideoWrapper" in nodes["WanVideoSampler"]["offered_by"]


def test_找节点包_关键词查注册表_缺的节点类型先查映射_装了的标出来(plugin) -> None:
    out = plugin("node_pack_search", query="rgthree")
    ids = [one["id"] for one in out["packs"]]
    assert ids[0] == "rgthree-comfy", "下载量、星数排前面"
    first = out["packs"][0]
    assert first["installed"] == "1.0.2607232129" and first["publisher"] == "rgthree", "搜索结果里只有发布者的 id"
    assert first["license"] == "见仓库的 LICENSE"
    out = plugin("node_pack_search", node_types=["Any Switch (rgthree)", "WanVideoSampler"])
    by_id = {one["id"]: one for one in out["packs"]}
    assert by_id["rgthree-comfy"]["provides"] == ["Any Switch (rgthree)"], "nodename_pattern 认出来的"
    assert by_id["ComfyUI-WanVideoWrapper"]["provides"] == ["WanVideoSampler"]
    assert by_id["ComfyUI-WanVideoWrapper"]["installed"] == "1.4.7"
    assert by_id["ComfyUI-WanVideoWrapper"]["registry"] is False, "注册表里没查到:照映射里说"


def test_分析节点包_最新一版被标记_装着的是哪一版_之后改了什么(plugin) -> None:
    out = plugin("node_pack_info", id="rgthree-comfy")
    assert out["newest_version"] == {"version": "1.0.2610050029", "status": "NodeVersionStatusFlagged", "deprecated": False,
                                     "date": "2026-10-05"}
    assert out["flagged_versions"] == 3 and out["install_version"] == "1.0.2608210019"
    assert out["installed"]["version"] == "1.0.2607232129"
    assert out["installed"]["newer_versions"][:4] == ["1.0.2610050029", "1.0.2608312342", "1.0.2608272350", "1.0.2608210019"]
    assert out["downloads"] == 4137189 and out["stars"] == 3535 and out["dependency_risk"] == "low"
    assert out["publisher"] == "Regis Gaughan, III (rgthree)" and out["updated"] == "2026-08-21"
    assert any("Flagged" in line and "1.0.2608210019" in line for line in out["advice"])
    graph = _txt2img()
    graph["nodes"].append(_node(30, "Fast Groups Muter (rgthree)", []))
    graph["nodes"].append(_node(31, "Image Comparer (rgthree)", []))
    out = plugin("node_pack_info", id="RGThree-Comfy", content=graph)
    assert out["id"] == "rgthree-comfy", "大小写不一样:注册表跳到规范的那个"
    assert out["fills_missing"] == ["Image Comparer (rgthree)"], "只在前端的那几个不算缺"


def test_分析节点包_依赖直接有_torch_是高风险_封禁的不要装(plugin) -> None:
    out = plugin("node_pack_info", id="comfyui-sharpfin")
    assert out["dependency_risk"] == "high" and out["torch_touching"] == ["torch>=2.4.0", "torchvision>=0.19.0"]
    assert any("PyTorch" in line for line in out["advice"])
    out = plugin("node_pack_info", id="comfyui-reactor-node")
    assert out["newest_version"]["status"] == "NodeVersionStatusBanned"
    assert any("封禁" in line and "不要装" in line for line in out["advice"])
    from lines import ComfyError

    with pytest.raises(ComfyError, match="注册表里没有"):
        plugin("node_pack_info", id="no-such-pack")


def test_依赖风险_和这台机器合不合(plugin) -> None:
    import node_packs

    assert node_packs.dependency_risk(["numpy", "Pillow"]) == ("low", [])
    assert node_packs.dependency_risk(["open-clip-torch>=2.24.0", "numpy"]) == ("medium", ["open-clip-torch>=2.24.0"])
    assert node_packs.dependency_risk(["xformers==0.0.30; platform_system == 'Linux'"])[0] == "high"
    assert node_packs._os_ok([], "win32") is True and node_packs._os_ok(["OS Independent"], "darwin") is True
    assert node_packs._os_ok(["Microsoft :: Windows"], "darwin") is False
    assert node_packs._os_ok(["POSIX :: Linux", "Microsoft :: Windows"], "linux") is True
    assert node_packs._accelerator_ok(["GPU :: NVIDIA CUDA"], "mps", "2.14.1") is False
    assert node_packs._accelerator_ok(["GPU :: NVIDIA CUDA"], "cuda", "2.9.1+cu130") is True
    assert node_packs._accelerator_ok(["GPU :: AMD ROCm"], "cuda", "2.9.1+rocm6.3") is True
    assert node_packs._comfy_ok(">=0.33.0", "0.39.0") is True and node_packs._comfy_ok(">=0.40.0", "0.39.0") is False
    assert node_packs._comfy_ok("", "0.39.0") is True


def test_去注册表走这个连接的出站代理(plugin, comfy, monkeypatch) -> None:
    """注册表是公网:和下载模型同一条出站路(宿主注入的 HTTP(S)_PROXY)。这里把注册表写成一个解析不了的名字,只有经代理
    (就是那台假服务器)才问得到。"""
    import node_packs

    import importlib

    import sources

    monkeypatch.setattr(node_packs, "REGISTRY", "http://registry.test/registry")
    monkeypatch.setenv("HTTP_PROXY", comfy.url)
    monkeypatch.setenv("http_proxy", comfy.url)
    importlib.reload(sources)  # 插件进程起来时就拿到了宿主注入的环境;这里补一次
    out = plugin("node_pack_info", id="comfyui-sharpfin")
    assert out["id"] == "comfyui-sharpfin"
