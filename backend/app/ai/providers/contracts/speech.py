"""语音合成 Adapter 的能力契约。

它和 ``contracts/generation.py`` 共同组成能力 Interface；供应商协议和引擎注册不属于
这个 Module，避免契约反向依赖任意一个具体 Adapter。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Protocol

from app.core.i18n import LocalizedError

logger = logging.getLogger(__name__)

SPEECH_REQUEST_TIMEOUT_SECONDS = 120
#: Concurrency for remote engines. Bounded: vendors rate-limit, and a long transcript would
#: otherwise open a socket per cue.
MAX_PARALLEL_SPEECH_REQUESTS = 6


class SpeechSynthesisError(LocalizedError, RuntimeError):
    """Raised when synthesis cannot produce audio.

    带文案 key(`providerErr_*`,见 core/i18n),`str(exc)` 按读的人的语言翻;引擎回的原话放进
    `detail`。传一句现成的话也行 —— 不在文案表里的就原样显示。"""


@dataclass(frozen=True)
class SpeechSynthesisRequest:
    """One utterance to synthesise.

    `speed` exists for dubbing: a translated line rarely fits the window its original occupied,
    and asking the engine to speak faster produces better prosody than stretching the waveform
    afterwards. 1.0 means the engine's natural pace.
    """

    text: str
    voice: str = ""  # engine-specific voice id; ignored by clone engines
    speed: float = 1.0


class SpeechAdapter(Protocol):
    engine_id: str
    label_key: str
    #: May several synthesize() calls run at once? True for remote HTTP engines, false for a
    #: local model that holds one instance in memory.
    supports_parallel_synthesis: bool
    #: 用它念不花钱(Edge 的免费在线语音)。记账据此记 0、可信度「免费」,而不是一条找不到价格规则的「未定价」。
    free_of_charge: bool
    #: 下面几项是**目录信息**:领域层照它列引擎、摆控件,不再逐家手写一段(ADR 0086)。
    #: 要不要一条带钥匙的连接(Edge 不要)。
    needs_key: bool
    #: 有没有语速可调。摆一个拨不动的旋钮比不摆更糟。
    supports_speed: bool
    #: 音色是开放集合、认不出的要手填 id(百炼),还是一定从下拉里选。
    needs_voice_id: bool
    #: 设置页上这一家底下那句说明的文案 key。
    note_key: str

    @classmethod
    def voices(cls, context: VoiceCatalogContext) -> list[VoiceOption]:
        """这个引擎此刻能念的音色(音色目录,ADR 0087)。

        内置的照表给;随模型变的(百炼)按 `context.model` 给,认不出的模型回空 —— 由界面退回手填 id;
        随账号变的(火山)按 `context.connection_extra` 现拉,拉失败抛 `SpeechCatalogError`。
        """
        ...

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None: ...


class SpeechCatalogError(LocalizedError, RuntimeError):
    """按账号现拉音色清单没拉成(带文案 key,供应商的原话放进 `detail`)。

    调用方用不带连接的 `VoiceCatalogContext` 再问一次,退回这家的内置清单 —— 下拉不该因此坏掉。"""


#: 音色从哪来。`cloned` 不由任何一家 Adapter 给:克隆音色是工作区的领域数据,由领域层并进同一份清单。
VOICE_SOURCES = ("builtin", "account", "preset", "cloned")


@dataclass(frozen=True)
class VoiceOption:
    """音色目录里的一项(ADR 0087)。

    **宁缺不猜**:供应商(或我们手里那张核过的表)没说语言 / 性别,就留空,不从名字里推断 ——
    界面对空着的那一格不画筛选,比画一个错的强。
    """

    #: 引擎自己的音色 id;克隆音色是 `voices.id`。
    id: str
    label: str
    source: str = "builtin"
    #: BCP 47 语言标签(`zh-CN`、`en`)。
    languages: tuple[str, ...] = ()
    #: female / male / neutral;不知道就空。
    gender: str = ""
    #: 供应商给的风格 / 情感标签,原样。
    styles: tuple[str, ...] = ()
    #: 只对这几个模型(或模型族前缀)有效;空 = 这个引擎的所有模型。
    models: tuple[str, ...] = ()
    #: 供应商给了试听才有 —— 不自己合成一段试听。
    preview_url: str = ""
    #: 只有这一家 Adapter 解释的附加信息(火山:音色所属的资源族 `resource_id`)。领域层原样带着,不读。
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceCatalogContext:
    """问音色目录时手上有什么。内置清单什么都不看;随模型 / 随账号变的那几家各取所需。"""

    #: 这次会用的模型(百炼按它给音色)。空 = 没有指定,给对所有模型都有效的那一组。
    model: str = ""
    #: 这条连接的附加字段,**含跟着钥匙走的密字段**(火山的 ak / sk,见 domain/providers/credentials)。
    #: 空 = 不按账号问,只给内置清单。
    connection_extra: Mapping[str, Any] = field(default_factory=dict)



def synthesize_many(
    adapter: SpeechAdapter,
    requests: list[SpeechSynthesisRequest],
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
            adapter.synthesize(requests[index], out_paths[index])
        except Exception as exc:  # noqa: BLE001 — recorded per cue, not raised
            logger.warning("tts cue %d failed: %s", index, exc)
            results[index] = exc

    if adapter.supports_parallel_synthesis and len(requests) > 1:
        workers = min(MAX_PARALLEL_SPEECH_REQUESTS, len(requests))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, range(len(requests))))
    else:
        # A local model engine: one at a time, deliberately. Running two only makes both slower
        # and can exhaust VRAM.
        for index in range(len(requests)):
            one(index)
    return results
