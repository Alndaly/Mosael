"""降噪的能力契约:一段有噪声的音频进来,一段干净些的出去。

和 ``contracts/separation.py`` 同一个形状(ADR-0017):契约只说**要什么、拿到什么**,不提任何
引擎;实现在 ``adapters/``,装配在 ``registry.py``。调用方(工作流节点、智能体工具、素材库、
剪辑台)只跟 ``domain/denoise.py`` 说话,不认识引擎 —— 加一个引擎不需要改任何入口。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

#: 一次降噪最长等多久。滤波器类引擎比实时快得多,模型类引擎在 CPU 上可能慢于实时;
#: 一小时的访谈是正常输入。
DENOISE_TIMEOUT_SECONDS = 3600

#: 契约认得的档位。**档位说的是"下手多重"**,各引擎自己决定怎么落到参数上 ——
#: 调用方不该知道某个滤镜的某个参数是多少分贝。
LIGHT = "light"
MEDIUM = "medium"
STRONG = "strong"
STRENGTHS = (LIGHT, MEDIUM, STRONG)
DEFAULT_STRENGTH = MEDIUM


class DenoiseError(RuntimeError):
    """降不了。message 已经是可以直接给用户看的话。"""


def checked_strength(value: str | None) -> str:
    """空 = 默认档;认不出的当场拒,而不是悄悄按默认跑 —— 否则"我选了强"和实际跑的"中"
    对不上,而用户只会觉得"强档也没什么用"。"""
    strength = value or DEFAULT_STRENGTH
    if strength not in STRENGTHS:
        raise DenoiseError(f"不认识的降噪档位:{strength}(可选:{'、'.join(STRENGTHS)})")
    return strength


@dataclass(frozen=True)
class DenoiseRequest:
    audio_path: Path
    strength: str = DEFAULT_STRENGTH

    def __post_init__(self) -> None:
        checked_strength(self.strength)


class DenoiseAdapter(Protocol):
    engine_id: str
    label_key: str
    #: 一句话说清它适合什么、代价是什么(i18n key)。界面照着显示 —— 前端不认识任何引擎,
    #: 所以"这个会去掉音乐""这个要先装"这类话必须由引擎自己说。
    description_key: str
    #: 这个引擎理解哪几档。空元组 = 它没有档位这回事(比如人声提取:要么是人声要么不是),
    #: 调用方据此不摆一个拨了没用的旋钮。
    strengths: tuple[str, ...]
    #: 会不会连音乐一起去掉。`auto` 只挑不会的那种 —— 用户说"降噪"时没有要求把配乐也拿掉。
    removes_music: bool
    #: 没准备好时告诉用户去哪儿准备(i18n key;永远就绪的引擎留空)。**准备这一步不替用户做**:
    #: 下载、安装是设置里显式的一步,不该藏在"点一下降噪"后面。
    setup_hint_key: str

    def runtime_ready(self) -> bool:
        """现在就能跑吗。**是问出来的,不是配置出来的**(同 SeparationAdapter)。"""
        ...

    def denoise(self, request: DenoiseRequest, out_path: Path) -> Path:
        """降噪,把结果写到 out_path(wav)并返回它。调用方负责它的生命周期。"""
        ...
