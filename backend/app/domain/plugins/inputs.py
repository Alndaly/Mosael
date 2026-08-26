"""宿主把一份**文件**交给插件。

artifact 那条(见 artifacts)是插件交给宿主;这条是反过来。有了它,插件才能做"上传"这类
事 —— 上传到网盘、发给外部服务转码、推进企业微盘。

## 插件怎么说"我要一个文件"

在工具的 `input_schema` 里给那个字段标上 `"format": "asset"`:

    {"name": "pan_upload",
     "input_schema": {"type": "object",
       "properties": {"asset_id": {"type": "string", "format": "asset"},
                      "path": {"type": "string"}},
       "required": ["asset_id", "path"]}}

调用方传 `asset_id`,插件收到的是**一个本地路径** —— 它不知道素材库存在,也不该知道。
用 JSON Schema 的 `format` 而不是自造一个键:那个关键字的用途正是"这个字符串在语义上
是什么",而且不认识它的工具会安静忽略,清单仍然是合法的 JSON Schema。

## 为什么在这里换,而不是让插件自己去取

插件的环境里没有数据库、没有 API 令牌、没有媒体目录 —— 这是隔离边界的一部分,不是疏漏。
让它自己取意味着要把这些交给它,那道边界就没了。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.domain.plugins import media_bridge
from app.domain.plugins.errors import PluginDomainError

logger = logging.getLogger(__name__)

#: `input_schema` 里标记"这个字段是一份素材"的 format 值。
ASSET_FORMAT = "asset"


def asset_fields(tool: dict[str, Any]) -> list[str]:
    """这个工具的哪些输入要换成文件。"""
    schema = tool.get("input_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return []
    return [
        key
        for key, spec in properties.items()
        if isinstance(spec, dict) and spec.get("format") == ASSET_FORMAT
    ]


def materialize(
    db: Session,
    tool: dict[str, Any],
    payload: dict[str, Any],
    scratch: Path | None,
    *,
    workspace_id: str | None,
) -> dict[str, Any]:
    """把 payload 里声明为素材的字段换成插件看得见的**本地路径**。

    没有这类字段就原样返回 —— 绝大多数工具走这条,不该为此付出任何代价。
    """
    fields = [key for key in asset_fields(tool) if payload.get(key)]
    if not fields:
        return payload
    if scratch is None:
        raise PluginDomainError("这个工具要收一份素材,但 MCP 形态没有交接文件的通道")
    if workspace_id is None:
        raise PluginDomainError("这个工具要收一份素材,但这次调用没有归属工作区")

    resolved = dict(payload)
    for key in fields:
        ref = str(payload[key])
        path = media_bridge.source()(db, ref, into=scratch, workspace_id=workspace_id)
        # 给的是**绝对路径**:插件的 cwd 是它自己的目录,相对路径会指到别处去。
        resolved[key] = str(path)
        logger.info("插件输入 %s: %s → %s", key, ref, path.name)
    return resolved


__all__ = ["ASSET_FORMAT", "asset_fields", "materialize"]
