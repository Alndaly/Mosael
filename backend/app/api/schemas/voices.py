"""音色与朗读:音色库、合成、配音、播客,以及智能体用哪个音色。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import Field
from app.api.schemas.base import ApiModel
from app.domain.voices.subtitle_dub import DEFAULT_MATCH_DURATION

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
    #: 配音库里的一把嗓子,由能复刻的远端引擎(CosyVoice)念它的副本(ADR 0037);给了它 `engine_voice` 就留空。
    #: 这个账号还没同意上传就回 409(`remote_voice_consent_required`)。
    voice_id: str | None = None
    speed: float = 1.0
    enabled: bool = True


class AgentSpeechRequest(ApiModel):
    """念一句话。**不产出素材** —— 见 routes/agent.speak。"""

    text: str = Field(min_length=1, max_length=4000)
    #: **必填**。念一句要 ai 权限,而"没填就不检查"等于给了一条绕过去的路;
    #: 记账也要有归属(TTS 按字符计费)。
    workspace_id: str = Field(min_length=1)


class RemoteCopyOut(ApiModel):
    """一把嗓子复刻到远端引擎上的一份副本(ADR 0037)。只列**我自己**账号里的 —— 别人账号里那份我用不上。"""

    id: str
    #: 能力表里的引擎 id(`builtin:alibaba-cosyvoice`)。
    engine: str
    provider_profile_id: str
    #: 那条连接叫什么(连接删了就是空串)。
    connection: str = ""
    #: 建在哪个模型上(音色绑死在建它的模型上)。
    target_model: str
    #: deploying / ok / failed / missing。
    status: Literal["deploying", "ok", "failed", "missing"]
    #: 失败原因(远端的原话,或翻好的一句)。
    error: str = ""
    #: 最近一次合成用到它的时间 —— 一年没被合成用过,远端会把它删掉。
    last_used_at: datetime | None = None
    created_at: datetime


class VoiceOut(ApiModel):
    id: str
    name: str
    reference_text: str = ""
    source: str = "upload"
    source_speaker: str | None = None
    has_reference: bool = True
    #: 授权声明(self / authorized / fictional;升级前建的是 undeclared)与声明时间。
    consent_kind: str = "undeclared"
    consent_at: datetime | None = None
    created_at: datetime
    #: 它在哪儿还能念:我账号里的远端副本(本机那一种总在,参考音频就是它)。
    remote_copies: list[RemoteCopyOut] = Field(default_factory=list)


class RemoteCopyRequest(ApiModel):
    """把这把嗓子复刻到一个远端引擎上(配音库的「复刻到百炼」,或确认框里点了同意)。"""

    #: 能力表里的引擎 id;这一版只有 `builtin:alibaba-cosyvoice`。
    engine: str = Field(min_length=1, max_length=80)
    #: 哪条连接;不给就用这个人那家的第一条。
    provider_profile_id: str | None = None
    #: **同意把参考音频上传到这个账号**(确认框里点了同意才带)。这个账号没同意过、又没带它,回 409
    #: `remote_voice_consent_required`,带着确认框要说的那几样;同意过的不用再带。
    consent: bool = False


class RemoteCopyFailureOut(ApiModel):
    """删嗓子时没删掉的一份远端副本。本机那一行照删;这一份要去那家的控制台看。"""

    connection: str
    target_model: str
    remote_voice_id: str
    reason: str


class VoiceDeleteOut(ApiModel):
    #: 没删掉的远端副本(钥匙失效、网络)。空 = 远端也都删干净了。
    remote_failures: list[RemoteCopyFailureOut] = Field(default_factory=list)


class VoiceUpdate(ApiModel):
    """改音色。**只改说明性的字段** —— 参考音频不在其中:换了音频就是另一个音色了,
    而已经用它生成过的配音还在时间线上,让同一个 id 底下的声音悄悄换人比新建一条更糟。"""

    name: str | None = None
    reference_text: str | None = None
    #: 补声明 / 改声明这把嗓子是谁的。谁、何时由服务端记。
    consent_kind: str | None = None


class SynthesizeRequest(ApiModel):
    text: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    #: 这一次用哪个本地引擎(f5-tts / fish-speech)。空 = 用部署配置里那个默认(管理页「引擎 → 声音克隆」)——
    #: 那是默认,不是唯一。
    clone_model: str = Field(default="", max_length=40)
    clone_engine: str = Field(default="", max_length=40)
    #: 语速。**只有声明支持的引擎会用它**(见 TtsEngine.supports_speed):F5 的 infer 吃,
    #: fish 的请求结构里根本没有这一项。收下但不转发,好过让界面以为发了就生效。
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class SubtitleDubRequest(ApiModel):
    """给选中的字幕条配音。音色/引擎那一套与 /tts/synthesize 同构 —— 配音就是合成,只是文本
    来自字幕、产物直接落到时间线上。"""

    #: 点名要配的字幕条;留空 = 整条字幕轨(`track_id`,只有一条字幕轨时可省)。规则见 subtitle_dub.dub_targets。
    clip_ids: list[str] = Field(default_factory=list, max_length=500)
    #: 配哪条字幕轨。点名了条目时只取这条轨上的;条目跨两条字幕轨会被拒(一次只配一条轨)。
    track_id: str = Field(default="", max_length=64)
    #: 把配音拉伸/压缩到字幕段落的长度。默认值归领域层(subtitle_dub.DEFAULT_MATCH_DURATION),
    #: 剪辑台、智能体、工作流、MCP 是同一个。
    match_duration: bool = DEFAULT_MATCH_DURATION
    #: 双语字幕(「原文\n译文」)念哪一行。整段念的话是先念一遍原文再念一遍译文 ——
    #: 一条 3 秒的字幕能配出 12 秒的音。默认全念:单语字幕就该全念,那是绝大多数情况。
    line: str = Field(default="all", pattern="^(all|first|last)$")
    #: 配好之后原声怎么办(见 domain/voices/original_audio)。
    original_audio: Literal["duck", "mute", "keep", "separate"] = "duck"
    #: 配音引擎(能力表里的提供方 id:`builtin:clone`、`builtin:edge`、插件连接 id……)。
    engine: str = Field(default="builtin:clone", max_length=80)
    #: 克隆引擎要一个音色行;远端引擎不需要,它自带发音人 —— 能复刻的远端引擎(CosyVoice)点了配音库里的嗓子时
    #: 也是这一格(念它的远端副本,ADR 0037),`engine_voice` 留空。
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


class VoicePreviewRequest(ApiModel):
    """试听一个引擎里的一把嗓子:念一小句,直接回音频(不建任务、不进素材库)。"""

    workspace_id: str
    engine: str = Field(min_length=1, max_length=40)
    voice: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200)


class EngineSynthesizeRequest(ApiModel):
    """Synthesis through a remote engine — in one of its stock voices (`engine_voice`), or, for an engine that can
    clone (CosyVoice), in a cloned voice from the library (`voice_id`, spoken through its remote copy; ADR 0037)."""

    workspace_id: str
    text: str = Field(min_length=1, max_length=2000)
    engine: str = Field(min_length=1, max_length=40)
    provider_profile_id: str | None = None
    engine_model: str = Field(default="", max_length=120)
    engine_voice: str = Field(default="", max_length=120)
    #: 配音库里的一把嗓子(和本机克隆同一个字段)。给了它 `engine_voice` 就留空。
    voice_id: str | None = None
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
    #: 这一项是配音库里的一把克隆嗓子(`value` 是它的 id),由这个引擎念它的远端副本(ADR 0037)。
    #: 选它时请求带 `voice_id`、`engine_voice` 留空。只在能复刻的引擎(CosyVoice)、带了工作区时出现。
    cloned: bool = False


class VoiceFromSpeakerRequest(ApiModel):
    asset_id: str
    speaker: str | None = None
    name: str = ""
    #: 这把嗓子是谁的(必选,ADR 0028 §5)。
    consent_kind: str
