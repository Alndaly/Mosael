"""授权声明(ADR 0028 §5、数字人方案「合规」一节):这个人物 / 这把嗓子是谁的。

**叶子模块,自成一个包。** 资产库(人物的声明)、配音库(克隆音色的声明)、生成漏斗(generation.operations)、
数字人节点(workflows.executors.talking)都要问同一件事;词表放在任何一个使用方里,别的使用方就得反过来
依赖它 —— 资产库和配音库此前正是为了这一张词表互相 import(见 tests/test_import_layering)。
"""

from __future__ import annotations

from typing import Any

#: 真人 / 虚构的授权声明。真人要 `self` 或 `authorized` 才能用于数字人功能;虚构的随便用。
CONSENT_KINDS: tuple[str, ...] = ("self", "authorized", "fictional")

#: 还没声明这把嗓子是谁的(升级前建的音色)。见 Voice.consent_kind。
UNDECLARED = "undeclared"


def voice_usable_for_digital_human(voice: Any) -> bool:
    """这把嗓子能不能用于数字人:声明过是谁的就行(本人、已获同意、虚构都算)。"""
    return voice.consent_kind != UNDECLARED


__all__ = ["CONSENT_KINDS", "UNDECLARED", "voice_usable_for_digital_human"]
