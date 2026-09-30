"""官方模板的前置条件:一句给人看的话 + **能不能自动查**。

此前前置条件只是一串按语言分的句子。界面只能给每一句配同一个图标 —— 「AI 对话模型」
和「待整理的视频素材」长得一模一样,而用户真正想知道的是**这台机器上缺哪一样**。
句子读不出这个,所以每一条另带一个检查键:

- 检查键非空的,由 `templates.requirement_statuses` 按这个人、这个工作区查出「齐了 / 缺 /
  还没测出来」;
- 检查键为空的是**跑的时候才给**的东西(一条视频、一张商品图) —— 现在查不了,也不该查,
  界面说「运行时选择」,不假装它已经齐了。

句子的中英文仍然贴着彼此写(和插件清单、模板说明同一套),只是从「一种语言一串」换成了
「一条一个对象」:两种语言各写一串时,检查键没有地方挂,而且两串一长一短也不会有人发现。
"""

from __future__ import annotations

from typing import Any, Literal

#: 能自动查的几样东西。键是接口的一部分(界面按它挑图标和说法),加一个就要在
#: `templates.requirement_statuses` 里给出查法 —— 测试钉着两边对得上。
CHAT_MODEL = "chat_model"
#: 能带一张参考图出图的图像模型(商品图、面料图:每次只带那一张)。
REFERENCE_IMAGE_MODEL = "reference_image_model"
#: 能同时带一组参考图出图的图像模型(整片生成的关键帧:白模帧 + 三视图 + 设定图,见 templates_models)。
MULTI_REFERENCE_IMAGE_MODEL = "multi_reference_image_model"
REFERENCE_VIDEO_MODEL = "reference_video_model"
#: 一把克隆音色,而且本机克隆引擎跑得起来(模板里配音节点的引擎写的是 builtin:clone)。
CLONED_VOICE = "cloned_voice"
#: 同上,而且这把嗓子声明过是谁的(数字人用,ADR 0028 §5:未声明的克隆音色不能拿去让一张脸说话)。
DIGITAL_HUMAN_VOICE = "digital_human_voice"
TRANSCRIPTION_ENGINE = "transcription_engine"
SEPARATION_ENGINE = "separation_engine"
#: 会「说话照片」的视频模型(描述符的 modes 里有 speech-to-video,ADR 0028)。
SPEECH_VIDEO_MODEL = "speech_video_model"
#: 会「改口型」的视频模型(modes 里有 video-lipsync)。
LIPSYNC_VIDEO_MODEL = "lipsync_video_model"

CHECKS: tuple[str, ...] = (
    CHAT_MODEL,
    REFERENCE_IMAGE_MODEL,
    MULTI_REFERENCE_IMAGE_MODEL,
    REFERENCE_VIDEO_MODEL,
    CLONED_VOICE,
    DIGITAL_HUMAN_VOICE,
    TRANSCRIPTION_ENGINE,
    SEPARATION_ENGINE,
    SPEECH_VIDEO_MODEL,
    LIPSYNC_VIDEO_MODEL,
)

#: met = 齐了;missing = 没有;unknown = 还没测出来(引擎探测在后台跑,**不拿未知冒充结论**)。
CheckStatus = Literal["met", "missing", "unknown"]


def requirement(check: str | None, *, zh: str, en: str, optional: bool = False) -> dict[str, Any]:
    """一条前置条件。`check=None` 表示运行时由用户自己给(素材),查不了。

    `optional` 的那条缺了也能跑(比如旁白),界面据此把「缺」说成「可选」而不是报警。
    """
    if check is not None and check not in CHECKS:
        raise ValueError(f"unknown requirement check: {check!r}")
    return {"check": check or "", "optional": optional, "text": {"zh": zh, "en": en}}
