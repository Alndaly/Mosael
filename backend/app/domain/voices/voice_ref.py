"""「选了哪把嗓子」的唯一形状:`VoiceRef`(ADR 0087 §3)。

配音参数、智能体朗读偏好、这台机器的默认、人物资产的音色存的都是它 —— 以 JSON 一列落库,序列化和解析只在这里。
此前六处各存一种形状(`engine_voice` / `voice_id` / `engine_model` / `clone_engine` / `engine_voice_resource` …),
加一格就要改六处,而「音色依赖模型」这件事没有一处记得全。

**这个模块只管形状**(叶子,不 import 数据库与音色目录):
- 结构校验在 `VoiceRef.of`:引擎非空、引擎音色与克隆音色**恰好一个**、每一格都是有长度上限的字符串;
- 「属不属于这个引擎、适不适用这个模型、克隆音色在不在这个工作区」要问音色目录,在 `engine_catalog.check_voice`。

语速不在其中:它是念法,不是嗓子(同一把嗓子在对话里快一点、成片里慢一点是常见用法),各处单独存。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.i18n import LocalizedError

#: 每一格的长度上限:引擎 id(能力表提供方 id,插件连接 id 最长)、音色 id(火山账号音色、插件给的 id)、
#: 模型 id、连接 id、`extra` 里一项的键与值。超出就是调用方塞错了东西,不截断。
_LIMITS = {"engine": 100, "voice": 200, "cloned_voice": 64, "model": 120, "connection": 64}
_EXTRA_KEY_LIMIT, _EXTRA_VALUE_LIMIT, _EXTRA_ITEMS_LIMIT = 40, 200, 8


class VoiceRefInvalid(LocalizedError, ValueError):
    """存进来 / 传进来的音色选择形状不对。是输入的问题(422),不是服务端故障。"""


@dataclass(frozen=True)
class VoiceRef:
    """一把选定的嗓子。

    - `engine`:宿主能力 `speech` 的候选 id(`builtin:volcano`、`builtin:clone`、插件连接 id);
    - `voice` / `cloned_voice`:引擎自己的音色 id,**或**这个工作区配音库里的克隆音色(`voices.id`),恰好一个;
    - `model`:选择时这把嗓子对应的模型;空 = 不绑模型,按引擎解析。本机克隆引擎在这一格写
      「哪个本机引擎 / 哪一份权重」(见 `voices.clone_runtime_of`);
    - `connection`:走哪条连接;空 = 这个人在该引擎上的那一条;
    - `extra`:从 `VoiceOption.extra` 原样带过来,只有那一家 Adapter 读(火山的资源族)。
    """

    engine: str
    voice: str = ""
    cloned_voice: str = ""
    model: str = ""
    connection: str = ""
    extra: Mapping[str, str] = field(default_factory=dict)

    @property
    def spoken(self) -> str:
        """念的那一格:引擎音色 id 或克隆音色 id(给人看、给「这把嗓子叫什么」查名字用)。"""
        return self.voice or self.cloned_voice

    @classmethod
    def of(cls, raw: Any) -> VoiceRef:
        """一份 JSON(库里的一列、请求体里的一格)→ `VoiceRef`;形状不对抛 `VoiceRefInvalid`。

        **只认当前形状**:旧的那几种(`engine_voice`、`voice_id`、`clone_engine`…)由迁移改写,读取这一侧不认它们。
        """
        if not isinstance(raw, Mapping):
            raise VoiceRefInvalid("voiceErr_refNotObject")
        unknown = sorted(set(raw) - {*_LIMITS, "extra"})
        if unknown:
            raise VoiceRefInvalid("voiceErr_refUnknownField", fields=", ".join(unknown))
        values = {name: _text(raw.get(name), name, limit) for name, limit in _LIMITS.items()}
        if not values["engine"]:
            raise VoiceRefInvalid("voiceErr_refNoEngine")
        if bool(values["voice"]) == bool(values["cloned_voice"]):
            raise VoiceRefInvalid("voiceErr_refOneVoice")
        return cls(**values, extra=_extra(raw.get("extra")))

    @classmethod
    def stored(cls, raw: Any) -> VoiceRef | None:
        """库里的一列 → `VoiceRef`;空对象(`{}`,没选过)是 `None`。"""
        return None if not raw else cls.of(raw)

    def to_json(self) -> dict[str, Any]:
        """落库 / 回包的形状:只写有值的格 —— 读的一侧对缺的格取默认,两边是同一份。"""
        out: dict[str, Any] = {name: getattr(self, name) for name in _LIMITS if getattr(self, name)}
        if self.extra:
            out["extra"] = dict(self.extra)
        return out


def voice_identity(ref: VoiceRef, speed: float) -> str:
    """「是不是同一把嗓子、同样快慢念的」的规范化串(字幕配音认句子用,见 subtitle_dub.DUB_LINE_KEY)。

    连接和 `extra` 不算:换个人跑、用他自己的连接调同一个音色,念出来还是同一把嗓子;`extra` 是从音色目录带出来的
    附属信息,不是选择本身。
    """
    parts = {"engine": ref.engine, "voice": ref.voice, "cloned_voice": ref.cloned_voice, "model": ref.model,
             "speed": str(float(speed or 1.0))}
    return "|".join(f"{name}={value}" for name, value in parts.items() if value)


def _text(value: Any, name: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise VoiceRefInvalid("voiceErr_refFieldNotText", field=name)
    value = value.strip()
    if len(value) > limit:
        raise VoiceRefInvalid("voiceErr_refFieldTooLong", field=name, limit=limit)
    return value


def _extra(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > _EXTRA_ITEMS_LIMIT:
        raise VoiceRefInvalid("voiceErr_refBadExtra")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise VoiceRefInvalid("voiceErr_refBadExtra")
        if len(key) > _EXTRA_KEY_LIMIT or len(item) > _EXTRA_VALUE_LIMIT:
            raise VoiceRefInvalid("voiceErr_refBadExtra")
        if item:
            out[key] = item
    return out


__all__ = ["VoiceRef", "VoiceRefInvalid", "voice_identity"]
