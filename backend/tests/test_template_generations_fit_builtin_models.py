"""官方模板里**每一次生成**的参数和素材组合,拿到模板会挑中的每一个内置模型上,用生成漏斗提交前的同一个函数
(`validate_against_capabilities`)校验一遍。

此前的模板测试只看引用指不指得到东西,从不把"这一步到底会给模型交什么"拿去对模型的能力表。于是「商品图 → 模特
上身图」的视频那一步对**每一个**内置视频模型都必败,而测试断言的恰恰就是那个错的组合(首帧 + 参考图):Seedance 2 /
MiniMax 两组互斥,Wan / Kling / Seedance 1.x 不收参考图,Veo 不收 5 秒。

哪些模型"会被挑中",用的是模板建图时挑模型的同一套判据(`_can_take_references` / `_can_shoot_from_references`),
不在这里另写一份名单。每一步按运行时会出现的几种走法各校验一次:整片生成的一镜走首帧还是走参考、有没有尾帧。
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.domain.generation.catalog import known_capabilities_for
from app.domain.generation.descriptors.builtin import BUILTIN_MODELS
from app.domain.generation.operations import keep_source_group, parse_source_assets, validate_against_capabilities
from app.domain.workflows.executors.basic import json_extract
from app.domain.workflows.graph_rules import interpolate
from app.domain.workflows.templates import ModelChoice, full_video_generation_graph
from app.domain.workflows.templates_business import (
    fabric_lookbook_graph,
    product_on_model_graph,
    product_pitch_short_graph,
)
from app.domain.workflows.templates_models import (
    FRAME_ASPECTS,
    REFERENCE_IMAGES_NEEDED,
    SINGLE_REFERENCE,
    _can_shoot_from_references,
    _can_take_references,
    _video_plan,
)

CHAT = ModelChoice(profile_id="chat", provider="openai", model="chat-model")
SEEDREAM = ModelChoice(profile_id="image", provider="bytedance", model="doubao-seedream-4-0-250828")
SEEDANCE = ModelChoice(profile_id="video", provider="bytedance", model="doubao-seedance-2-0-260128")


def _choices(kind: str, usable) -> list[ModelChoice]:
    return [
        ModelChoice(profile_id=kind, provider=one["provider"], model=one["model"])
        for one in BUILTIN_MODELS
        if one["kind"] == kind and usable(None, ModelChoice(provider=one["provider"], model=one["model"]))
    ]


#: 挑模型的判据(templates_models)排掉了拍不了一镜的模型(说话照片、改口型、改视频、续写视频)、参考图收不下一整组的
#: (kling-v3-omni 只收 4 张)、首帧那条路注定被 requires_source 拒的(wan2.7-r2v),`_image_plan` 也认得「1:1」这种
#: 尺寸写法了 —— 此前这几处在这里挂着 strict xfail,现在每个会被挑中的模型都该真的通过。
def _video_params() -> list[Any]:
    return [pytest.param(choice, id=f"{choice.provider}/{choice.model}")
            for choice in _choices("video", _can_shoot_from_references)]


def _image_params(needed: int) -> list[Any]:
    """会被挑中的图像模型。门槛按模板来:商品 / 面料每次只带一张(SINGLE_REFERENCE),整片的关键帧带一组。"""
    return [pytest.param(choice, id=f"{choice.provider}/{choice.model}")
            for choice in _choices("image", lambda db, one: _can_take_references(db, one, needed=needed))]


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
    #: 「按画幅取尺寸」只读开始参数,不花钱 —— 真跑一遍,下游拿到的就是运行时那一组尺寸。
    for node in graph["nodes"]:
        if node["type"] == "json_extract":
            top[node["id"]] = json_extract(None, None, interpolate(node["config"], top))
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


def _full_video_walks(video: ModelChoice) -> list[tuple[set[str], dict[str, Any]]]:
    """整片生成一镜的几种走法:走首帧(有 / 没有尾帧),或走参考 —— 只列这个视频模型让分镜选得到的那几种。"""
    plan = _video_plan(None, video)
    walks: list[tuple[set[str], dict[str, Any]]] = []
    if "keyframes" in plan.modes:
        walks.append(({"paint_last_frame"}, {"reference_mode": "keyframes"}))
        if plan.last_frame:
            walks.append((set(), {"reference_mode": "keyframes"}))
    if "references" in plan.modes:
        walks.append(({"paint_first_frame", "paint_last_frame"}, {"reference_mode": "references"}))
    return walks


def _on_model_video_params() -> list[Any]:
    """上身图动起来那一步会挑中的视频模型:参考那条路只交那一张上身图,门槛是 1 张(和建图时同一个判据)。"""
    def usable(db: Any, one: ModelChoice) -> bool:
        return _can_shoot_from_references(db, one, references=SINGLE_REFERENCE)

    return [pytest.param(choice, id=f"{choice.provider}/{choice.model}") for choice in _choices("video", usable)]


def test_只收几张参考图又必须给参考的视频模型_上身图那一步挑得中() -> None:
    """万相 wan2.7-r2v 只收 5 张参考、必须给参考:整片一镜要一整组,它不行;上身图只交一张,它行。
    此前门槛写死整片那一组,它在哪个模板里都挑不中。"""
    r2v = ModelChoice(provider="alibaba", model="wan2.7-r2v")
    assert not _can_shoot_from_references(None, r2v)
    assert _can_shoot_from_references(None, r2v, references=SINGLE_REFERENCE)


@pytest.mark.parametrize("video", _on_model_video_params())
def test_会被挑中的视频模型_收得下上身图动起来那一步(video: ModelChoice) -> None:
    on_model = _business(SEEDREAM, video)["product_on_model"]
    assert _check(_generations(on_model, skipped=set(), item={}), "video") == ["on_model_clip"]


@pytest.mark.parametrize("video", _video_params())
def test_会被挑中的视频模型_收得下整片生成的每一种走法(video: ModelChoice) -> None:
    graph = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=video)
    walks = _full_video_walks(video)
    assert walks, "这个模型一条路都走不了,却被挑来拍整片"
    for skipped, item in walks:
        assert _check(_generations(graph, skipped=skipped, item=item), "video") == ["generate_clip"], item


@pytest.mark.parametrize("image", _image_params(SINGLE_REFERENCE))
def test_会被挑中的图像模型_收得下模板交给它的每一次出图(image: ModelChoice) -> None:
    for template_id, graph in _business(image, SEEDANCE).items():
        assert _check(_generations(graph, skipped=set(), item={}), "image"), template_id


@pytest.mark.parametrize("image", _image_params(REFERENCE_IMAGES_NEEDED))
def test_会被挑中的图像模型_收得下整片生成的每一次出图(image: ModelChoice) -> None:
    graph = full_video_generation_graph(chat=CHAT, image=image, video=SEEDANCE)
    checked = set()
    for skipped, item in _full_video_walks(SEEDANCE):
        checked |= set(_check(_generations(graph, skipped=skipped, item=item), "image"))
    assert checked == {"paint_first_frame", "paint_last_frame", "sheet", "art"}


def _with_aspect(graph: dict[str, Any], aspect: str) -> dict[str, Any]:
    next(node for node in graph["nodes"] if node["type"] == "start")["config"]["params"]["aspect_ratio"] = aspect
    return graph


def _orientation(size: str) -> str:
    text = size.replace("*", "x").replace(":", "x")
    width, height = (int(one) for one in text.split("x", 1))
    return "portrait" if height > width else "landscape" if width > height else "square"


ASPECT_ORIENTATION = {"16:9": "landscape", "9:16": "portrait", "1:1": "square"}


@pytest.mark.parametrize("video", _video_params())
def test_整片改画幅_视频的尺寸跟着画幅走_收不下的画幅只能是模型本来就不收的(video: ModelChoice) -> None:
    """改的只有开始节点的 aspect_ratio 一格。此前万相视频的 size 写死 832*480,改成竖屏照样出横屏;
    模型本来就不收的画幅(Veo 不收 1:1)由运行前检查拦(见下一条),不在这里算失败。"""
    ratios = [str(one) for one in (known_capabilities_for(video.provider, video.model, "video") or {}).get("aspect_ratios") or ()]
    for aspect in FRAME_ASPECTS:
        graph = _with_aspect(full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=video), aspect)
        for skipped, item in _full_video_walks(video):
            generations = _generations(graph, skipped=skipped, item=item)
            clip = next(config for node_id, config in generations if node_id == "generate_clip")
            size = str(clip["parameters"].get("size") or "")
            if size:
                assert _orientation(size) == ASPECT_ORIENTATION[aspect], (aspect, size)
            if clip["parameters"].get("aspect_ratio") == aspect and ratios and aspect not in ratios:
                continue
            _check(generations, "video")
            frames = [config for node_id, config in generations if node_id == "paint_first_frame"]
            assert all(_orientation(str(one["parameters"]["size"])) == ASPECT_ORIENTATION[aspect]
                       for one in frames if one["parameters"].get("size")), aspect


@pytest.mark.parametrize("image", _image_params(SINGLE_REFERENCE))
def test_竖屏成片的出图_尺寸表里有竖屏那一档就用它_不论写成像素还是画幅比(image: ModelChoice) -> None:
    capabilities = known_capabilities_for(image.provider, image.model, "image") or {}
    offers = "size" in (capabilities.get("parameter_keys") or ()) and any(
        _orientation(str(one)) == "portrait" for one in capabilities.get("sizes") or ()
        if re.fullmatch(r"\d+[x*:]\d+", str(one)) and abs(_ratio_of(str(one)) - 9 / 16) < 0.05
    )
    graph = product_pitch_short_graph(chat=CHAT, image=image, voice_id="voice-1")
    frame = next(config for node_id, config in _generations(graph, skipped=set(), item={}) if node_id == "beat_frame")
    size = str(frame["parameters"].get("size") or "")
    assert (_orientation(size) == "portrait") if offers else size == "", (image.model, size)


def _ratio_of(size: str) -> float:
    width, height = (int(one) for one in re.split(r"[x*:]", size, maxsplit=1))
    return width / height


def test_还没挑模型的副本_出图出视频的画幅尺寸照样接在开始参数上() -> None:
    """官网副本(模型留空,由导入的人挑):挑模型时编辑器只留新模型仍收的绑定(前端 carriedParameters)。
    此前这里只有时长 —— 挑了模型之后改开始节点的画幅不起作用,片子按模型的默认画幅出。"""

    def body(graph: dict[str, Any], loop_id: str, node_id: str) -> dict[str, Any]:
        loop = next(node for node in graph["nodes"] if node["id"] == loop_id)
        return next(node for node in loop["config"]["body"]["nodes"] if node["id"] == node_id)["config"]["parameters"]

    blank = ModelChoice()
    full = full_video_generation_graph(chat=blank, image=blank, video=blank)
    #: 时长也接在开始参数上(「每镜秒数」),和画幅、分辨率同一个做法。
    assert body(full, "generate_shots", "generate_clip") == {
        "duration_seconds": "{{input.shot_seconds}}", "aspect_ratio": "{{input.aspect_ratio}}", "resolution": "{{input.resolution}}"}
    assert body(full, "generate_shots", "paint_first_frame") == {"size": "{{input.frame_size}}"}
    on_model = product_on_model_graph(chat=blank, image=blank, video=blank, motion=True)
    assert body(on_model, "shoot_scenes", "on_model_clip")["aspect_ratio"] == "{{input.aspect_ratio}}"
    #: 认得出名字、查不到能力表的模型(用户自建的)不猜它收画幅。
    custom = full_video_generation_graph(chat=blank, image=blank, video=ModelChoice(provider="x", model="my-model"))
    assert body(custom, "generate_shots", "generate_clip") == {"duration_seconds": "{{input.shot_seconds}}"}


@pytest.mark.parametrize("image", _image_params(REFERENCE_IMAGES_NEEDED))
def test_分镜写满上限时_整条首帧尾帧提示词仍在图像模型收得下的字数里(image: ModelChoice) -> None:
    """首帧那条固定的白模说明就有近 500 字,Evolink 的图像模型只收 2000 字:分镜里模型写的那段要按余量封顶。"""
    limit = int((known_capabilities_for(image.provider, image.model, "image") or {}).get("max_prompt_chars") or 0)
    graph = full_video_generation_graph(chat=CHAT, image=image, video=SEEDANCE)
    storyboard = next(node for node in graph["nodes"] if node["id"] == "storyboard")
    shot = storyboard["config"]["json_schema"]["properties"]["shots"]["items"]["properties"]
    if not limit:
        assert "maxLength" not in shot["first_frame_prompt"]
        return
    item = {"reference_mode": "keyframes", "first_frame_prompt": "f" * shot["first_frame_prompt"]["maxLength"],
            "last_frame_prompt": "e" * shot.get("last_frame_prompt", {}).get("maxLength", 1)}
    generations = dict(_generations(graph, skipped=set(), item=item))
    #: 这里画风、白模图例插出来是空的(上游是假的):按一段常见的长度(各 250 字)补上再比。
    for node_id in ("paint_first_frame", "paint_last_frame"):
        if node_id in generations:
            assert len(generations[node_id]["prompt"]) + 2 * 250 <= limit, (node_id, limit)


def test_参数表没有缩水() -> None:
    """扫描面自己也要有人看着:判据哪天一个模型都挑不中,上面两条参数化测试一条都不会跑。"""
    assert len(_choices("video", _can_shoot_from_references)) >= 10
    assert len(_image_params(SINGLE_REFERENCE)) >= 3
