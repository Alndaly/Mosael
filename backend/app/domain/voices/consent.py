"""克隆音色的授权声明(ADR 0028 §5)。

叶子模块:生成漏斗(generation.operations)、数字人节点(workflows.executors.talking)、配音库(voices.voices)
都要问「这把嗓子能不能用于数字人」;判据放在 voices.voices 里的话,漏斗要回头 import 配音那一整套,而配音又依赖生成
那一侧 —— 成了环。
"""

from __future__ import annotations

from typing import Any

#: 还没声明这把嗓子是谁的(升级前建的音色)。见 Voice.consent_kind。
UNDECLARED = "undeclared"


def usable_for_digital_human(voice: Any) -> bool:
    """这把嗓子能不能用于数字人:声明过是谁的就行(本人、已获同意、虚构都算)。"""
    return voice.consent_kind != UNDECLARED


__all__ = ["UNDECLARED", "usable_for_digital_human"]
