"""我们自己发的插件:节点的输出口说到做到。

没写 `node.outputs` 时,宿主把整份返回装进一个叫 `output` 的口子(见 plugins/nodes.node_meta)。于是:

- 写了 `output_labels` / `output_types` / `board_outputs` / `wiring_outputs` 却没写 `outputs` 的,那些名字**全部落空** ——
  Text Toolkit 和 Remotion 都这么写过:标签对着不存在的口子,下游接不到 `{{n1.asset_id}}`,
  画板上是一张大 JSON 便签;
- 点名落板的(`board_outputs`)和只给连线用的(`wiring_outputs`)不能是同一个口子 —— 两句话打架;
- 交出文件的工具要有一个 `asset` 类型的口子,否则画板认不出它是素材、工作流连不上下一个吃素材的节点。

这条棘轮扫 plugins/examples 与 plugins/bundled 里所有**写死在清单里**的工具,**也扫运行时报出的**:ComfyUI
每张工作流一个工具,清单里没有它们 —— 对着测试用的假 ComfyUI 让插件现报一份。它们还多两条:
画板上落的**只有每个输出节点自己的产出**(第一份 / 全部 id / 摘要 / 任务号是给连线用的,落了就是一张重复的图和
几张 JSON 便签);声明了 `mirrors` 的,说的那个模型就在同一个插件报的模型目录里,入参改名后的键就是它的生成参数。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2] / "plugins"
MANIFESTS = sorted([*ROOT.glob("examples/*/mosael.plugin.json"), *ROOT.glob("bundled/*/mosael.plugin.json")])
#: 交出文件的工具(返回里有 artifact / artifacts)。新加一个交文件的工具就加进来。
PRODUCES_FILES = {
    ("dev.mosael.remotion", "remotion_explainer"), ("dev.mosael.remotion", "remotion_animation"),
    ("dev.mosael.manim", "manim_explainer"), ("dev.mosael.manim", "manim_animation"), ("dev.mosael.manim", "manim_still"),
    ("dev.mosael.object-storage", "storage_fetch"),
}
COMFYUI = ROOT / "bundled" / "comfyui"



def _tools() -> list[tuple[str, dict]]:
    out = []
    for path in MANIFESTS:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        out += [(manifest["id"], tool) for tool in (manifest.get("tools") or {}).get("declare") or []]
    return out


def _check(package: str, tool: dict[str, Any]) -> None:
    node = tool.get("node") or {}
    outputs = node.get("outputs")
    board, wiring = set(node.get("board_outputs") or []), set(node.get("wiring_outputs") or [])
    named = {*(node.get("output_labels") or {}), *(node.get("output_types") or {}), *board, *wiring}
    if named:
        assert isinstance(outputs, list) and outputs, f"{package}.{tool['name']} 给 {sorted(named)} 起了名字,却没写 outputs"
        assert named <= set(outputs), f"{package}.{tool['name']}:{sorted(named - set(outputs))} 不是声明过的输出"
    assert not board & wiring, f"{package}.{tool['name']}:{sorted(board & wiring)} 又点名落板、又说只给连线用"
    if (package, tool["name"]) in PRODUCES_FILES:
        assert (node.get("output_types") or {}).get("asset_id") == "asset", f"{package}.{tool['name']} 交文件,却没有 asset 口子"


@pytest.mark.parametrize(("package", "tool"), _tools(), ids=lambda value: value if isinstance(value, str) else value["name"])
def test_输出的标签类型和画板点名都对得上口子(package: str, tool: dict) -> None:
    _check(package, tool)


def test_运行时报出的工具也说到做到(tmp_path: Path) -> None:
    """ComfyUI 每张工作流一个工具(`op: tools`):对着假 ComfyUI 上几种典型的图(文生图、图生视频、放大 + 预览、
    自定义保存节点、只交出一段字的打标签)让插件现报一份,过同一道棘轮,再加上它自己的两条。"""
    from app.ai.providers.contracts.generation import SOURCE_ROLES
    from app.domain.boards.tools import landing_outputs
    from app.domain.generation.catalog import GENERATION_KINDS
    from app.domain.plugins import runtime
    from app.domain.plugins.dynamic_tools import clean_mirror
    from app.domain.plugins.nodes import node_meta
    from tests.fake_comfyui import UPSCALE_API, FakeComfyUI

    manifest = json.loads((COMFYUI / "mosael.plugin.json").read_text(encoding="utf-8"))
    with FakeComfyUI() as comfy:
        comfy.state.workflows["upscale.json"] = UPSCALE_API
        comfy.state.object_info["SaveImageExtended"] = {"input": {"required": {"images": ["IMAGE"]}}, "output_node": True}
        comfy.state.workflows["custom.json"] = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "12": {"class_type": "SaveImageExtended", "inputs": {"images": ["1", 0]}},
        }
        comfy.state.object_info["WD14Tagger|pysssss"] = {"input": {"required": {"image": ["IMAGE"]}}}
        comfy.state.workflows["tagger.json"] = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "2": {"class_type": "WD14Tagger|pysssss", "inputs": {"image": ["1", 0]}},
            "3": {"class_type": "ShowText|pysssss", "inputs": {"text": ["2", 0]}},
        }
        env = {"SERVER_URL": comfy.url}
        reported = runtime.execute_tool(COMFYUI, "tools/main.py", "comfyui_generation", {"op": "tools"}, env,
                                        data_dir=tmp_path, timeout=60).output["tools"]
        models = {model["id"]: model for model in runtime.execute_tool(
            COMFYUI, "tools/main.py", "comfyui_generation", {"op": "models"}, env, timeout=60).output["models"]}
    assert len(reported) >= 6, [tool["name"] for tool in reported]
    assert "wf_" + hashlib.sha1(b"tagger.json").hexdigest()[:12] in {tool["name"] for tool in reported}
    for tool in reported:
        name = f"{manifest['id']}.{tool['name']}"
        _check(manifest["id"], tool)
        node = tool["node"]
        #: 每个输出节点自己的那个口子(`image_9`、`text_40`、自定义节点的 `output_12`)—— 画板上落的就是这几个。
        per_node = [key for key in node["outputs"] if key.split("_", 1)[0] in ("image", "video", "audio", "text", "output")]
        assert landing_outputs(node_meta(tool)) == per_node, f"{name} 画板上落的不是每个输出节点自己的产出"
        assert {"asset_id", "asset_ids", "summary", "prompt_id"} <= set(node["wiring_outputs"]), name
        mirror = tool.get("mirrors")
        if mirror is None:
            continue
        assert clean_mirror(mirror) == mirror, f"{name} 的 mirrors 形状不对,宿主会整条不认"
        assert mirror["kind"] in GENERATION_KINDS, name
        model = models.get(mirror["generation_model"])
        assert model is not None and model["kind"] == mirror["kind"], f"{name} 说它是模型 {mirror['generation_model']},目录里没有"
        assert set((mirror.get("parameters") or {}).values()) <= set(model["parameters"]), name
        assert set((mirror.get("sources") or {}).values()) <= set(SOURCE_ROLES), name
        assert set(mirror.get("parameters") or {}) | set(mirror.get("sources") or {}) <= set(
            tool["input_schema"]["properties"]), f"{name} 的 mirrors 说的入参不是它的入参"
