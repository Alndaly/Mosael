"""音色与朗读:音色库、合成、配音、播客,以及智能体用哪个音色。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import Field
from app.api.schemas.base import ApiModel

class AgentVoiceOut(ApiModel):
    """语音对话的音色。**和配音的 TTS 默认是两行配置** —— 见 db.models.AgentVoicePref。"""

    engine: str = ""
    engine_voice: str = ""
    engine_voice_resource: str = ""
    engine_model: str = ""
    provider_profile_id: str | None = None
    voice_id: str | None = None
    speed: float = 1.0
    #: 没设过时是 False,而且 engine 为空 —— 界面据此提示去选一个,而不是显示一个假的默认。
    enabled: bool = False


class AgentVoiceUpdate(ApiModel):
    engine: str = Field(default="", max_length=40)
    engine_voice: str = Field(default="", max_length=120)
    engine_voice_resource: str = Field(default="", max_length=200)
    engine_model: str = Field(default="", max_length=120)
    provider_profile_id: str | None = None
    voice_id: str | None = None
    speed: float = 1.0
    enabled: bool = True


class AgentSpeechRequest(ApiModel):
    """念一句话。**不产出素材** —— 见 routes/agent.speak。"""

    text: str = Field(min_length=1, max_length=4000)
    #: **必填**。念一句要 ai 权限,而"没填就不检查"等于给了一条绕过去的路;
    #: 记账也要有归属(TTS 按字符计费)。
    workspace_id: str = Field(min_length=1)


class VoiceOut(ApiModel):
    id: str
    name: str
    reference_text: str = ""
    source: str = "upload"
    source_speaker: str | None = None
    has_reference: bool = True
    created_at: datetime


class VoiceUpdate(ApiModel):
    """改音色。**只改说明性的字段** —— 参考音频不在其中:换了音频就是另一个音色了,
    而已经用它生成过的配音还在时间线上,让同一个 id 底下的声音悄悄换人比新建一条更糟。"""

    name: str | None = None
    reference_text: str | None = None


class SynthesizeRequest(ApiModel):
    text: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    #: 这一次用哪个本地引擎(f5-tts / fish-speech)。空 = 用设置页那个默认 ——
    #: 设置页是默认,不是唯一。
    clone_model: str = Field(default="", max_length=40)
    clone_engine: str = Field(default="", max_length=40)
    #: 语速。**只有声明支持的引擎会用它**(见 TtsEngine.supports_speed):F5 的 infer 吃,
    #: fish 的请求结构里根本没有这一项。收下但不转发,好过让界面以为发了就生效。
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class SubtitleDubRequest(ApiModel):
    """给选中的字幕条配音。音色/引擎那一套与 /tts/synthesize 同构 —— 配音就是合成,只是文本
    来自字幕、产物直接落到时间线上。"""

    clip_ids: list[str] = Field(min_length=1, max_length=500)
    #: 把配音拉伸/压缩到字幕段落的长度。**默认关** —— 变速会改变语速听感,超出 ±20% 就开始
    #: 明显不自然,值不值这个代价由用户按素材决定,而不是替他默认承受。
    match_duration: bool = False
    #: 双语字幕(「原文\n译文」)念哪一行。整段念的话是先念一遍原文再念一遍译文 ——
    #: 一条 3 秒的字幕能配出 12 秒的音。默认全念:单语字幕就该全念,那是绝大多数情况。
    line: str = Field(default="all", pattern="^(all|first|last)$")
    #: 配好之后原声怎么办(见 domain/voices/original_audio)。
    original_audio: Literal["duck", "mute", "keep", "separate"] = "duck"
    engine: str = Field(default="clone", max_length=40)
    #: 克隆引擎要一个音色行;远端引擎不需要,它自带发音人。
    voice_id: str | None = None
    clone_engine: str = Field(default="", max_length=40)
    #: 明说要用哪一份克隆权重(见 ai/runtime/f5_models)。空 = 按文字自动挑。
    #: 法语/德语/西语/意语/芬兰语都写拉丁字母,自动挑**永远挑不中**,只能由人来说。
    clone_model: str = Field(default="", max_length=40)
    provider_profile_id: str | None = None
    engine_model: str = Field(default="", max_length=120)
    engine_voice: str = Field(default="", max_length=120)
    engine_voice_resource: str = Field(default="", max_length=60)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class EngineSynthesizeRequest(ApiModel):
    """Synthesis through a remote engine, which speaks in a stock voice and so has no Voice row."""

    workspace_id: str
    text: str = Field(min_length=1, max_length=2000)
    engine: str = Field(min_length=1, max_length=40)
    provider_profile_id: str | None = None
    engine_model: str = Field(default="", max_length=120)
    engine_voice: str = Field(default="", max_length=120)
    #: 火山 only: the voice's resource family. Only the account's voice list knows it, and the
    #: synthesis header must agree with it or the call fails with an opaque 55000000. Blank
    #: falls back to inferring it from the voice id, which works for the built-in voices.
    engine_voice_resource: str = Field(default="", max_length=60)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)
    project_id: str | None = None


class PodcastRequest(ApiModel):
    """A 火山 podcast: two voices reading or discussing the given material."""

    workspace_id: str
    project_id: str | None = None
    provider_profile_id: str | None = None
    #: The material. summarize/read use this; research uses `topic` instead.
    text: str = Field(default="", max_length=20000)
    topic: str = Field(default="", max_length=2000)
    mode: str = Field(default="summarize", pattern="^(summarize|read|research)$")
    speakers: list[str] = Field(default_factory=list, max_length=2)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class TtsVoiceOut(ApiModel):
    """One selectable voice. `resource_id` is 火山-specific: the synthesis header must name the
    voice's family, and only the listing knows it — inferring it from the id is guesswork that
    fails with an opaque 55000000."""

    value: str
    label: str
    resource_id: str = ""


class VoiceFromSpeakerRequest(ApiModel):
    asset_id: str
    speaker: str | None = None
    name: str = ""
