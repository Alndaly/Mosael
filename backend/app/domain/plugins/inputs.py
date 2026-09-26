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
#: `input_schema` 里标记"这个字段是另一个系统里的编号"(任务号、fs_id、对象路径)的 format 值。
#: 运行时不换任何东西,只是一句声明:节点上它的 data_type 是 external_id(见 workflows.EXTERNAL_ID)。
EXTERNAL_ID_FORMAT = "external_id"


def _is_asset(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get("format") == ASSET_FORMAT


def asset_fields(tool: dict[str, Any]) -> list[str]:
    """这个工具的哪些输入要换成文件:`format: asset` 的字符串,以及 `items` 是它的数组(一次交几份)。"""
    schema = tool.get("input_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return []
    return [
        key
        for key, spec in properties.items()
        if _is_asset(spec) or (isinstance(spec, dict) and spec.get("type") == "array" and _is_asset(spec.get("items")))
    ]


def coerce(tool: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """表单里填的是文字(工作流节点的配置、插件页试跑的输入框都是字符串),按 `input_schema` 声明的类型转回来:
    `integer` / `number` / `boolean` 的一格是字符串时转成数 / 布尔,空字符串当没填(去掉这一格)。

    转不了的原样留着(一个 `{{上游.输出}}` 没接上时就是这样)—— 交给插件去说哪里不对,不在这里替它猜。
    """
    schema = tool.get("input_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return payload
    out = dict(payload)
    for key, spec in properties.items():
        value = out.get(key)
        if not isinstance(spec, dict) or not isinstance(value, str):
            continue
        kind = spec.get("type")
        if kind not in ("integer", "number", "boolean"):
            continue
        text = value.strip()
        if not text:
            out.pop(key)
            continue
        if kind == "boolean":
            if text.lower() in ("true", "false", "1", "0", "yes", "no"):
                out[key] = text.lower() in ("true", "1", "yes")
            continue
        try:
            number = float(text)
        except ValueError:
            continue
        out[key] = int(number) if kind == "integer" and number.is_integer() else number
    return out


def materialize(
    db: Session,
    tool: dict[str, Any],
    payload: dict[str, Any],
    scratch: Path | None,
    *,
    workspace_id: str | None,
) -> dict[str, Any]:
    """把 payload 里声明为素材的字段换成插件看得见的**本地路径**(数组就是一串路径)。

    没有这类字段就原样返回 —— 绝大多数工具走这条,不该为此付出任何代价。
    """
    fields = [key for key in asset_fields(tool) if payload.get(key)]
    if not fields:
        return payload
    if scratch is None:
        raise PluginDomainError("pluginErr_mcpNoAssetChannel")
    if workspace_id is None:
        raise PluginDomainError("pluginErr_assetNeedsWorkspace")

    resolved = dict(payload)
    for key in fields:
        value = payload[key]
        refs = [str(one) for one in value if one] if isinstance(value, list) else [str(value)]
        paths = []
        for ref in refs:
            # 每一份落进自己的子目录:两份素材同名(都叫 image.png)时不互相覆盖
            into = scratch / "inputs" / f"{key}-{len(paths) + 1}"
            into.mkdir(parents=True, exist_ok=True)
            path = media_bridge.source()(db, ref, into=into, workspace_id=workspace_id)
            logger.info("插件输入 %s: %s → %s", key, ref, path.name)
            # 给的是**绝对路径**:插件的 cwd 是它自己的目录,相对路径会指到别处去。
            paths.append(str(path))
        resolved[key] = paths if isinstance(value, list) else paths[0]
    return resolved


__all__ = ["ASSET_FORMAT", "EXTERNAL_ID_FORMAT", "asset_fields", "coerce", "materialize"]
