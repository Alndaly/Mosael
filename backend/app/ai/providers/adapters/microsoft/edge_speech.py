"""Edge 免费语音(微软)。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.ai.providers.contracts.speech import SpeechSynthesisRequest, SpeechSynthesisError
from app.core.http_retry import backoff_seconds, current_max_retries

logger = logging.getLogger(__name__)


def _transient(exc: BaseException) -> bool:
    """连不上 / 超时 / 连接中途断掉 —— 再连一次多半就好。服务回了「没有音频」(音色名不对之类)不算:重来也一样。"""
    import aiohttp
    from edge_tts.exceptions import WebSocketError

    return isinstance(exc, (aiohttp.ClientError, TimeoutError, WebSocketError))


class EdgeSpeechAdapter:
    """微软 Edge 的免费在线语音 — the same service the Edge browser's Read Aloud uses.

    The zero-config engine: no API key, no local model, no provider profile. That makes it the
    engine a fresh install can synthesise with before the user has configured anything, which is
    exactly the gap the other engines leave (clone wants gigabytes of weights, OpenAI/火山 want
    keys). The trade-offs are the service's: stock neural voices only, network required, and no
    contractual SLA — fine for drafts and口播, not something to build billing on.

    Speed maps to the service's ``rate`` parameter (a signed percentage, "+0%" is natural),
    keeping SpeechSynthesisRequest.speed meaning the same thing across engines — dubbing depends on it.
    """

    engine_id = "edge"
    label_key = "ttsProvider_edge"
    supports_parallel_synthesis = True
    free_of_charge = True

    def __init__(self, voice: str = "") -> None:
        self._default_voice = voice

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        try:
            import edge_tts
        except ModuleNotFoundError as exc:  # pragma: no cover — packaged installs ship it
            raise SpeechSynthesisError("providerErr_edgeTtsMissing") from exc

        voice = request.voice or self._default_voice or "zh-CN-XiaoxiaoNeural"
        speed = max(0.5, min(2.0, request.speed))
        rate = f"{round((speed - 1.0) * 100):+d}%"
        #: **连不上就再连。** 它是免费的,重连不多花一分钱;而它一失败,同一条流程里已经付了钱的东西跟着作废 —— 付费实测:
        #: 带货口播第 5 拍的配音连 speech.platform.bing.com 超时,整条循环失败,前面 4 拍 ¥8.47 的画面和视频没能导出。
        #: 次数和退避跟着「AI 出站调用」的重试设置走(core/http_retry),和别的出站调用一样。
        attempts = current_max_retries() + 1
        for attempt in range(attempts):
            communicate = edge_tts.Communicate(request.text, voice=voice, rate=rate)
            try:
                asyncio.run(communicate.save(str(out_path)))
                break
            except SpeechSynthesisError:
                raise
            except Exception as exc:  # noqa: BLE001 — edge_tts raises its own exception family
                if attempt < attempts - 1 and _transient(exc):
                    logger.info("Edge 语音合成第 %d 次没连上,重试:%s", attempt + 1, exc)
                    time.sleep(backoff_seconds(attempt))
                    continue
                raise SpeechSynthesisError("providerErr_ttsFailed", engine="Edge", detail=str(exc)) from exc
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise SpeechSynthesisError("providerErr_ttsEmptyAudio", engine="Edge")


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


