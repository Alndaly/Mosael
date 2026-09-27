"""资产的词表:几种资产、参考图的几种角度 / 用途、授权声明的几种说法,以及每种资产的专有字段。

**词表在这里,名字在出口翻。** 角度的中英文名是文案 `entityRole_<角度>`(core/i18n),界面从
`GET /api/entities/catalog` 拿翻好的那一份,不另存一张表;生成时挑参考图的先后也写在这里,
界面上说「会先挂哪几张」读的是同一份顺序。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

#: 三种资产。「风格」那一种先不做(ADR 0027「以后再议」)。
KINDS: tuple[str, ...] = ("character", "location", "prop")

#: 参考图的角度 / 用途。顺序就是界面上下拉里的顺序。
ROLES: tuple[str, ...] = (
    "front",
    "side",
    "back",
    "turnaround",
    "closeup",
    "full_body",
    "expression",
    "concept",
    "detail",
)

#: 生成时从参考图里挑的先后(ADR 0027 §3):三视图 > 正面 > 全身 > 其余(其余按资产里排的顺序)。
ATTACH_PRIORITY: tuple[str, ...] = ("turnaround", "front", "full_body")

#: 新挂一张参考图、没说角度时按种类给的缺省:人物和道具先当正面,场景先当设定图。
DEFAULT_ROLE: dict[str, str] = {"character": "front", "location": "concept", "prop": "front"}

#: 音色库(本地克隆)这个引擎的名字 —— 和 voices.engine_catalog.CLONE_ENGINE 是同一个值;这里不 import 它,
#: 词表这一层不依赖配音引擎的装配。
VOICE_LIBRARY_ENGINE = "clone"

#: 真人 / 虚构的授权声明(数字人方案「合规」一节)。真人要 `self` 或 `authorized` 才能用于数字人功能。
CONSENT_KINDS: tuple[str, ...] = ("self", "authorized", "fictional")

#: 一个资产最多挂几张参考图。参考图墙是一面墙,不是一个素材库;再多就该拆成变体。
MAX_REFERENCES = 60
MAX_TAGS = 20
MAX_TAG_CHARS = 40
MAX_NAME_CHARS = 160
MAX_TEXT_CHARS = 8000
#: `lost_references` 只留最近这么多条 —— 它是一句提示,不是审计日志。
MAX_LOST = 20

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class AttributeProblem(ValueError):
    """专有字段写得不对。`key` 是文案 key,`params` 是参数(由 library 转成领域错误)。"""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def _text(value: Any, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AttributeProblem("entityErr_attributeNotText", field=field)
    text = value.strip()
    if len(text) > limit:
        raise AttributeProblem("entityErr_attributeTooLong", field=field, limit=limit)
    return text


def _consent(value: Any, stored: Any, actor_id: str | None) -> dict[str, str] | None:
    """授权声明。**谁声明的、什么时候声明的由服务端记**,客户端只说选了哪一种。

    选的和已存的一样就原样留着(不因为重存一次表单就把声明时间刷新);换了一种就重新记一笔。
    """
    if value is None:
        return None
    kind = value.get("kind") if isinstance(value, dict) else value
    if kind in (None, ""):
        return None
    if kind not in CONSENT_KINDS:
        raise AttributeProblem("entityErr_consentKind", kinds=" / ".join(CONSENT_KINDS))
    if isinstance(stored, dict) and stored.get("kind") == kind and stored.get("declared_at"):
        return {"kind": kind, "declared_by": str(stored.get("declared_by") or ""), "declared_at": str(stored["declared_at"])}
    return {
        "kind": str(kind),
        "declared_by": actor_id or "",
        "declared_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def normalize_attributes(
    kind: str, raw: Any, stored: dict[str, Any] | None = None, *, actor_id: str | None = None
) -> dict[str, Any]:
    """一个资产的专有字段 → 存得下的形状。**只收这种资产有的那几项**,写错的键当场拒(不静默丢)。

    引用的东西(音色、3D 场景、3D 模型)在不在这个工作区,由 library 在落库前查,这里只管形状。
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise AttributeProblem("entityErr_attributesNotObject")
    stored = stored or {}
    allowed = ATTRIBUTE_KEYS[kind]
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise AttributeProblem("entityErr_attributeUnknown", keys=", ".join(unknown), allowed=", ".join(allowed))
    out: dict[str, Any] = {}
    if kind == "character":
        # 音色是「引擎 + 那个引擎里的一把嗓子」,和配音、工作流的念稿同一种说法:本地克隆(音色库)只是其中一个引擎。
        # 没写引擎就是音色库里的 —— 那是「一把嗓子」最常见的来处。只写了引擎、没挑嗓子,等于没选。
        voice = _text(raw.get("voice_id"), "voice_id", 200)
        if voice:
            out["voice_engine"] = _text(raw.get("voice_engine"), "voice_engine", 64) or VOICE_LIBRARY_ENGINE
            out["voice_id"] = voice
        color = _text(raw.get("blockout_color"), "blockout_color", 7)
        if color:
            if not _COLOR.match(color):
                raise AttributeProblem("entityErr_colorFormat")
            out["blockout_color"] = color.lower()
        real = raw.get("real_person")
        if real is not None and not isinstance(real, bool):
            raise AttributeProblem("entityErr_attributeNotBool", field="real_person")
        out["real_person"] = bool(real)
        consent = _consent(raw.get("consent"), stored.get("consent"), actor_id)
        if consent is not None:
            # 虚构人物声明「虚构」;真人的声明只能是本人或已获授权 —— 真人配「虚构」是自相矛盾。
            if out["real_person"] and consent["kind"] == "fictional":
                raise AttributeProblem("entityErr_realPersonNotFictional")
            if not out["real_person"] and consent["kind"] != "fictional":
                raise AttributeProblem("entityErr_fictionalConsent")
            out["consent"] = consent
    elif kind == "location":
        scene = _text(raw.get("scene_id"), "scene_id", 64)
        if scene:
            out["scene_id"] = scene
        time_of_day = _text(raw.get("time_of_day"), "time_of_day", 200)
        if time_of_day:
            out["time_of_day"] = time_of_day
    elif kind == "prop":
        model = _text(raw.get("model_asset_id"), "model_asset_id", 64)
        if model:
            out["model_asset_id"] = model
    return out


