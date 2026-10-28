"""播客合成的能力契约:两把嗓子读一段对话(或者先把一段材料改写成对话再读)。

和「念一句话」的语音合成是两件事:一次产出一整段多轮对话,计费按整段算,还要知道每一轮是谁在说。
今天只有火山一家实现(见 adapters/bytedance/volcano/podcast),但领域层只认这里的形状,由 Registry
交出实现(`registry.podcast_engine()`)—— 不在领域里写死是哪一家、凭据叫什么名字(ADR 0086)。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.core.i18n import LocalizedError


class PodcastSynthesisError(LocalizedError, RuntimeError):
    """播客合成不出来。带文案 key(`providerErr_podcast*`),供应商回的原话放进 `detail`。"""


class PodcastAction:
    """拿到的文本让服务端怎么用。"""

    #: 把材料改写成两人对话再读。要恰好两位发音人。
    SUMMARIZE = 0
    #: 逐轮照读(`turns`):谁读哪一轮跟着稿子走,不跟着发音人列表。
    READ = 3
    #: 先上网查这个话题,再两个人聊。要恰好两位发音人。
    RESEARCH = 4


@dataclass
class PodcastSynthesisResult:
    audio: bytes = b""
    #: 每一轮说了什么:{"speaker": …, "text": …}。这就是逐字稿;对 SUMMARIZE 来说,这是改写出的对话唯一存在的地方。
    texts: list[dict] = field(default_factory=list)


class PodcastConnection(Protocol):
    """合成要的那条连接:钥匙和附加字段。领域层的 ResolvedConnection 满足它;各家从里面取自己要的那几样。"""

    api_key: str | None
    extra: Mapping[str, Any]


class PodcastEngine(Protocol):
    """一家播客合成的实现。"""

    #: 能力表里的引擎 id(不带 `builtin:` 前缀),也是它记账、选连接用的 vendor id。
    engine_id: str
    label_key: str
    note_key: str
    #: 内置发音人:(id, 给人看的名字)。
    speakers: tuple[tuple[str, str], ...]
    #: 一次最多几轮、每轮最多几个字 —— 按轮计费,这是预算,不是对「合理请求」的限制。
    max_rounds: int
    max_round_chars: int

    def synthesize(
        self,
        connection: PodcastConnection | None,
        *,
        action: int,
        input_text: str = "",
        prompt_text: str = "",
        turns: list[dict] | None = None,
        speakers: list[str] | None = None,
        speed: float = 1.0,
        out_path: Path | None = None,
    ) -> PodcastSynthesisResult: ...


def split_to_rounds(text: str, *, dual: bool, max_rounds: int, max_round_chars: int) -> list[str]:
    """把一段散文切成逐轮照读的稿子(手上只有文字、没有剧本的调用方用,例如智能体读一段话)。

    两个人读时一轮就是一句,嗓音才真的交替;把几句塞进一轮,就成了一个人念一段、另一个人答一句。
    一个人读时没有交替可言,按 `max_round_chars` 塞满一轮,压低轮数(和账单)。
    """
    sentences = [part.strip() for part in re.split(r"(?<=[。!?!?\n])", text) if part.strip()]
    if not sentences:
        return []
    if dual:
        return sentences[:max_rounds]
    rounds: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_round_chars:
            rounds.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        rounds.append(current)
    return rounds[:max_rounds]


__all__ = [
    "PodcastAction",
    "PodcastConnection",
    "PodcastEngine",
    "PodcastSynthesisError",
    "PodcastSynthesisResult",
    "split_to_rounds",
]
