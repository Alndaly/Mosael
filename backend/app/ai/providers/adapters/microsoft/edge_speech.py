"""Edge 免费语音(微软)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.ai.providers.contracts.speech import SpeechSynthesisRequest, SpeechSynthesisError


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

    def __init__(self, voice: str = "") -> None:
        self._default_voice = voice

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        try:
            import edge_tts
        except ModuleNotFoundError as exc:  # pragma: no cover — packaged installs ship it
            raise SpeechSynthesisError("edge-tts 依赖未安装,请更新后端环境") from exc

        voice = request.voice or self._default_voice or "zh-CN-XiaoxiaoNeural"
        speed = max(0.5, min(2.0, request.speed))
        rate = f"{round((speed - 1.0) * 100):+d}%"
        communicate = edge_tts.Communicate(request.text, voice=voice, rate=rate)
        try:
            asyncio.run(communicate.save(str(out_path)))
        except SpeechSynthesisError:
            raise
        except Exception as exc:  # noqa: BLE001 — edge_tts raises its own exception family
            raise SpeechSynthesisError(f"Edge 语音合成失败: {exc}") from exc
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise SpeechSynthesisError("Edge 语音合成返回空音频")


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


