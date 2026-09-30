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

import json
import logging
import shutil
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
        if isinstance(spec, dict) and spec.get("type") == "array" and key in out:
            listed = _as_list(value, spec.get("items") if isinstance(spec.get("items"), dict) else {})
            if listed is None:
                out.pop(key)
            else:
                out[key] = listed
            continue
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


def _as_list(value: Any, items: dict[str, Any]) -> Any:
    """数组入参交给插件时**是数组**。空的(没填、空串、空列表)回 None = 去掉这一格。

    - 表单里一行一项(见前端 ListField):某一行是一整串引用,插值之后那一行就是一个列表 —— 拼进来(和
      「行列表」字段同一个规矩),而不是交出一个套着列表的列表;每一项是结构(对象 / 数组)的除外。
    - 一整格接的是上游:上游交来的已经是列表就照收;是一段 JSON 数组文字就解开;是一个值就当只有这一项。
    - 数字 / 整数项里的数字文字转成数(同 coerce 对单值的做法)。
    转不了的原样留着,交给插件去说哪里不对。
    """
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        value = parsed if isinstance(parsed, list) else [value]
    if not isinstance(value, list):
        return [value]
    structured = items.get("type") in ("object", "array")
    flat: list[Any] = []
    for one in value:
        if isinstance(one, list) and not structured:
            flat.extend(one)
        elif one not in (None, ""):
            flat.append(one)
    if items.get("type") in ("integer", "number"):
        flat = [_number(one, items["type"]) for one in flat]
    return flat


def _number(value: Any, kind: str) -> Any:
    if not isinstance(value, str):
        return value
    try:
        number = float(value.strip())
    except ValueError:
        return value
    return int(number) if kind == "integer" and number.is_integer() else number


def _media(spec: dict[str, Any]) -> tuple[str, ...]:
    """入参的 `x-media`:只收这几种素材。和节点上的素材选择器同一个读法(media_kinds.declared_media)。"""
    from app.domain.media_kinds import declared_media

    return declared_media(spec.get("x-media"))


def _prepared(spec: dict[str, Any], path: Path) -> Path:
    """`x-audio`:先把声音抽成 wav 再交(`original` 原采样率,`speech` 16k 单声道),插件不必自己带 ffmpeg。"""
    from app.media.audio_io import extract_audio, extract_speech

    prepare = spec.get("x-audio")
    if prepare not in ("original", "speech"):
        return path
    target = path.with_name(f"{path.stem}.audio.wav")
    return (extract_speech if prepare == "speech" else extract_audio)(path, target)


def _spec_of(tool: dict[str, Any], key: str) -> dict[str, Any]:
    schema = tool.get("input_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    spec = properties.get(key) if isinstance(properties, dict) else None
    if isinstance(spec, dict) and spec.get("type") == "array" and isinstance(spec.get("items"), dict):
        return spec["items"]
    return spec if isinstance(spec, dict) else {}


def materialize(
    db: Session,
    tool: dict[str, Any],
    payload: dict[str, Any],
    scratch: Path | None,
    *,
    workspace_id: str | None,
    files: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """把 payload 里声明为素材的字段换成插件看得见的**本地路径**(数组就是一串路径)。

    素材来自两处,落到暂存目录的是同一种副本:调用方传的素材 id(智能体、工作流、画板、插件页),和宿主自己的入口
    手上的文件(`files`:转写前抽好的音轨、解析任务里的原件 —— 它们不一定在素材库里)。前者按入参的 `x-media`
    核对类型、按 `x-audio` 先抽好声音;后者由宿主的入口自己备好,原样拷一份。

    没有这类字段就原样返回 —— 绝大多数工具走这条,不该为此付出任何代价。
    """
    given = {key: path for key, path in (files or {}).items() if key in asset_fields(tool)}
    fields = [key for key in asset_fields(tool) if payload.get(key) and key not in given]
    if not fields and not given:
        return payload
    if scratch is None:
        raise PluginDomainError("pluginErr_mcpNoAssetChannel")
    resolved = dict(payload)
    for key, path in given.items():
        into = scratch / "inputs" / f"{key}-1"
        into.mkdir(parents=True, exist_ok=True)
        copy = into / path.name
        shutil.copyfile(path, copy)
        resolved[key] = str(copy)
    if fields and workspace_id is None:
        raise PluginDomainError("pluginErr_assetNeedsWorkspace")
    for key in fields:
        value = payload[key]
        spec = _spec_of(tool, key)
        refs = [str(one) for one in value if one] if isinstance(value, list) else [str(value)]
        paths = []
        for ref in refs:
            # 每一份落进自己的子目录:两份素材同名(都叫 image.png)时不互相覆盖
            into = scratch / "inputs" / f"{key}-{len(paths) + 1}"
            into.mkdir(parents=True, exist_ok=True)
            path = media_bridge.source()(db, ref, into=into, workspace_id=workspace_id, media=_media(spec))
            path = _prepared(spec, path)
            logger.info("插件输入 %s: %s → %s", key, ref, path.name)
            # 给的是**绝对路径**:插件的 cwd 是它自己的目录,相对路径会指到别处去。
            paths.append(str(path))
        resolved[key] = paths if isinstance(value, list) else paths[0]
    return resolved


__all__ = ["ASSET_FORMAT", "EXTERNAL_ID_FORMAT", "asset_fields", "coerce", "materialize"]
