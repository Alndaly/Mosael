"""素材有哪几种,以及字段声明里「只收哪几种」的读法。

节点字段的 `media`(内置节点,见 workflows.config_media)和插件入参的 `x-media`(见 plugins.nodes)是
同一件事的两种写法:一种写字符串(`"video"`),几种写列表(`["audio", "video"]`)。住在这里而不是
workflows 里,是因为插件那一侧也要读它,而 workflows 本来就依赖插件 —— 反过来引就是一个环。
"""

from __future__ import annotations

from typing import Any

MEDIA_KINDS: tuple[str, ...] = ("image", "video", "audio")


def declared_media(value: Any) -> tuple[str, ...]:
    """声明里写的 → 收哪几种素材(按 MEDIA_KINDS 的顺序)。空 = 没限制;认不出的项丢掉。"""
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return tuple(kind for kind in MEDIA_KINDS if kind in values)


__all__ = ["MEDIA_KINDS", "declared_media"]
