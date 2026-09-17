"""把一条混音拆成几条 stem 的能力契约(人声 / 背景音 / …)。

和 ``contracts/generation.py``、``contracts/speech.py`` 并列:契约只说**要什么、拿到什么**,
不说是哪个模型、跑在哪、要不要联网。具体实现在 ``adapters/``,装配在 ``registry.py`` ——
契约反向依赖任何一个具体 Adapter 都会让这一层白分(见 ADR-0010)。

**为什么这是一个能力,而不是配音流程里的一步**(ADR-0016):同一个操作还回答"做一份纯音乐"、
"只留人声好让转写干净"、"把这段的背景乐提出来"。埋进 dub 执行器就意味着每个入口各实现一遍,
而这个仓库为那种形状付过账 —— 手写的第二份工具清单漂移,静默让智能体少了十九个工具。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

#: 一次分离最长等多久。分离是按音频长度线性增长的重活(本地模型在 CPU 上尤其慢),
#: 而一段一小时的访谈是正常输入 —— 所以这个数比合成/识别那两条都大得多。
SEPARATION_TIMEOUT_SECONDS = 3600

#: 契约认得的 stem 名字。适配器各叫各的(demucs 叫 `no_vocals`、别家叫 `instrumental` / `accompaniment`),归一到这里,调用方才不必认识引擎 —— 而「调用方不认识引擎」这条由
#: tests/test_audio_separation.py::Test契约不认识任何一个引擎 守着。
VOCALS = "vocals"
BACKGROUND = "background"
STEMS = (VOCALS, BACKGROUND)


class SeparationError(RuntimeError):
    """分不出来。message 已经是可以直接给用户看的话。"""


@dataclass(frozen=True)
class SeparationRequest:
    """要分离的那段音频。

    `stems` 是**想要哪几条**,不是"引擎能给哪几条":四分离的引擎给得出鼓和贝斯,而这条产品线上
    真正用得到的是人声和背景音两条。要不到的名字由适配器报错,而不是悄悄少给一个文件 ——
    少给的那条会一路空到成片里。
    """

    audio_path: Path
    stems: tuple[str, ...] = STEMS


class SeparationAdapter(Protocol):
    engine_id: str
    label_key: str

    def runtime_ready(self) -> bool:
        """现在就能跑吗。

        **能力的可用性是问出来的,不是配置出来的**:本地引擎要装依赖和下模型,云引擎要有凭据。
        调用方据此决定"用它"还是"退回没有它的做法",而不是先调一次再看报错 —— 那一次调用
        可能已经花了钱或者等了十分钟。
        """
        ...

    def ensure_runtime(self) -> None:
        """把运行条件准备好(建 venv、装依赖、拉权重)。已经好了就什么都不做。"""
        ...

    def separate(self, request: SeparationRequest, out_dir: Path) -> dict[str, Path]:
        """分离,返回 {stem 名字: 文件}。文件写在 out_dir 下,调用方负责它的生命周期。"""
        ...
