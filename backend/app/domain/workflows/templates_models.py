"""内置模板**挑模型**的那几步:按用户的默认设置、按描述符能不能带参考图 / 首帧,选出每一步用哪个模型,
并把它的能力摊成出图 / 出片计划(ImagePlan / VideoPlan)。

模板入口(templates.py)和整片生成那张大图都要用,所以单独一份,放在两者下面。

由 templates.py 统一重新导出;调用方照旧从 templates 取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO
from app.db.models import ProviderModel
from app.domain.generation.catalog import known_capabilities_for
from app.domain.generation.resolution import resolve_row
from app.domain.providers.defaults import get_row
from app.domain.providers.models import effective_capabilities


@dataclass(frozen=True)
class ModelChoice:
    profile_id: str = ""
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class VideoPlan:
    clip_seconds: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    width: int = 1920
    height: int = 1080
    parameters: dict[str, Any] | None = None
    #: 这个视频模型收哪几种参考(见 _video_plan)。决定分镜里每一镜**能选**哪条路:
    #: 首帧(+尾帧)锁构图,或者参考图/参考视频锁人物与运镜。
    keyframes: bool = True
    last_frame: bool = False
    references: bool = False
    reference_video: bool = False

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


def _capabilities(db: Session | None, choice: ModelChoice, kind: str) -> dict[str, Any] | None:
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


#: 关键帧图要同时参考:白模帧 1 张 + 角色三视图最多 4 张 + 场景设定图最多 3 张 + (尾帧时)首帧 1 张。
REFERENCE_IMAGES_NEEDED = 9


def _can_take_references(db: Session | None, choice: ModelChoice) -> bool:
    """图像模型能不能带着一组参考图出图。认不出的算能(用户自建的、查不到能力表的)。"""
    capabilities = _capabilities(db, choice, "image")
    if capabilities is None:
        return bool(choice.model)
    limit = int((capabilities.get("source_limits") or {}).get(REFERENCE_IMAGE) or 0)
    return "image-to-image" in (capabilities.get("modes") or ()) and limit >= REFERENCE_IMAGES_NEEDED


def _can_shoot_from_references(db: Session | None, choice: ModelChoice) -> bool:
    """视频模型能不能从首帧或参考素材出片 —— 这条流程每一镜都给其中之一,从不只给一段文字。"""
    plan = _video_plan(db, choice)
    return bool(choice.model) and (plan.keyframes or plan.references)


def _pick(db: Session, user_id: str, kind: str, usable) -> ModelChoice:
    """默认模型合用就用它(用户自己的选择优先);不合用就在他**已经配好的**模型里挑一个合用的。
    一个都没有时留空 —— 节点上的模型格空着,界面会让他去选,那比塞一个必然失败的进去诚实。"""
    chosen = _default_model(db, kind, user_id)
    if usable(db, chosen):
        return chosen
    from app.domain.providers import models as provider_models

    for model in provider_models.models_for_capability(db, kind, user_id=user_id):
        if model.profile is None or not model.profile.enabled or kind not in effective_capabilities(model):
            continue
        candidate = ModelChoice(profile_id=model.provider_profile_id, provider=model.profile.vendor, model=model.model_id)
        if usable(db, candidate):
            return candidate
    return ModelChoice()


def _shot_video_model(db: Session, user_id: str) -> ModelChoice:
    return _pick(db, user_id, "video", _can_shoot_from_references)


def _reference_image_model(db: Session, user_id: str) -> ModelChoice:
    return _pick(db, user_id, "image", _can_take_references)


def _image_plan(db: Session | None, choice: ModelChoice) -> ImagePlan:
    """从图像模型的尺寸表里挑:关键帧和成片同画幅,三视图取最宽的横幅。认不出就不传尺寸。"""
    capabilities = _capabilities(db, choice, "image")
    sizes = [str(size).lower().replace("*", "x") for size in (capabilities or {}).get("sizes") or ()]
    minimum = int((capabilities or {}).get("min_size_pixels") or 0)

    def parsed(size: str) -> tuple[int, int]:
        width, height = (int(value) for value in size.split("x", 1))
        return width, height

    def best(ratio: float, *, largest: bool) -> str:
        fitting = [s for s in sizes if abs(parsed(s)[0] / parsed(s)[1] - ratio) < 0.02 and parsed(s)[0] * parsed(s)[1] >= minimum]
        if not fitting:
            return ""
        return sorted(fitting, key=lambda s: parsed(s)[0] * parsed(s)[1], reverse=largest)[0]

    frames = {aspect: best(ratio, largest=False) for aspect, ratio in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0))}
    return ImagePlan(frame_sizes={aspect: size for aspect, size in frames.items() if size}, sheet_size=best(16 / 9, largest=True))


def _video_plan(db: Session | None, choice: ModelChoice) -> VideoPlan:
    """从模型能力目录挑一组肯定合法的默认值；未知模型只给生成契约的通用时长。"""
    capabilities = _capabilities(db, choice, "video")
    if capabilities is None:
        #: 认不出的模型只按最通用的那条走:首帧生视频。不猜它收参考素材。
        return VideoPlan(parameters={"duration_seconds": 5})

    keys = set(capabilities.get("parameter_keys") or ())
    durations = [int(value) for value in capabilities.get("duration_seconds") or ()]
    if durations:
        preferred = int(capabilities.get("default_duration_seconds") or 5)
        clip_seconds = preferred if preferred in durations else durations[0]
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
    if "size" in keys:
        default_size = capabilities.get("default_size")
        if default_size:
            parameters["size"] = str(default_size)
    size_text = str(capabilities.get("default_size") or "").lower().replace("*", "x")
    try:
        size_width, size_height = (int(value) for value in size_text.split("x", 1))
    except (TypeError, ValueError):
        ratio_dimensions = {
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "1:1": (1080, 1080),
            "4:3": (1440, 1080),
            "3:4": (1080, 1440),
        }
        size_width, size_height = ratio_dimensions.get(aspect_ratio, (1920, 1080))
    return VideoPlan(
        clip_seconds=clip_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        width=size_width,
        height=size_height,
        parameters=parameters,
        keyframes=FIRST_FRAME in keys,
        last_frame=LAST_FRAME in keys,
        references=REFERENCE_IMAGE in keys,
        reference_video=REFERENCE_VIDEO in keys,
    )
