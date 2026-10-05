"""声音复刻 Adapter 的能力契约(ADR 0037):把一段参考音频在某家的账号里复刻成一个音色,之后像系统音色一样合成。

这一版只有百炼 CosyVoice 一家(`adapters/alibaba/dashscope/voice_enrollment.py`)。火山、qwen-tts、MiniMax 的复刻
以后接进来是多一个实现,不改这里。契约只管「怎么跟这家说」:建、查、列、删四个动作;副本挂在哪把嗓子下面、
在谁的账号里、什么时候重建,是领域层(`domain/voices/remote.py`)的事。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.i18n import LocalizedError

#: 远端音色的状态,归一成这三个词(各家原词另存在 `RemoteVoice.raw_status`)。
DEPLOYING = "deploying"
READY = "ok"
REJECTED = "failed"


class VoiceEnrollmentError(LocalizedError, RuntimeError):
    """复刻这一步做不成。带文案 key(`providerErr_*`);那家回的原话放进 `detail`,不翻、也不猜。"""


@dataclass(frozen=True)
class RemoteVoice:
    """远端的一个复刻音色。"""

    voice_id: str
    #: DEPLOYING / READY / REJECTED 之一。
    status: str
    raw_status: str = ""
    target_model: str = ""


class VoiceEnrollmentAdapter(Protocol):
    #: 复刻出来的音色由哪个语音引擎念(和 SpeechAdapter.engine_id 同一个名字空间)。
    engine_id: str

    def create(self, *, target_model: str, prefix: str, reference: Path) -> str:
        """交一段参考音频,建一个音色,交回那家给的音色 id。**不等它就绪** —— 就绪要另外查(`query`)。"""
        ...

    def query(self, voice_id: str) -> RemoteVoice: ...

    def list(self, *, prefix: str) -> list[RemoteVoice]:
        """这个账号里名字带这个前缀的复刻音色。"""
        ...

    def delete(self, voice_id: str) -> None: ...


__all__ = [
    "DEPLOYING",
    "READY",
    "REJECTED",
    "RemoteVoice",
    "VoiceEnrollmentAdapter",
    "VoiceEnrollmentError",
]
