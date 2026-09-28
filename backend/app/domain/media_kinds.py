"""素材有哪几种,以及字段声明里「只收哪几种」的读法。

节点字段的 `media`(内置节点,见 workflows.config_media)和插件入参的 `x-media`(见 plugins.nodes)是
同一件事的两种写法:一种写字符串(`"video"`),几种写列表(`["audio", "video"]`)。住在这里而不是
workflows 里,是因为插件那一侧也要读它,而 workflows 本来就依赖插件 —— 反过来引就是一个环。
"""

from __future__ import annotations

from typing import Any

MEDIA_KINDS: tuple[str, ...] = ("image", "video", "audio")
#: 素材库里的全部种类:媒体,加上文档(ADR 0031)。文档没有画面和声音,不进时间线、不当生成的参考。
ASSET_KINDS: tuple[str, ...] = (*MEDIA_KINDS, "document")


def declared_media(value: Any) -> tuple[str, ...]:
    """声明里写的 → 收哪几种素材(按 ASSET_KINDS 的顺序,文档也算:「文档转 Markdown」只收文档)。
    空 = 没限制;认不出的项丢掉。"""
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return tuple(kind for kind in ASSET_KINDS if kind in values)


__all__ = ["ASSET_KINDS", "MEDIA_KINDS", "declared_media"]
