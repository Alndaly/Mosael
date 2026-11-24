"""给一张图重新打光(ADR 0108)。

原图当参考图交给一个收参考图的图片模型(`reference_models`),灯位 —— 方向、高度、软硬、色温、亮度这几个数 ——
由 `relight_instruction` 翻成一段打光指令。**只有这一处翻**:界面、工作流、智能体给的都是数。要的画幅是原图自己的
宽 × 高(ADR 0094 的 `frame_aspect`),不然模型按自己的默认出一张 1:1,构图就变了。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale, t
from app.domain.jobs import current_actor
from app.domain.workflows.executors.inputs import _asset_in
from app.domain.workflows.executors.reference_models import reference_model
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.subjobs import generate_one

#: 每一格缺省是多少、能取到多少(和节点声明的 default 同一份数)。超出的按边界夹住 —— 方位按圈取余。
DEFAULTS = {"light_azimuth": 315.0, "light_elevation": 45.0, "light_temperature": 5500.0,
            "light_softness": 0.5, "light_intensity": 60.0}
_BOUNDS = {"light_elevation": (0.0, 90.0), "light_temperature": (1500.0, 12000.0),
           "light_softness": (0.0, 1.0), "light_intensity": (0.0, 100.0)}

#: 方位分八个方向,每 45° 一档,0 = 从镜头这边。
_DIRECTIONS = (0, 45, 90, 135, 180, 225, 270, 315)
#: (上限, 文案 key):第一个不小于这个值的那一档。
_HEIGHTS = ((15, "relight_height_low"), (40, "relight_height_mid"), (70, "relight_height_high"), (90, "relight_height_top"))
_SOFTNESS = ((0.33, "relight_soft_hard"), (0.67, "relight_soft_mid"), (1.0, "relight_soft_soft"))
_WARMTH = ((2600, "relight_warm_candle"), (4300, "relight_warm_tungsten"), (6200, "relight_warm_daylight"),
           (8000, "relight_warm_overcast"), (12000, "relight_warm_blue"))
_BRIGHTNESS = ((33, "relight_bright_low"), (67, "relight_bright_mid"), (100, "relight_bright_high"))


def light_values(config: dict[str, Any]) -> dict[str, float]:
    """节点上那几格 → 几个数:没写、写错的用缺省,超出范围的夹到边上,方位按圈取余。"""
    values: dict[str, float] = {}
    for key, fallback in DEFAULTS.items():
        try:
            number = float(config.get(key) if config.get(key) not in (None, "") else fallback)
        except (TypeError, ValueError):
            number = fallback
        if key == "light_azimuth":
            number %= 360
        else:
            low, high = _BOUNDS[key]
            number = min(max(number, low), high)
        values[key] = number
    return values


def _band(value: float, bands: tuple[tuple[float, str], ...]) -> str:
    return next(key for limit, key in bands if value <= limit)


def relight_instruction(config: dict[str, Any], locale: str) -> str:
    """几个数 → 交给模型的那段打光指令(按 `locale` 写),后面接上用户补的那句(`prompt`)。"""
    light = light_values(config)
    direction = min(_DIRECTIONS, key=lambda one: min(abs(light["light_azimuth"] - one), 360 - abs(light["light_azimuth"] - one)))
    text = t(
        "relight_instruction", locale,
        direction=t(f"relight_dir_{direction}", locale),
        elevation=t(_band(light["light_elevation"], _HEIGHTS), locale),
        softness=t(_band(light["light_softness"], _SOFTNESS), locale),
        kelvin=int(round(light["light_temperature"] / 100) * 100),
        warmth=t(_band(light["light_temperature"], _WARMTH), locale),
        brightness=t(_band(light["light_intensity"], _BRIGHTNESS), locale),
    )
    extra = str(config.get("prompt") or "").strip()
    return f"{text} {t('relight_extra', locale, text=extra)}" if extra else text


def _frame_of(asset: Any) -> str:
    """原图的宽 × 高(「1280x720」),读不出来是空串 —— 那就照模型的默认出。"""
    info = asset.media_info if isinstance(asset.media_info, dict) else {}
    width, height = info.get("width"), info.get("height")
    return f"{int(width)}x{int(height)}" if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width and height else ""


def _relight_order(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """这一单交什么:原图当参考图、打光指令当提示词、画幅是原图的宽 × 高,模型是挑好的那个收参考图的图片模型。"""
    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    model = reference_model(db, str(config.get("model") or "").strip(), current_actor(db))
    return {
        "provider": model["provider"],
        "provider_profile_id": model["provider_profile_id"],
        "model": model["model"],
        "kind": "image",
        "prompt": relight_instruction(config, get_current_locale()),
        "negative_prompt": "",
        "parameters": {},
        "source_assets": [{"asset_id": asset.id, "role": "reference_image"}],
        "frame_aspect": _frame_of(asset),
    }


@register("image_relight")
def image_relight(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """给一张图重新打光:一次生成,原图当参考图,交回打好光的那一张(下单、等结果见 subjobs.generate_one)。"""

    made = generate_one(db, scope, config, lambda: _relight_order(db, scope, config))
    return {"asset_id": made["asset_id"] or (made["asset_ids"][0] if made["asset_ids"] else ""), "asset_ids": made["asset_ids"]}
