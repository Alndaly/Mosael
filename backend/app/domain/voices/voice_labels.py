"""内置音色的名字。素材名(voices)、音色下拉和智能体挑音色(engine_catalog)都从这里认,不各自拼一份 ——
只拼 Edge 那一份的话,播客发音人显示成 `zh_male_dayixiansheng_v2_saturn_bigtts`。

单独成一个模块,是因为两边都要它:合成(voices)要给产出起名,目录(engine_catalog)要给下拉写名字,而目录本身要读配音库。"""

from __future__ import annotations

from app.ai.providers import builtin_voice_labels
from app.ai.runtime import qwen_models

_BUILTIN_VOICE_LABELS: dict[str, str] = {
    #: 各家内置的念字音色与播客发音人,由 Registry 汇总(ADR 0086)。
    **builtin_voice_labels(),
    # 本机 Qwen3-TTS 的 9 个预置音色:id 是上游的小写名(vivian / uncle_fu …),下拉要给人看的名字。
    **qwen_models.voice_labels(),
}


def builtin_voice_label(voice: str) -> str:
    """内置音色的名字(「晓晓(女·温暖)」);不是内置的(火山按账号现拉的、插件的、百炼手填的)是空串。"""
    return _BUILTIN_VOICE_LABELS.get(voice, "")