#: 每种资产的专有字段(ADR 0027 §2)。
ATTRIBUTE_KEYS: dict[str, tuple[str, ...]] = {
    "character": ("voice_engine", "voice_id", "blockout_color", "real_person", "consent"),
    "location": ("scene_id", "time_of_day"),
    "prop": ("model_asset_id",),
}


def usable_for_digital_human(attributes: dict[str, Any]) -> bool:
    """这个人物能不能用于数字人功能(ADR 0027 §4、数字人方案「合规」):真人要有本人或已获授权的声明。

    阶段 5 才有用它的功能;判据先写在这里,和授权声明同一处。
    """
    consent = attributes.get("consent") if isinstance(attributes.get("consent"), dict) else None
    if not attributes.get("real_person"):
        return True
    return bool(consent) and consent.get("kind") in ("self", "authorized")


def attach_order(roles: list[tuple[str, str]]) -> list[str]:
    """`[(素材 id, 角度)]`(已按资产里的顺序排好)→ 生成时挑图的先后:三视图 > 正面 > 全身 > 其余。"""
    rank = {role: index for index, role in enumerate(ATTACH_PRIORITY)}
    ordered = sorted(enumerate(roles), key=lambda pair: (rank.get(pair[1][1], len(rank)), pair[0]))
    return [asset_id for _, (asset_id, _) in ordered]


def parse_entity_ids(value: Any) -> list[str]:
    """点名的资产:一串 id,或者逗号 / 换行分隔的一段字(工作流的模板字段插值之后就是这样)。去重保序。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts: list[Any] = value.replace("，", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple)):
        parts = []
        for one in value:
            parts.extend(one if isinstance(one, (list, tuple)) else [one])
    else:
        return []
    out: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in out:
            out.append(text)
    return out
