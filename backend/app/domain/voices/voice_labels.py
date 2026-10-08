"""内置音色的名字。素材名(voices)、音色下拉和智能体挑音色(engine_catalog)都从这里认,不各自拼一份 ——
只拼 Edge 那一份的话,播客发音人显示成 `zh_male_dayixiansheng_v2_saturn_bigtts`。

单独成一个模块,是因为两边都要它:合成(voices)要给产出起名,目录(engine_catalog)要给下拉写名字,而目录本身要读配音库。"""

from __future__ import annotations

from app.ai.providers import EDGE_BUILTIN_VOICES, PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES

_BUILTIN_VOICE_LABELS: dict[str, str] = {
    **dict(EDGE_BUILTIN_VOICES), **dict(PODCAST_SPEAKERS), **dict(VOLCANO_BUILTIN_VOICES),
}


def builtin_voice_label(voice: str) -> str:
    """内置音色的名字(「晓晓(女·温暖)」);不是内置的(火山按账号现拉的、插件的、百炼手填的)是空串。"""
    return _BUILTIN_VOICE_LABELS.get(voice, "")
