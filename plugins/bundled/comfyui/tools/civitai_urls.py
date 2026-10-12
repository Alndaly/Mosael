"""Civitai 的**地址形状**:一个版本号藏在哪种链接里、一个版本在网站上的那一页长什么样(纯解析与拼接,不连网)。

`civitai`(读那个版本的公开接口、把它收成模型库要的那几样)与 `provenance`(这个下载链接是哪个站上的哪一页)
都要这一样东西,所以它住在两者下面这个叶子里 —— 认链接这件事不必把那个会出网的模块拉进来。
"""

from __future__ import annotations

import re
from typing import Any
from urllib import parse


def page(model_id: Any, version_id: Any) -> str:
    """一个版本在 Civitai 网站上的那一页。"""
    return f"https://civitai.com/models/{int(model_id)}?modelVersionId={int(version_id)}"


def version_id_of(url: str) -> str:
    """Civitai 的下载链接、版本接口、带 modelVersionId 的模型页 → 版本号;认不出是空串。"""
    parts = parse.urlsplit(url)
    if found := re.match(r"^/api/download/models/(\d+)", parts.path):
        return found.group(1)
    if found := re.match(r"^/api/v1/model-versions/(\d+)", parts.path):
        return found.group(1)
    if re.match(r"^/models/\d+", parts.path):
        return (parse.parse_qs(parts.query).get("modelVersionId") or [""])[0]
    return ""
