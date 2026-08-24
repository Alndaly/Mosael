"""Speech synthesis behind one interface, so the caller does not care which engine ran.

Until now synthesis meant exactly one thing: a local zero-shot clone (F5 / Fish Speech) driven
by a reference clip. That is the right engine when you want *this person's* voice, and the wrong
one for everything else — it needs a reference recording, a multi-gigabyte model on disk, and a
GPU's patience. A remote engine needs none of that and speaks immediately in a stock voice.

The distinction that actually matters to callers is `parallel_safe`. A remote engine is an HTTP
request, so N cues can be in flight at once; a local engine holds one model in memory and
running two at once only makes both slower and risks exhausting VRAM. Dubbing a video means
synthesising every cue in a transcript, so getting this wrong is the difference between seconds
and many minutes — see synthesize_many, which is the only place callers should batch.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import base64
import json
import uuid

import httpx

logger = logging.getLogger(__name__)

REMOTE_TIMEOUT_SECONDS = 120
#: Concurrency for remote engines. Bounded: providers rate-limit, and a long transcript would
#: otherwise open a socket per cue.
REMOTE_PARALLEL = 6


class TTSError(RuntimeError):
    """Raised when synthesis cannot produce audio."""


@dataclass(frozen=True)
class SpeechRequest:
    """One utterance to synthesise.

    `speed` exists for dubbing: a translated line rarely fits the window its original occupied,
    and asking the engine to speak faster produces better prosody than stretching the waveform
    afterwards. 1.0 means the engine's natural pace.
    """

    text: str
    voice: str = ""  # engine-specific voice id; ignored by clone engines
    speed: float = 1.0


class TTSProvider(Protocol):
    id: str
    label: str
    #: May several synthesize() calls run at once? True for remote HTTP engines, false for a
    #: local model that holds one instance in memory.
    parallel_safe: bool

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None: ...


class OpenAITTS:
    """OpenAI's speech endpoint. Stock voices, no reference clip, no local model."""

    #: 引擎 id **就是 vendor id**(audio/voices.py 拿 engine 去 resolve_profile)。
    #: 合并成 "openai" 之前这里有三个:openai-tts 与 openai-compatible-tts —— 而后者存在的
    #: 理由只是"要填自定义 endpoint",可 openai 档案本来就有 base_url 字段。
    id = "openai"
    label = "ttsProvider_openai"
    parallel_safe = True
    VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", base_url: str = "") -> None:
        if not api_key:
            raise TTSError("OpenAI 语音合成需要 API Key,请在设置里配置")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://api.openai.com/v1").rstrip("/")

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
        payload = {
            "model": self._model,
            "input": request.text,
            "voice": request.voice or "alloy",
            "response_format": "wav",
        }
        # The API takes speed directly, which is what we want for dubbing — the model paces
        # itself rather than us squeezing the waveform afterwards.
        if abs(request.speed - 1.0) > 0.01:
            payload["speed"] = max(0.25, min(4.0, request.speed))
        try:
            response = httpx.post(
                f"{self._base}/audio/speech",
                headers={"Authorization": f"Bearer {self._key}"},
                json=payload,
                timeout=REMOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TTSError(f"OpenAI 语音合成失败: {exc}") from exc
        out_path.write_bytes(response.content)


class EdgeTTS:
    """微软 Edge 的免费在线语音 — the same service the Edge browser's Read Aloud uses.

    The zero-config engine: no API key, no local model, no provider profile. That makes it the
    engine a fresh install can synthesise with before the user has configured anything, which is
    exactly the gap the other engines leave (clone wants gigabytes of weights, OpenAI/火山 want
    keys). The trade-offs are the service's: stock neural voices only, network required, and no
    contractual SLA — fine for drafts and口播, not something to build billing on.

    Speed maps to the service's ``rate`` parameter (a signed percentage, "+0%" is natural),
    keeping SpeechRequest.speed meaning the same thing across engines — dubbing depends on it.
    """

    id = "edge"
    label = "ttsProvider_edge"
    parallel_safe = True

    def __init__(self, voice: str = "") -> None:
        self._default_voice = voice

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
        try:
            import edge_tts
        except ModuleNotFoundError as exc:  # pragma: no cover — packaged installs ship it
            raise TTSError("edge-tts 依赖未安装,请更新后端环境") from exc
        import asyncio

        voice = request.voice or self._default_voice or "zh-CN-XiaoxiaoNeural"
        speed = max(0.5, min(2.0, request.speed))
        rate = f"{round((speed - 1.0) * 100):+d}%"
        communicate = edge_tts.Communicate(request.text, voice=voice, rate=rate)
        try:
            asyncio.run(communicate.save(str(out_path)))
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001 — edge_tts raises its own exception family
            raise TTSError(f"Edge 语音合成失败: {exc}") from exc
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise TTSError("Edge 语音合成返回空音频")


#: Curated Edge voices. The service lists hundreds; offering them all makes the dropdown
#: useless. Chinese first (the primary audience), a couple of dialects, then English/Japanese.
EDGE_BUILTIN_VOICES: tuple[tuple[str, str], ...] = (
    ("zh-CN-XiaoxiaoNeural", "晓晓(女·温暖)"),
    ("zh-CN-XiaoyiNeural", "晓伊(女·活泼)"),
    ("zh-CN-YunxiNeural", "云希(男·阳光)"),
    ("zh-CN-YunjianNeural", "云健(男·解说)"),
    ("zh-CN-YunyangNeural", "云扬(男·新闻)"),
    ("zh-CN-YunxiaNeural", "云夏(男·少年)"),
    ("zh-CN-liaoning-XiaobeiNeural", "晓北(女·东北)"),
    ("zh-CN-shaanxi-XiaoniNeural", "晓妮(女·陕西)"),
    ("zh-TW-HsiaoChenNeural", "曉臻(台湾)"),
    ("zh-HK-HiuMaanNeural", "曉曼(粤语)"),
    ("en-US-AriaNeural", "Aria(英·女)"),
    ("en-US-GuyNeural", "Guy(英·男)"),
    ("ja-JP-NanamiNeural", "Nanami(日·女)"),
)


def synthesize_many(
    provider: TTSProvider,
    requests: list[SpeechRequest],
    out_paths: list[Path],
) -> list[Exception | None]:
    """Synthesise a batch, concurrently only where the engine allows it.

    Returns one entry per request — the exception if that one failed, None if it succeeded.
    Failures are per-cue on purpose: dubbing a hundred-line transcript should not be lost
    because line 57 tripped a rate limit, and the caller needs to know *which* lines to retry.
    """
    if len(requests) != len(out_paths):
        raise ValueError("requests and out_paths must be the same length")
    results: list[Exception | None] = [None] * len(requests)

    def one(index: int) -> None:
        try:
            provider.synthesize(requests[index], out_paths[index])
        except Exception as exc:  # noqa: BLE001 — recorded per cue, not raised
            logger.warning("tts cue %d failed: %s", index, exc)
            results[index] = exc

    if provider.parallel_safe and len(requests) > 1:
        workers = min(REMOTE_PARALLEL, len(requests))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, range(len(requests))))
    else:
        # A local model engine: one at a time, deliberately. Running two only makes both slower
        # and can exhaust VRAM.
        for index in range(len(requests)):
            one(index)
    return results


