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
    #: 老 id 只作**读**的别名:迁移会把库里的值改掉,但在途任务的载荷可能还带着旧串。
    legacy_ids = ("openai-tts", "openai-compatible-tts")
    label = "OpenAI 语音合成(含兼容端点)"
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
    label = "Edge 免费语音(微软)"
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
    label = "火山方舟(豆包)"
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
REMOTE_ENGINES = {
    OpenAITTS.id: OpenAITTS,
    **{legacy: OpenAITTS for legacy in OpenAITTS.legacy_ids},
    VolcanoTTS.id: VolcanoTTS,
    EdgeTTS.id: EdgeTTS,
}


def describe_engines() -> list[dict[str, object]]:
    """What the UI needs to render an engine picker, without importing the classes."""
    return [
        {
            "id": "clone",
            "label": "本地音色克隆",
            "needs_key": False,
            "needs_voice_id": False,
            "voices": [],
            "note": "用音色库里的克隆音色;需要本地引擎(F5 / Fish Speech)。",
        },
        {
            "id": EdgeTTS.id,
            "label": EdgeTTS.label,
            "needs_key": False,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in EDGE_BUILTIN_VOICES],
            "note": "免费在线合成,无需任何配置;需联网,微软 Edge 同款音色。",
        },
        {
            "id": OpenAITTS.id,
            "label": OpenAITTS.label,
            "needs_key": True,
            "needs_voice_id": False,
            "voices": list(OpenAITTS.VOICES),
            "note": "预置音色,不需要参考音频。自建 /audio/speech 兼容端点填档案里的 Endpoint 即可,不必另建一项。",
        },
        {
            "id": "volcano-podcast",
            "label": "火山播客(双人对话)",
            "needs_key": True,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in PODCAST_SPEAKERS],
            "note": "两个发音人对谈;配置是 App ID + Access Token,不是方舟 API Key。",
        },
        {
            "id": VolcanoTTS.id,
            "label": VolcanoTTS.label,
            "needs_key": True,
            # The catalogue is account-dependent, so the real list comes from /api/tts/voices —
            # live when AK/SK are set, the built-in list otherwise. Either way it is a list, so
            # the panel offers a dropdown rather than asking the user to type an opaque id.
            "needs_voice_id": False,
            "voices": [voice for voice, _ in VOLCANO_BUILTIN_VOICES],
            "note": "中文音色最好。配置账号 AK/SK 后可拉取账号内全部音色。",
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
