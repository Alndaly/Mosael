"""内置模板**挑模型**的那几步:按用户的默认设置、按描述符能不能带参考图 / 首帧,选出每一步用哪个模型,
并把它的能力摊成出图 / 出片计划(ImagePlan / VideoPlan)。

模板入口(templates.py)和整片生成那张大图都要用,所以单独一份,放在两者下面。

调用方直接从这个模块取(一个名字只有一个来源,见 tests/test_imports_come_from_where_names_live)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import DRIVING_AUDIO, FIRST_CLIP, FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO
from app.db.models import ProviderModel
from app.domain.generation_catalog import known_capabilities_for
from app.domain.generation.resolution import resolve_row
from app.domain.providers.defaults import get_row
from app.domain.providers.models import effective_capabilities
from app.domain.providers import models as provider_models


@dataclass(frozen=True)
class ModelChoice:
    profile_id: str = ""
    provider: str = ""
    model: str = ""


#: 续写的尾巴留多长。H3 按 17k+5 帧取片段,22 帧正好是 24fps 下的 0.92 秒:写成 1 秒的话多出来的两帧被裁掉。
CONTINUATION_TAIL_SECONDS = 0.92
#: 模型要尾巴至少几秒时多留这一点:按帧截,截出来总比要的短一丝,卡在下限上供应商未必认。
TAIL_MARGIN_SECONDS = 0.1


@dataclass(frozen=True)
class VideoPlan:
    clip_seconds: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    width: int = 1920
    height: int = 1080
    parameters: dict[str, Any] | None = None
    #: 按像素尺寸定画幅的模型(万相 2.2 / 2.5 / 2.6 收 `size`、不收 `aspect_ratio`):每种画幅用尺寸表里哪一档。
    #: 有它时参数里的 size 是 `{{input.video_size}}`,跟着画幅走 —— 此前写死默认的 832*480,改成竖屏照样出横屏。
    sizes: dict[str, str] | None = None
    #: 这个视频模型收哪几种参考(见 _video_plan)。决定分镜里每一镜**能选**哪条路:
    #: 首帧(+尾帧)锁构图,或者参考图/参考视频锁人物与运镜。
    keyframes: bool = True
    last_frame: bool = False
    #: 收待续写的片段(`first_clip`):接着一段视频往下拍,而不只是从一帧动起来。
    extends: bool = False
    #: 交给下一段的尾巴至少几秒(描述符的 `source_duration_seconds`)。没声明就是 0,由模板定。
    shortest_tail: float = 0
    #: 一段最长几秒。续写时每段都有一截是重叠,段越长重叠占的比例越小。没声明就是 0。
    longest_clip: int = 0
    shortest_clip: int = 0
    #: 只有几档固定时长的模型:这几档。
    allowed_clips: tuple[int, ...] = ()
    references: bool = False
    reference_video: bool = False

    @property
    def chains(self) -> bool:
        """一镜比一次能出的长时,这个模型接得下去:知道一次最长多少,又收待续写片段或首帧。"""
        return self.longest_clip > 0 and (self.extends or self.keyframes)

    @property
    def tail_seconds(self) -> float:
        """续写时交给下一段的尾巴多长。只交一帧时没有重叠。"""
        if not self.extends:
            return 0.0
        return self.shortest_tail + TAIL_MARGIN_SECONDS if self.shortest_tail else CONTINUATION_TAIL_SECONDS

    @property
    def modes(self) -> list[str]:
        return [mode for mode, ok in (("keyframes", self.keyframes), ("references", self.references)) if ok]


@dataclass(frozen=True)
class ImagePlan:
    """图像模型的两种尺寸:关键帧(和成片同画幅)、角色三视图(横向,三个视角并排)。认不出的模型不传尺寸。"""

    frame_sizes: dict[str, str]
    sheet_size: str = ""


def _default_model(db: Session, capability: str, user_id: str) -> ModelChoice:
    row = get_row(db, capability, user_id)
    model = db.get(ProviderModel, row.provider_model_id) if row and row.provider_model_id else None
    if model is None or not model.enabled or model.profile is None or not model.profile.enabled:
        return ModelChoice()
    return ModelChoice(
        profile_id=model.provider_profile_id,
        provider=model.profile.vendor,
        model=model.model_id,
    )


def model_capabilities(db: Session | None, choice: ModelChoice, kind: str) -> dict[str, Any] | None:
    """这个模型在这种生成能力下的描述符;认不出返回 None(**不猜**)。

    点了名连接且有库可查时走逐模型解析 —— 用户自定义的声明(见 generation/resolution.py)
    在这条路上生效。纯静态上下文(官网模板导出、不建库的单元测试)传 ``db=None``,
    退回内置目录;连模型名都没有时是空选择,不是"不认识",同样 None。
    """
    if not choice.model:
        return None
    if db is not None and choice.profile_id:
        model = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_profile_id == choice.profile_id,
                ProviderModel.model_id == choice.model,
            )
        )
        if model is not None:
            resolved = resolve_row(db, model, kind)
            return resolved.capabilities if resolved.capabilities_known else None
    return known_capabilities_for(choice.provider, choice.model, kind)


#: 整片生成的关键帧图要同时参考:白模帧 1 张 + 角色三视图最多 4 张 + 场景设定图最多 3 张 + (尾帧时)首帧 1 张。
REFERENCE_IMAGES_NEEDED = 9
#: 商品图、面料图那几条模板:每次出图只带那一张商品 / 面料图。
SINGLE_REFERENCE = 1


def _can_take_references(db: Session | None, choice: ModelChoice, *, needed: int) -> bool:
    """图像模型能不能带着 `needed` 张参考图出图。认不出的算能(用户自建的、查不到能力表的)。

    `needed` 由模板自己说:此前门槛写死 9 张(整片生成的关键帧),商品图 / 面料图模板复用了它 —— 每次只带一张图,
    却把只收 3 张的百炼 qwen-image-edit 判成缺。"""
    capabilities = model_capabilities(db, choice, "image")
    if capabilities is None:
        return bool(choice.model)
    limit = int((capabilities.get("source_limits") or {}).get(REFERENCE_IMAGE) or 0)
    return "image-to-image" in (capabilities.get("modes") or ()) and limit >= needed


def _can_shoot_from_references(db: Session | None, choice: ModelChoice, *, references: int | None = None) -> bool:
    """视频模型能不能从首帧或参考素材出片 —— 这条流程每一镜都给其中之一,从不只给一段文字。

    `references` 是参考那条路一次交几张图,由模板自己说:整片一镜交一整组(SHOT_REFERENCE_IMAGES),上身图动起来
    只交那一张上身图。此前门槛写死整片那一组 —— 只收 5 张、又必须给参考的万相 wan2.7-r2v 永远挑不中。"""
    plan = video_plan_for(db, choice, references=references)
    return bool(choice.model) and (plan.keyframes or plan.references)


def _pick(db: Session, user_id: str, kind: str, usable) -> ModelChoice:
    """默认模型合用就用它(用户自己的选择优先);不合用就在他**已经配好的**模型里挑一个合用的。
    一个都没有时留空 —— 节点上的模型格空着,界面会让他去选,那比塞一个必然失败的进去诚实。"""
    chosen = _default_model(db, kind, user_id)
    if usable(db, chosen):
        return chosen

    for model in provider_models.models_for_capability(db, kind, user_id=user_id):
        if model.profile is None or not model.profile.enabled or kind not in effective_capabilities(model):
            continue
        candidate = ModelChoice(profile_id=model.provider_profile_id, provider=model.profile.vendor, model=model.model_id)
        if usable(db, candidate):
            return candidate
    return ModelChoice()


def _chat_model(db: Session, user_id: str) -> ModelChoice:
    """模板里要对话的那几步用哪个模型。**建图写在节点上的和前置检查问的是同一个**:此前建图用 `_default_model`
    (没设默认就留空),检查用 `_pick`(没默认也挑一个配好的)—— 检查说齐了,建出来的节点却是空的。"""
    return _pick(db, user_id, "chat", lambda _db, choice: bool(choice.model))


def _shot_video_model(db: Session, user_id: str, *, references: int | None = None) -> ModelChoice:
    return _pick(db, user_id, "video", lambda db_, choice: _can_shoot_from_references(db_, choice, references=references))


def _continuation_video_model(db: Session, user_id: str) -> ModelChoice:
    """逐段往下拍用哪个模型:收待续写片段的优先,其次收首帧的。"""
    extends = _pick(db, user_id, "video", lambda db_, choice: FIRST_CLIP in _parameter_keys(db_, choice))
    return extends if extends.model else _pick(db, user_id, "video", lambda db_, choice: FIRST_FRAME in _parameter_keys(db_, choice))


def _opening_video_model(db: Session, user_id: str, *, continuing: ModelChoice) -> ModelChoice:
    """第一段用哪个模型:从一段文字就能出片的,和续写同一家的优先 —— 同一家的画风接得更顺。"""

    def from_text(db_: Session | None, choice: ModelChoice) -> bool:
        return "text-to-video" in ((model_capabilities(db_, choice, "video") or {}).get("modes") or ())

    same_vendor = _pick(db, user_id, "video", lambda db_, choice: choice.provider == continuing.provider and from_text(db_, choice))
    return same_vendor if same_vendor.model else _pick(db, user_id, "video", from_text)


def _talking_video_model(db: Session, user_id: str, *, continuing: bool) -> ModelChoice:
    """数字人长片用哪个模型:都收驱动音频,续写的那条还收上一段的尾巴,第一段的不收。"""

    def usable(db_: Session | None, choice: ModelChoice) -> bool:
        keys = _parameter_keys(db_, choice)
        return DRIVING_AUDIO in keys and (FIRST_CLIP in keys) == continuing

    return _pick(db, user_id, "video", usable)


def _parameter_keys(db: Session | None, choice: ModelChoice) -> list[str]:
    return list((model_capabilities(db, choice, "video") or {}).get("parameter_keys") or ())


def _reference_image_model(db: Session, user_id: str, *, needed: int) -> ModelChoice:
    """能带 `needed` 张参考图出图的图像模型(整片生成传 REFERENCE_IMAGES_NEEDED,商品 / 面料图传 SINGLE_REFERENCE)。"""
    return _pick(db, user_id, "image", lambda db_, choice: _can_take_references(db_, choice, needed=needed))


#: 白模 / 时间线认得的三种画幅,以及每一种的成片画布。
FRAME_ASPECTS: dict[str, tuple[int, int]] = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}

#: 一档尺寸算不算这个画幅:宽高比差多少以内。万相视频的 832*480 是 1.733,和 16:9 的 1.778 差 0.044。
_RATIO_TOLERANCE = 0.05


def _ratio(aspect: str) -> float:
    width, _, height = aspect.partition(":")
    return int(width) / int(height)


def size_for_aspect(sizes: Any, aspect: str, *, pick: str = "smallest", near_area: int = 0, minimum: int = 0) -> str:
    """尺寸表里和这个画幅同比例的那一档,**原样**交出(`832*480` 就是 `832*480`);没有就空串。

    像素写法(`宽x高` / `宽*高`)优先,在同比例的几档里按 `pick` 挑:smallest / largest 按面积,near 挑面积最接近
    `near_area` 的(视频按默认那一档的清晰度挑,不顺手升到 1080p 多花钱)。`minimum` 是模型要求的最小像素数。
    没有像素写法、但表里列着同一个比例的**画幅比写法**(Evolink 的 `9:16`)时,直接交它 —— 此前只认像素写法,
    这类模型的竖屏 / 横屏那一档一律被丢掉,按模型默认出方图。
    """
    target = _ratio(aspect)
    pixel: list[tuple[int, str]] = []
    for raw in sizes or ():
        text = str(raw).strip().lower().replace("*", "x")
        if not re.fullmatch(r"\d+x\d+", text):
            continue
        width, height = (int(value) for value in text.split("x", 1))
        if height and abs(width / height - target) < _RATIO_TOLERANCE and width * height >= minimum:
            pixel.append((width * height, str(raw).strip()))
    if pixel:
        if pick == "near":
            return min(pixel, key=lambda one: abs(one[0] - near_area))[1]
        return sorted(pixel, reverse=pick == "largest")[0][1]
    for raw in sizes or ():
        written = re.fullmatch(r"(\d+):(\d+)", str(raw).strip())
        if written and int(written.group(2)) and abs(int(written.group(1)) / int(written.group(2)) - target) < 0.02:
            return str(raw).strip()
    return ""


def image_plan_for(db: Session | None, choice: ModelChoice) -> ImagePlan:
    """从图像模型的尺寸表里挑:关键帧和成片同画幅,三视图取最宽的横幅。认不出、或不收 `size` 的不传尺寸。"""
    capabilities = model_capabilities(db, choice, "image") or {}
    keys = capabilities.get("parameter_keys")
    #: 声明了参数却不收 size 的(百炼 qwen-image-edit 只收参考图,出图跟着参考图的比例):尺寸表再全也不传。
    sizes = capabilities.get("sizes") if not keys or "size" in keys else ()
    minimum = int(capabilities.get("min_size_pixels") or 0)
    frames = {aspect: size_for_aspect(sizes, aspect, minimum=minimum) for aspect in FRAME_ASPECTS}
    return ImagePlan(
        frame_sizes={aspect: size for aspect, size in frames.items() if size},
        sheet_size=size_for_aspect(sizes, "16:9", pick="largest", minimum=minimum),
    )


#: 整片生成「参考」那条路一镜交几张参考图:角色三视图最多 4 张 + 场景设定图最多 3 张 + 白模帧 1 张。
SHOT_REFERENCE_IMAGES = 8
#: 能从零拍出一镜的模式。说话照片、改口型、改视频、续写视频也收首帧或参考素材,但它们拍不了一镜:
#: 要的是一段现成的音频 / 视频。此前只看参数键,挑中过说话照片模型当镜头模型。
_SHOT_MODES = frozenset({"text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"})
#: 首尾帧那条路、参考那条路各交哪几种素材。
_KEYFRAME_SOURCES = frozenset({FIRST_FRAME, LAST_FRAME})
_REFERENCE_SOURCES = frozenset({REFERENCE_IMAGE, REFERENCE_VIDEO})


def _route_allowed(capabilities: dict[str, Any], sources: frozenset[str]) -> bool:
    """这条路交的素材满不满足模型的 `requires_source`(每一组里至少给一种)。万相 wan2.7-r2v 要求参考图或参考视频
    至少一种:走首尾帧那条路注定被漏斗拒 —— 此前照样把它算成能走首帧。"""
    return all(set(group) & sources for group in capabilities.get("requires_source") or () if group)


def video_plan_for(db: Session | None, choice: ModelChoice, *, references: int | None = None) -> VideoPlan:
    """从模型能力目录挑一组肯定合法的默认值；未知模型只给生成契约的通用时长。

    `references`:参考那条路一次交几张图(缺省是整片一镜的 SHOT_REFERENCE_IMAGES),收不下的不走这条路。"""
    needed = SHOT_REFERENCE_IMAGES if references is None else references
    capabilities = model_capabilities(db, choice, "video")
    if capabilities is None:
        #: 认不出的模型只按最通用的那条走:首帧生视频。不猜它收参考素材。
        parameters: dict[str, Any] = {"duration_seconds": 5}
        if not choice.model:
            #: 还没挑模型(官网副本、这台机器上还没配视频模型):把画幅、分辨率接到开始参数上。挑模型时编辑器
            #: 留下新模型仍收的那几个绑定(见前端 carriedParameters)—— 此前这里只有时长,挑了模型之后改开始
            #: 节点的画幅不起作用,片子按模型的默认画幅出。
            parameters.update({"aspect_ratio": "{{input.aspect_ratio}}", "resolution": "{{input.resolution}}"})
        return VideoPlan(parameters=parameters)

    keys = set(capabilities.get("parameter_keys") or ())
    durations = [int(value) for value in capabilities.get("duration_seconds") or ()]
    if durations:
        #: 只给几档固定时长的,取**最接近默认**的那一档(平手取短的,便宜);此前默认那档不在里面就取第一档。
        preferred = int(capabilities.get("default_duration_seconds") or 5)
        clip_seconds = min(durations, key=lambda one: (abs(one - preferred), one))
    else:
        low = int(capabilities.get("min_duration_seconds") or 1)
        high = int(capabilities.get("max_duration_seconds") or max(5, low))
        clip_seconds = max(low, min(int(capabilities.get("default_duration_seconds") or 5), high))

    aspect_ratio = str(capabilities.get("default_aspect_ratio") or "16:9")
    resolution = str(capabilities.get("default_resolution") or "720p")
    parameters: dict[str, Any] = {}
    if "duration_seconds" in keys:
        parameters["duration_seconds"] = clip_seconds
    if "aspect_ratio" in keys:
        parameters["aspect_ratio"] = "{{input.aspect_ratio}}"
    if "resolution" in keys:
        parameters["resolution"] = "{{input.resolution}}"
    size_text = str(capabilities.get("default_size") or "").lower().replace("*", "x")
    try:
        size_width, size_height = (int(value) for value in size_text.split("x", 1))
    except (TypeError, ValueError):
        ratio_dimensions = {
            **FRAME_ASPECTS,
            "4:3": (1440, 1080),
            "3:4": (1080, 1440),
        }
        size_width, size_height = ratio_dimensions.get(aspect_ratio, (1920, 1080))
    sizes: dict[str, str] = {}
    if "size" in keys:
        #: 每种画幅挑和默认那一档清晰度最接近的(832*480 → 480*832 / 624*624),不顺手升到 1080p 多花钱。
        default_area = size_width * size_height
        for aspect in FRAME_ASPECTS:
            found = size_for_aspect(capabilities.get("sizes"), aspect, pick="near", near_area=default_area)
            if found:
                sizes[aspect] = found
        if sizes:
            parameters["size"] = "{{input.video_size}}"
        elif capabilities.get("default_size"):
            parameters["size"] = str(capabilities["default_size"])
    modes = set(capabilities.get("modes") or ())
    #: 声明了模式、却一种能拍一镜的都没有(说话照片、改口型、改视频……):哪条路都不走。没声明模式的(用户自建、
    #: 查不全的)只看参数键。
    shoots = not modes or bool(modes & _SHOT_MODES)
    reference_limit = int((capabilities.get("source_limits") or {}).get(REFERENCE_IMAGE) or 0)
    return VideoPlan(
        clip_seconds=clip_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        width=size_width,
        height=size_height,
        parameters=parameters,
        sizes=sizes or None,
        keyframes=shoots and FIRST_FRAME in keys and _route_allowed(capabilities, _KEYFRAME_SOURCES),
        last_frame=shoots and LAST_FRAME in keys,
        extends=FIRST_CLIP in keys,
        longest_clip=max(durations) if durations else int(capabilities.get("max_duration_seconds") or 0),
        shortest_clip=int(capabilities.get("min_duration_seconds") or 0),
        allowed_clips=tuple(durations),
        shortest_tail=float(((capabilities.get("source_duration_seconds") or {}).get(FIRST_CLIP) or (0,))[0]),
        #: 参考那条路一次交 `needed` 张:收不下的(整片一镜 8 张,可灵 kling-v3-omni 只收 4 张)不走这条路。
        #: 没写上限的按收得下算(和图像模型那边「认不出的算能」同一条)。
        references=shoots and REFERENCE_IMAGE in keys and _route_allowed(capabilities, _REFERENCE_SOURCES)
        and (reference_limit == 0 or reference_limit >= needed),
        reference_video=REFERENCE_VIDEO in keys,
    )