class VolcanoTTS:
    """火山引擎(豆包)大模型语音合成 — the v3 synchronous endpoint.

    Best Chinese voices of the engines here, at the cost of a fiddlier contract than OpenAI's:

    * X-Api-Resource-Id must match the voice's family or the call fails with code 55000000, and
      the family is only discoverable from the voice id itself — see _resource_id.
    * The response is a chunked stream of JSON lines, each carrying a base64 audio fragment;
      code 20000000 is the end-of-stream marker, not an error.
    * Speed is `speech_rate`, an int in [-50, 100] where 0 is natural — not a multiplier. The
      linear map below is what makes SpeechRequest.speed mean the same thing across engines,
      which is what dubbing depends on.
    """

    id = "volcano"
    label = "ttsProvider_volcano"
    parallel_safe = True

    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        if not api_key:
            raise TTSError("火山引擎语音合成需要新版控制台的 API Key")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://openspeech.bytedance.com").rstrip("/")
        self._default_voice = voice

    def _resource_id(self, voice: str) -> str:
        """The voice family, which the header must agree with. An explicit seed-* model wins."""
        if self._model.startswith("seed-"):
            return self._model
        if voice.startswith("S_"):
            return "seed-icl-2.0"  # 复刻音色
        if "_uranus_" in voice or voice.startswith("saturn_"):
            return "seed-tts-2.0"
        return "seed-tts-1.0"

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
        voice = request.voice or self._default_voice
        if not voice:
            raise TTSError("火山引擎语音合成需要音色 id(如 zh_male_..._bigtts)")
        speed = max(0.2, min(3.0, request.speed))
        payload = {
            "req_params": {
                "text": request.text,
                "speaker": voice,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                    "speech_rate": max(-50, min(100, round((speed - 1.0) * 100))),
                },
            }
        }
        headers = {
            "X-Api-Key": self._key,
            "X-Api-Resource-Id": self._resource_id(voice),
            "X-Api-Request-Id": uuid.uuid4().hex,
            "Content-Type": "application/json",
        }
        chunks: list[bytes] = []
        try:
            with httpx.Client(timeout=REMOTE_TIMEOUT_SECONDS) as client:
                with client.stream(
                    "POST", f"{self._base}/api/v3/tts/unidirectional", headers=headers, json=payload
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        line = (line or "").strip()
                        if not line:
                            continue
                        try:
                            frame = json.loads(line)
                        except ValueError:
                            continue  # heartbeat / separator, not a frame
                        code = int(frame.get("code", 0))
                        if code == 20000000:  # documented end-of-stream, not a failure
                            break
                        if code != 0:
                            raise TTSError(
                                f"火山 TTS 失败: code={code} {frame.get('message') or ''}".strip()
                            )
                        data = frame.get("data")
                        if data:
                            chunks.append(base64.b64decode(data))
        except httpx.HTTPError as exc:
            raise TTSError(f"火山 TTS 请求失败: {exc}") from exc
        if not chunks:
            raise TTSError("火山 TTS 返回空音频")
        out_path.write_bytes(b"".join(chunks))


#: The voices to offer when the account's AK/SK are not configured, so synthesis is usable
#: without them. Deliberately excludes the emo_v2 multi-emotion voices: their resource family
#: cannot be inferred from the id, and guessing produces an opaque 55000000 at synthesis time.
VOLCANO_BUILTIN_VOICES: tuple[tuple[str, str], ...] = (
    ("zh_female_cancan_mars_bigtts", "灿灿(女·活泼)"),
    ("zh_female_shuangkuaisisi_moon_bigtts", "爽快思思(女)"),
    ("zh_female_vv_uranus_bigtts", "Vivi 薇薇(女·2.0)"),
    ("zh_female_wanwanxiaohe_moon_bigtts", "湾湾小何(女·台腔)"),
    ("zh_female_xiaomei_mars_bigtts", "小美(女)"),
    ("zh_female_qingxinnvsheng_mars_bigtts", "清新女声(女)"),
    ("zh_female_zhixingnvsheng_mars_bigtts", "知性女声(女)"),
    ("zh_male_liufei_uranus_bigtts", "刘飞(男·2.0)"),
    ("zh_male_m191_uranus_bigtts", "云舟(男·2.0)"),
    ("zh_male_wennuanahu_moon_bigtts", "温暖阿虎(男)"),
    ("zh_male_shaonianzixin_moon_bigtts", "少年梓辛(男)"),
    ("zh_male_jingqiangkanye_moon_bigtts", "京腔侃爷(男·北京)"),
    ("zh_male_yangguangqingnian_moon_bigtts", "阳光青年(男)"),
    ("zh_male_sunwukong_mars_bigtts", "孙悟空(角色)"),
    ("en_female_anna_mars_bigtts", "Anna(英·女)"),
    ("en_male_adam_mars_bigtts", "Adam(英·男)"),
)

#: 播客 voices. These only work on the podcast WebSocket, not the v3 single-voice endpoint,
#: and read best paired within a series (大义+咪仔 / 刘飞+潇磊).
PODCAST_SPEAKERS: tuple[tuple[str, str], ...] = (
    ("zh_male_dayixiansheng_v2_saturn_bigtts", "大义(男)"),
    ("zh_female_mizaitongxue_v2_saturn_bigtts", "咪仔(女)"),
    ("zh_male_liufei_v2_saturn_bigtts", "刘飞(男)"),
    ("zh_male_xiaolei_v2_saturn_bigtts", "潇磊(男)"),
)


#: Engines a user can pick, in the order the UI offers them. "clone" is handled separately —
#: it is the local reference-driven path and needs a Voice row, not an engine voice id.
class BailianTTS:
    """阿里云百炼(DashScope)的 qwen-tts。

    走的是多模态生成端点,**同步返回一个音频地址**,再下载 —— 不是异步任务,所以这里没有轮询
    (同一家的视频生成才需要,见 ai/providers/wan_video)。

    **speed 这一档它不接**。百炼的 qwen-tts 没有语速参数,而配音要的正是"把一句话塞进原来那段
    时长里"。这不影响功能:时间线在渲染时用 atempo 变速兜底(见 README 里「缩放到段落长度」)。
    但引擎自己念得快慢更自然,所以需要精确控时的配音,选 openai / volcano / 本地克隆更合适 ——
    这句话写进 note 里给用户看,而不是让他试完才发现。

    音色是模型自带的固定几个(不像火山那样按账号变),所以直接列在这儿,不用另开一个拉取接口。

    真机验证(2026-08-24):四个音色各合成一句,均返回 24kHz 单声道 16bit PCM 的 WAV。
    """

    id = "alibaba"
    label = "ttsProvider_bailian"
    parallel_safe = True
    #: 这一支只认 qwen-tts 家族。CosyVoice 是同一把 Key 下的**另一套 API**,单独一个引擎
    #: (见 CosyVoiceTTS)—— 端点、请求体、音色、支不支持语速全都不一样,合成一条会让面板
    #: 上的音色和语速跟着"当前恰好配了哪个模型"无声地变。
    MODEL_PREFIXES = ("qwen-tts", "qwen3-tts")
    DEFAULT_MODEL = "qwen-tts"
    #: CosyVoice 走**另一个端点**,请求体也不同 —— 见 _request_for。
    COSYVOICE_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
    #: 音色**按模型族**给,不是全引擎一份 —— 真机验证过 qwen3-tts-flash 有 qwen-tts 没有的
    #: 音色(Ryan/Katerina/Elias)。键按前缀匹配:带日期的快照沿用同族音色
    #: (实测 qwen3-tts-flash-2025-11-27 + Ryan、qwen-tts-2025-05-22 + Chelsie 都通)。
    #:
    #: **这几张表是"已知可用",不是"全部"。** 百炼的 TTS 模型是开放集合(还有 instruct /
    #: vd / vc 变体和一串日期快照),而它没有列音色的接口 —— 穷举只会得到一张很快过期的表。
    #: 所以列不出来的模型退回让用户填音色 id(needs_voice_id),而不是给他一个空下拉。
    VOICES_BY_MODEL = {
        # 四个都真机验证过(2026-08-24,各合成一句均返回可播放 WAV)。
        "qwen-tts": ("Cherry", "Serena", "Ethan", "Chelsie"),
        "qwen3-tts-flash": ("Cherry", "Serena", "Ethan", "Chelsie", "Ryan", "Katerina", "Elias"),
        # CosyVoice v2 的音色 id 带 `_v2` 后缀,和 v1 不通用。真机验证过 longxiaochun_v2。
        "cosyvoice-v2": ("longxiaochun_v2", "longwan_v2", "longcheng_v2", "longhua_v2", "longshu_v2"),
    }

    #: 支持语速的模型族。CosyVoice 收 `rate`(实测真变速);qwen-tts 家族没有这个参数。
    SPEED_PREFIXES = ("cosyvoice",)

    @classmethod
    def supports_speed_for(cls, model: str) -> bool:
        return (model or "").strip().lower().startswith(cls.SPEED_PREFIXES)
    #: 取不到模型时的兜底:两族的交集,哪个模型都认。
    VOICES = ("Cherry", "Serena", "Ethan", "Chelsie")

    @classmethod
    def voices_for(cls, model: str) -> tuple[str, ...]:
        """这个模型能用哪些音色。认不出来就回空 —— 由调用方退回"自己填 id"。"""
        name = (model or "").strip()
        if not name:
            return cls.VOICES
        # 最长前缀优先:qwen3-tts-flash 要先于 qwen-tts 命中,否则带 3 的那族会落到旧表上。
        for prefix in sorted(cls.VOICES_BY_MODEL, key=len, reverse=True):
            if name.startswith(prefix):
                return cls.VOICES_BY_MODEL[prefix]
        return ()
    PATH = "/api/v1/services/aigc/multimodal-generation/generation"

    # 签名要收 `voice`:build_remote_provider 的兜底分支是
    # `cls(api_key=…, voice=…, model=…, base_url=…)`,少一个参数就是 TypeError。
    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        if not api_key:
            raise TTSError("百炼语音合成需要 DashScope API Key,请在设置里配置")
        self._key = api_key
        self._model = model or "qwen-tts"
        self._base = resolve_dashscope_native_base(base_url)
        self._default_voice = voice

    def _request_for(self, request: SpeechRequest) -> tuple[dict, str]:
        """百炼的语音有**两套 API**,按模型分派。

        · qwen-tts 家族 → 多模态生成端点,音色在 `input.voice`,**没有语速参数**;
        · CosyVoice   → `/api/v1/services/audio/tts/SpeechSynthesizer`,音色在
          `parameters.voice`,而且**支持语速**(实测 rate=1.5 把 2.25 秒的句子变成 1.50 秒,
          正好 1.5 倍 —— 是真变速,不是被忽略)。

        两套的回包形状一样(`output.audio.url`),所以只有请求这一半要分。
        """
        voice = request.voice or self._default_voice
        if is_cosyvoice(self._model):
            parameters: dict = {"voice": voice or "longxiaochun_v2", "format": "wav", "sample_rate": 22050}
            if abs(request.speed - 1.0) > 0.01:
                # 配音要的正是"塞进原时长" —— 引擎自己变速比事后拉伸波形自然。
                parameters["rate"] = max(0.5, min(2.0, request.speed))
            return {"model": self._model, "input": {"text": request.text}, "parameters": parameters}, self.COSYVOICE_PATH
        return (
            {"model": self._model, "input": {"text": request.text, "voice": voice or self.VOICES[0]}},
            self.PATH,
        )

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
        payload, path = self._request_for(request)
        try:
            response = httpx.post(
                f"{self._base}{path}",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=payload,
                timeout=REMOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            url = extract_bailian_audio_url(response.json())
            if not url:
                raise TTSError("百炼语音合成没有返回音频地址")
            # 结果是一个预签名 OSS 地址。**不要带上 Authorization** —— 多余的头会让 OSS 的
            # 签名校验走另一条分支(与 ai/providers/qwen_image 里那条注释同一个坑)。
            audio = httpx.get(url, timeout=REMOTE_TIMEOUT_SECONDS)
            audio.raise_for_status()
        except httpx.HTTPError as exc:
            raise TTSError(f"百炼语音合成失败: {exc}") from exc
        out_path.write_bytes(audio.content)


#: 百炼原生 API 的根。语音走的是它,不是对话那个 compatible-mode。
DASHSCOPE_NATIVE_BASE = "https://dashscope.aliyuncs.com"


def resolve_dashscope_native_base(base_url: str) -> str:
    """把档案里的 base_url 归一到**原生** API 根。

    同一个百炼档案的 base_url 往往填的是对话用的
    `https://dashscope.aliyuncs.com/compatible-mode/v1` —— 那是 OpenAI 兼容端点。语音走的是
    原生路径 `/api/v1/services/aigc/...`,直接往后拼会得到
    `…/compatible-mode/v1/api/v1/services/…`,一个必然 404 的地址。

    同一个坑图像那边已经踩过并解决(见 ai/providers/qwen_image.resolve_qwen_edit_base),
    这里用同一条判据:认得出 compatible-mode 就剥掉它,自定义代理原样放行。
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return DASHSCOPE_NATIVE_BASE
    if base.endswith("/compatible-mode/v1"):
        return base.removesuffix("/compatible-mode/v1")
    return base


def is_cosyvoice(model: str) -> bool:
    return (model or "").strip().lower().startswith("cosyvoice")


def extract_bailian_audio_url(payload: dict) -> str:
    """从 qwen-tts 的回包里取音频地址。

    单独成函数是为了能被纯 payload 测试盯住:这个适配器真正容易错的就是这一步(回包是
    `output.audio.url`,而同家的图像走的是 `output.results[].url`),而它在真跑一次之前
    看不出来。
    """
    output = payload.get("output") or {}
    audio = output.get("audio")
    if isinstance(audio, dict) and audio.get("url"):
        return str(audio["url"])
    # 少数模型把音频放进 choices 的 content 数组里,与 qwen-image 的编辑模式同形。
    for choice in output.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("audio"), dict) and item["audio"].get("url"):
                    return str(item["audio"]["url"])
    return ""


class CosyVoiceTTS(BailianTTS):
    """百炼的 CosyVoice。**和 qwen-tts 同一把 Key,但是另一套 API。**

    单独成一个引擎而不是塞进 BailianTTS 里选模型 —— 理由和火山把 TTS 与播客分开一样:
    面板上要显示的东西不同(CosyVoice 有语速、音色 id 完全不同),而"显示什么"不该取决于
    用户当前恰好在这条连接下配了哪个模型。

    与火山那两条的差别是**钥匙**:火山的 TTS 和播客来自两个控制台、发两把不同的 Key,所以
    它们是两个 vendor;百炼这两套共用一把 DashScope Key,拆 vendor 会让用户把同一把钥匙填
    两遍(bytedance 当年就是这么拆的,后来合了)。所以只拆**引擎**,凭据仍指向 alibaba ——
    见 vendor_for_engine。
    """

    id = "alibaba-cosyvoice"
    label = "ttsProvider_cosyvoice"
    MODEL_PREFIXES = ("cosyvoice",)
    DEFAULT_MODEL = "cosyvoice-v2"

    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        super().__init__(api_key=api_key, voice=voice, model=model or self.DEFAULT_MODEL, base_url=base_url)


#: 引擎 id → 取凭据时用的 vendor。**默认是它自己**(约定见 OpenAITTS.id 上面那段);
#: 只有百炼这一处例外:两个引擎共用一条连接、一把 Key。
_ENGINE_VENDOR = {CosyVoiceTTS.id: BailianTTS.id}


def vendor_for_engine(engine: str) -> str:
    """这个引擎的凭据挂在哪个 vendor 下。"""
    return _ENGINE_VENDOR.get(engine, engine)


REMOTE_ENGINES = {
    OpenAITTS.id: OpenAITTS,
    BailianTTS.id: BailianTTS,
    CosyVoiceTTS.id: CosyVoiceTTS,
    VolcanoTTS.id: VolcanoTTS,
    EdgeTTS.id: EdgeTTS,
}


def active_model_for(engine_cls: type) -> str:
    """这个部署给某个百炼引擎配的模型;取不到就回它的默认模型。

    引擎目录本来是"纯静态的一张表",这里破了一次例 —— 因为百炼的音色**随模型变**,
    而界面要在**挑引擎的那一刻**就把音色列对,不能等用户填完文本才发现选的音色不存在。
    """
    prefixes = getattr(engine_cls, "MODEL_PREFIXES", ())
    default = getattr(engine_cls, "DEFAULT_MODEL", "")
    try:
        from app.core.db import SessionLocal
        from app.domain import provider_models
        from app.domain.providers import resolve_profile

        with SessionLocal() as db:
            profile = resolve_profile(db, vendor_for_engine(getattr(engine_cls, "id", "")))
            found = provider_models.model_id_for_family(db, profile, "tts", prefixes) if profile else ""
            return found or default
    except Exception:  # noqa: BLE001 —— 引擎目录不该因为取不到模型就整个拉不出来
        return default


def describe_engines() -> list[dict[str, object]]:
    """What the UI needs to render an engine picker, without importing the classes.

    本地克隆这一条的 note 跟着**这台机器上装没装引擎**变:装了就说怎么用,没装就说去哪装。
    在这里说,是因为这是用户**挑引擎**的那一刻 —— 比让他填完文本、点了生成、再收到一句
    「还没有可用的引擎」要早得多。
    """
    from app.audio import tts_models
    from app.domain import tts_config

    # **不等探测**:这个接口只是"引擎选择器要什么",而探测要起子进程 import torch。
    # 没测过时按"还没就绪"渲染,后台探完下一次拉列表就对了(见 tts_models.runtime_status)。
    clone_ready, _checked = tts_models.runtime_status(tts_config.get().engine)
    return [
        {
            "id": "clone",
            "label": "ttsProvider_clone",
            "needs_key": False,
            # 本地克隆按**模型**定(F5 的 infer 吃 speed,fish 的请求里根本没这项),
            # 所以这里不表态,由 tts_models 那份 supports_speed 说了算。
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [],
            "ready": clone_ready,
            "note": "ttsProviderNote_cloneReady" if clone_ready else "ttsProviderNote_cloneMissing",
        },
        {
            "id": EdgeTTS.id,
            "label": EdgeTTS.label,
            "needs_key": False,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in EDGE_BUILTIN_VOICES],
            "note": "ttsProviderNote_edge",
        },
        {
            "id": OpenAITTS.id,
            "label": OpenAITTS.label,
            "needs_key": True,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": list(OpenAITTS.VOICES),
            "note": "ttsProviderNote_openai",
        },
        {
            "id": "volcano-podcast",
            "label": "ttsProvider_volcanoPodcast",
            "needs_key": True,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in PODCAST_SPEAKERS],
            "note": "ttsProviderNote_volcanoPodcast",
        },
        {
            "id": BailianTTS.id,
            "label": BailianTTS.label,
            "needs_key": True,
            # qwen-tts 家族没有语速参数。摆一个拨不动的旋钮比不摆更糟。
            "supports_speed": False,
            # 模型是开放集合(日期快照、instruct / vd / vc 变体),而百炼没有列音色的接口。
            # 认得出的模型走下拉(见 /api/tts/voices),认不出的退回填 id —— 而不是空下拉。
            "needs_voice_id": True,
            "voices": list(BailianTTS.voices_for(active_model_for(BailianTTS))),
            "note": "ttsProviderNote_bailian",
        },
        {
            # 同一把 DashScope Key 的第二套 API。分开列的理由见 CosyVoiceTTS 的说明。
            "id": CosyVoiceTTS.id,
            "label": CosyVoiceTTS.label,
            "needs_key": True,
            # 实测 rate=1.5 把 2.25 秒的句子变成 1.50 秒,是真变速。
            "supports_speed": True,
            "needs_voice_id": True,
            "voices": list(CosyVoiceTTS.voices_for(active_model_for(CosyVoiceTTS))),
            "note": "ttsProviderNote_cosyvoice",
        },
        {
            "id": VolcanoTTS.id,
            "label": VolcanoTTS.label,
            "needs_key": True,
            "supports_speed": True,
            # The catalogue is account-dependent, so the real list comes from /api/tts/voices —
            # live when AK/SK are set, the built-in list otherwise. Either way it is a list, so
            # the panel offers a dropdown rather than asking the user to type an opaque id.
            "needs_voice_id": False,
            "voices": [voice for voice, _ in VOLCANO_BUILTIN_VOICES],
            "note": "ttsProviderNote_volcano",
        },
    ]


def build_remote_provider(engine: str, api_key: str, voice: str = "", model: str = "", base_url: str = ""):
    """Construct a remote engine, or raise a message the user can act on."""
    cls = REMOTE_ENGINES.get(engine)
    if cls is None:
        raise TTSError(f"未知的语音引擎:{engine}")
    if cls is EdgeTTS:
        return cls(voice=voice)  # 免费服务,无密钥可传
    if cls is OpenAITTS:
        return cls(api_key=api_key, model=model or "gpt-4o-mini-tts", base_url=base_url)
    return cls(api_key=api_key, voice=voice, model=model, base_url=base_url)
