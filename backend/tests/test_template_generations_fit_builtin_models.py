"""官方模板里**每一次生成**的参数和素材组合,拿到模板会挑中的每一个内置模型上,用生成漏斗提交前的同一个函数
(`validate_against_capabilities`)校验一遍。

此前的模板测试只看引用指不指得到东西,从不把"这一步到底会给模型交什么"拿去对模型的能力表。于是「商品图 → 模特
上身图」的视频那一步对**每一个**内置视频模型都必败,而测试断言的恰恰就是那个错的组合(首帧 + 参考图):Seedance 2 /
MiniMax 两组互斥,Wan / Kling / Seedance 1.x 不收参考图,Veo 不收 5 秒。

哪些模型"会被挑中",用的是模板建图时挑模型的同一套判据(`_can_take_references` / `_can_shoot_from_references`),
不在这里另写一份名单。每一步按运行时会出现的几种走法各校验一次:整片生成的一镜走首帧还是走参考、有没有尾帧。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.generation.descriptors.builtin import BUILTIN_MODELS
from app.domain.generation.operations import keep_source_group, parse_source_assets, validate_against_capabilities
from app.domain.workflows.graph_rules import interpolate
from app.domain.workflows.templates import ModelChoice
from app.domain.workflows.templates_business import (
    fabric_lookbook_graph,
    product_on_model_graph,
    product_pitch_short_graph,
)
from app.domain.workflows.templates_models import _can_shoot_from_references, _can_take_references

CHAT = ModelChoice(profile_id="chat", provider="openai", model="chat-model")
SEEDREAM = ModelChoice(profile_id="image", provider="bytedance", model="doubao-seedream-4-0-250828")
SEEDANCE = ModelChoice(profile_id="video", provider="bytedance", model="doubao-seedance-2-0-260128")


def _choices(kind: str, usable) -> list[ModelChoice]:
    return [
        ModelChoice(profile_id=kind, provider=one["provider"], model=one["model"])
        for one in BUILTIN_MODELS
        if one["kind"] == kind and usable(None, ModelChoice(provider=one["provider"], model=one["model"]))
    ]


#: 挑模型那一步(templates_models,不归模板管)眼下会挑中、而它们根本拍不了一镜的模型:会「说话照片」「改口型」
#: 「改视频」「续写视频」的那些 —— 它们也收首帧或参考图,判据只看收不收,不看是不是在"从图出片"。
#: 挑模型的判据修好之后,它们不再出现在参数表里,这几行随之失效;在那之前 xfail(strict)记着。
NOT_A_SHOT_MODEL = {"speech-to-video", "video-lipsync", "video-edit", "video-extend"}
#: 同一处的另一个问题:evolink 的图像模型尺寸表里混着「1:1」这种比例写法,`_image_plan` 按「宽x高」拆它时抛错,
#: 用这几个模型建整片 / 带货 / 上身图模板直接失败。
RATIO_SIZES = {"evolink"}


def _video_params() -> list[Any]:
    out = []
    for choice in _choices("video", _can_shoot_from_references):
        spec = next(one for one in BUILTIN_MODELS if one["model"] == choice.model and one["provider"] == choice.provider)
        modes = set(spec["capabilities"].get("modes") or ())
        marks = []
        if modes and modes <= NOT_A_SHOT_MODEL:
            marks.append(pytest.mark.xfail(strict=True, reason="挑模型的判据把不能出一镜的模型也挑了进来(templates_models)"))
        out.append(pytest.param(choice, id=f"{choice.provider}/{choice.model}", marks=marks))
    return out


def _image_params() -> list[Any]:
    out = []
    for choice in _choices("image", _can_take_references):
        marks = []
        if choice.provider in RATIO_SIZES:
            marks.append(pytest.mark.xfail(strict=True, reason="_image_plan 拆不了「1:1」这种尺寸写法(templates_models)"))
        out.append(pytest.param(choice, id=f"{choice.provider}/{choice.model}", marks=marks))
    return out


class _Anything(dict):
    """某个节点的任意一个输出:素材 id 给一个假的;`results`(循环交出的一组参考行)给满额的一组。"""

    def __init__(self, node_id: str, *, results: int = 0, **known: Any) -> None:
        super().__init__(known)
        self.node_id = node_id
        self.results = results

    def get(self, key: Any, default: Any = None) -> Any:
        if dict.__contains__(self, key):
            return super().get(key)
        if key == "results":
            return [f"{self.node_id}-{index}:reference_image" for index in range(self.results)]
        return f"{self.node_id}-{key}"


#: 视觉圣经最多 4 个角色、3 个场景(见整片模板的提示词),参考图按满额算。
FULL_RESULTS = {"character_sheets": 4, "location_art": 3}


def _generations(graph: dict[str, Any], *, skipped: set[str], item: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """图里(连同循环体)每一个生成节点,连同它这一走法下插值好的配置。`skipped` 是这一走法里没跑的节点。"""
    top = {node["id"]: _Anything(node["id"], results=FULL_RESULTS.get(node["id"], 0)) for node in graph["nodes"]}
    start = next(node for node in graph["nodes"] if node["type"] == "start")
    top["start"] = dict(start["config"]["params"])
    found: list[tuple[str, dict[str, Any]]] = []

    def visit(nodes: list[dict[str, Any]], context: dict[str, Any]) -> None:
        for node in nodes:
            config = node.get("config") or {}
            body = config.get("body")
            if isinstance(body, dict) and body.get("nodes"):
                inner = dict(context)
                inner["input"] = interpolate(config.get("inputs") or {}, context)
                inner["loop"] = {"item": _Anything("item", **item), "index": 0}
                for one in body["nodes"]:
                    inner[one["id"]] = {} if one["id"] in skipped else _Anything(one["id"])
                visit(body["nodes"], inner)
            if node["type"] == "ai_generate" and node["id"] not in skipped:
                found.append((node["id"], interpolate(config, context)))

    visit(graph["nodes"], top)
    return found


def _check(generations: list[tuple[str, dict[str, Any]]], kind: str) -> list[str]:
    checked = []
    for node_id, config in generations:
        if config["kind"] != kind:
            continue
        sources = keep_source_group(
            parse_source_assets(config.get("source_assets"), kind=kind), str(config.get("source_group") or "all").strip()
        )
        validate_against_capabilities(config["provider"], config["model"], kind, dict(config.get("parameters") or {}), sources)
        checked.append(node_id)
    return checked


def _business(image: ModelChoice, video: ModelChoice) -> dict[str, dict[str, Any]]:
    return {
        "product_on_model": product_on_model_graph(chat=CHAT, image=image, video=video),
        "product_pitch_short": product_pitch_short_graph(chat=CHAT, image=image, voice_id="voice-1"),
        "product_pitch_presenter": product_pitch_short_graph(chat=CHAT, image=image, presenter=True),
        "fabric_lookbook": fabric_lookbook_graph(chat=CHAT, image=image),
    }


@pytest.mark.parametrize("video", _video_params())
def test_会被挑中的视频模型_收得下上身图动起来那一步(video: ModelChoice) -> None:
    on_model = _business(SEEDREAM, video)["product_on_model"]
    assert _check(_generations(on_model, skipped=set(), item={}), "video") == ["on_model_clip"]


@pytest.mark.parametrize("image", _image_params())
def test_会被挑中的图像模型_收得下模板交给它的每一次出图(image: ModelChoice) -> None:
    for template_id, graph in _business(image, SEEDANCE).items():
        assert _check(_generations(graph, skipped=set(), item={}), "image"), template_id


def test_参数表没有缩水() -> None:
    """扫描面自己也要有人看着:判据哪天一个模型都挑不中,上面两条参数化测试一条都不会跑。"""
    assert len(_choices("video", _can_shoot_from_references)) >= 10
    assert len(_choices("image", _can_take_references)) >= 3
