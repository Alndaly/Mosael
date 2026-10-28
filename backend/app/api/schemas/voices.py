"""音色与朗读:音色库、合成、配音、播客,以及智能体用哪个音色。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from app.api.schemas.base import ApiModel
from app.domain.voices.subtitle_dub import DEFAULT_MATCH_DURATION
from app.domain.voices.voice_ref import VoiceRef


class VoiceRefBody(ApiModel):
    """「选了哪把嗓子」(ADR 0087):所有收音色、回音色的接口都是这一个形状,和库里存的 `VoiceRef` 一一对应。

    `voice`(引擎自己的音色 id)与 `cloned_voice`(这个工作区配音库里的克隆音色)**恰好一个**。`model`:选的那一项绑模型时
    一并写下(百炼按模型给音色;本机克隆写「引擎」或「引擎/权重」,如 `f5-tts/fr`);空 = 按引擎解析。`connection`:走哪条
    连接,空 = 这个人在该引擎上的那一条。`extra` 从音色目录那一项原样带回来,界面不读。形状不对直接 422。
    """

    engine: str = Field(min_length=1, max_length=100)
    voice: str = Field(default="", max_length=200)
    cloned_voice: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=120)
    connection: str = Field(default="", max_length=64)
    extra: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_voice(self) -> VoiceRefBody:
        VoiceRef.of(self.model_dump())
        return self

    def ref(self) -> VoiceRef:
        return VoiceRef.of(self.model_dump())

    @classmethod
    def of(cls, ref: VoiceRef | None) -> VoiceRefBody | None:
        return cls(**ref.to_json()) if ref is not None else None


class AgentVoiceOut(ApiModel):
    """语音对话的音色,以及说话输入(ASR)用哪一家。**和配音的 TTS 默认是两行配置** —— 见 db.models.AgentVoicePref。"""

    #: 念哪把嗓子;没选过是 null。
    voice: VoiceRefBody | None = None
    speed: float = 1.0
    #: 没设过时是 False,而且 voice 为空 —— 界面据此提示去选一个,而不是显示一个假的默认。
    enabled: bool = False
    #: 说话输入用哪一家(能力表的提供方 id)。空 = 跟随「转写」的默认。
    asr_engine: str = ""
    #: 念回复时先出声(默认);False = 等整段合成完再播。**只有对话类读它。**
    speak_early: bool = True


class AgentVoiceUpdate(ApiModel):
    #: 念哪把嗓子;null = 不选了。点配音库里的嗓子(`cloned_voice`,由能复刻的远端引擎念它的副本,ADR 0037)而这个账号
    #: 还没同意上传就回 409(`remote_voice_consent_required`)。
    voice: VoiceRefBody | None = None
    speed: float = 1.0
    enabled: bool = True
    #: 说话输入用哪一家;空 = 跟随「转写」的默认。**和 `engine`(TTS)分开**,换念字的声音不改听写用谁。
    asr_engine: str = Field(default="", max_length=100)
    #: 念回复时先出声(默认);False = 等整段合成完再播。
    speak_early: bool = True


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
    #: 用哪把嗓子念;null = 用默认那一把(见 domain/voices/defaults)。本机克隆明说权重写在 `model` 里(`f5-tts/fr`):
    #: 法语/德语/西语/意语/芬兰语都写拉丁字母,自动挑**永远挑不中**,只能由人来说。
    voice: VoiceRefBody | None = None
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class VoicePreviewRequest(ApiModel):
    """试听一把嗓子:念一小句,直接回音频(不建任务、不进素材库)。播客发音人也走这里(引擎是播客那一个)。"""

    workspace_id: str
    voice: VoiceRefBody
    text: str = Field(min_length=1, max_length=200)


class SynthesizeRequest(ApiModel):
    """用一把嗓子念一段,产出登记成素材(ADR 0087:一个接口,`voice` 说是哪把嗓子)。本机克隆念配音库里的嗓子
    (`cloned_voice`),远端引擎念它自己的音色(`voice`)—— 能复刻的引擎(CosyVoice)也念得了配音库里的嗓子(念它的远端副本,
    这个账号要先同意上传,不然 409 `remote_voice_consent_required`,ADR 0037)。"""

    workspace_id: str
    text: str = Field(min_length=1, max_length=2000)
    voice: VoiceRefBody
    #: 语速。**只有声明支持的引擎会用它**(见 TtsEngine.supports_speed):F5 的 infer 吃,
    #: fish 的请求结构里根本没有这一项。收下但不转发,好过让界面以为发了就生效。
    speed: float = Field(default=1.0, ge=0.25, le=3.0)
    project_id: str | None = None


class VoiceOptionOut(ApiModel):
    """音色目录里的一项(ADR 0087),所有挑音色的地方同一个形状。

    `source` 说它从哪来:builtin(引擎内置)/ account(按账号现拉)/ preset(本机引擎预置)/ cloned(这个工作区
    配音库里的克隆音色,由能复刻的引擎念它的远端副本,ADR 0037 —— 选它时音色选择写 `cloned_voice`)。
    语言 / 性别 / 风格**宁缺不猜**:空着的就是供应商没说。`extra` 只有那一家 Adapter 解释,界面原样放进音色选择带回去,不读。"""

    id: str
    label: str
    source: str
    languages: list[str] = []
    gender: str = ""
    styles: list[str] = []
    #: 只对这几个模型(或模型族前缀)有效;空 = 这个引擎的所有模型。
    models: list[str] = []
    preview_url: str = ""
    extra: dict[str, str] = {}
    #: 这是不是这台机器默认那一对里的音色(和引擎一起标:默认是一对)。见 domain/voices/defaults。
    is_default: bool = False


class VoiceDefaultUpdate(ApiModel):
    """这台机器默认那一把嗓子。null = 清掉(回到每个入口各自点名)。"""

    #: 内置引擎的一个引擎音色;不属于那个引擎、不适用写下的模型时 409。
    voice: VoiceRefBody | None = None


class VoiceDefaultOut(ApiModel):
    """改完之后的那一把。当前默认不另开 GET —— 它作为 `is_default` 标在 /tts/engines 和 /tts/voices 上。"""

    voice: VoiceRefBody | None = None


class VoiceFromSpeakerRequest(ApiModel):
    asset_id: str
    speaker: str | None = None
    name: str = ""
    #: 这把嗓子是谁的(必选,ADR 0028 §5)。
    consent_kind: str
