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
import math
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.domain.plugins import media_bridge
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import text_of

logger = logging.getLogger(__name__)

#: `input_schema` 里标记"这个字段是一份素材"的 format 值。
ASSET_FORMAT = "asset"
#: `input_schema` 里标记"这个字段是另一个系统里的编号"(任务号、fs_id、对象路径)的 format 值。
#: 运行时不换任何东西,只是一句声明:节点上它的 data_type 是 external_id(见 workflows.EXTERNAL_ID)。
EXTERNAL_ID_FORMAT = "external_id"


def schema_type(spec: Any) -> str | None:
    """一格 JSON Schema 声明的类型。联合类型(`["array", "null"]` —— 可以不填的数组)取第一个不是 null 的分支:
    表单只能长一个样子,运行时也只能按一种转。没写类型回 None。

    表单(plugins.nodes)、运行时(coerce / asset_fields / materialize)、存量数据的迁移读的都是这一条。此前表单
    认联合类型、其余只认 `== "array"`:表单给了一行一项的编辑器,交给插件的却是没转过的原样;素材数组表单给了
    素材选择器,运行时却把素材 id 原样交出去。
    """
    if not isinstance(spec, dict):
        return None
    kind = spec.get("type")
    if isinstance(kind, list):
        kind = next((one for one in kind if one != "null"), None)
    return kind if isinstance(kind, str) else None


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
        if _is_asset(spec) or (schema_type(spec) == "array" and _is_asset(spec.get("items")))
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
        if schema_type(spec) == "array" and key in out:
            listed = _as_list(text_of(spec.get("title")) or key, value,
                              spec.get("items") if isinstance(spec.get("items"), dict) else {})
            if listed is None:
                out.pop(key)
            else:
                out[key] = listed
            continue
        if not isinstance(spec, dict) or not isinstance(value, str):
            continue
        kind = schema_type(spec)
        if kind not in ("integer", "number", "boolean"):
            continue
        if not value.strip():
            out.pop(key)
            continue
        out[key] = _scalar(value, kind)
    return out


_TRUE = frozenset({"true", "1", "yes"})
_FALSE = frozenset({"false", "0", "no"})


def _scalar(value: Any, kind: Any) -> Any:
    """一格文字按声明的类型转回来:`integer` / `number` 转成数,`boolean` 转成布尔。转不了的、不是文字的原样留着。

    整数先按整数读:`"7342567890123457123"` 绕一道 float 就成了 …024 —— 长 id 声明成 integer 时照样不丢位。
    """
    if not isinstance(value, str) or kind not in ("integer", "number", "boolean"):
        return value
    text = value.strip()
    if kind == "boolean":
        lowered = text.lower()
        return lowered in _TRUE if lowered in _TRUE | _FALSE else value
    if kind == "integer":
        try:
            return int(text)
        except ValueError:
            pass
    try:
        number = float(text)
    except ValueError:
        return value
    if not math.isfinite(number):
        # "nan" / "inf" / "1e999" float() 都认,可那不是谁填的数:原样留着,交给插件去说哪里不对
        return value
    return int(number) if kind == "integer" and number.is_integer() else number


def _item(value: Any, items: dict[str, Any]) -> Any:
    """数组里的一项按 `items` 归位。字符串项收到数 / 布尔(上游交来的、旧版表单存下的)写回文字:
    插件声明了要字符串,`"007"`、一串长 id 就得原样是字符串。每一项是一块结构的,按它的几格逐格归位。"""
    kind = schema_type(items)
    if kind == "object":
        return _structure(value, items)
    if kind == "string" and isinstance(value, (bool, int, float)):
        return json.dumps(value)
    return _scalar(value, kind)


def _structure(value: Any, schema: dict[str, Any]) -> Any:
    """一块结构(数组里的一项、项里的一个对象)按 `properties` 逐格归位 —— 和顶层的 coerce 同一个规矩。

    节点表单上一项一张卡(前端 ItemsField),每一格**只存文字**:数、布尔在这里按声明转回来,数 / 布尔格的空文字
    当没填(去掉这一格),一串值的格子走 _as_list(空的去掉),再往里一层的对象照样逐格归位。没声明的格子原样留着。
    """
    properties = schema.get("properties")
    if not isinstance(value, dict) or not isinstance(properties, dict):
        return value
    out: dict[str, Any] = {}
    for key, one in value.items():
        spec = properties.get(key)
        kind = schema_type(spec)
        if not isinstance(spec, dict) or kind is None:
            out[key] = one
        elif kind == "array":
            listed = _as_list(text_of(spec.get("title")) or key, one,
                              spec.get("items") if isinstance(spec.get("items"), dict) else {})
            if listed is not None:
                out[key] = listed
        elif kind == "object":
            out[key] = _structure(one, spec)
        elif kind in ("integer", "number", "boolean") and isinstance(one, str) and not one.strip():
            continue
        else:
            out[key] = _scalar(one, kind)
    return out


def _as_list(field: str, value: Any, items: dict[str, Any]) -> Any:
    """数组入参交给插件时**是数组**。空的(没填、空串、空列表)回 None = 去掉这一格。

    - 表单里一行一项(见前端 ListField):某一行是一整串引用,插值之后那一行就是一个列表 —— 拼进来(和
      「行列表」字段同一个规矩),而不是交出一个套着列表的列表;那一行拿到的是一段 JSON 数组文字(大模型交来的)
      也一样拼进来,和整格接上游同一个认法。每一项是结构(对象 / 数组)的除外:那一行是一段 JSON 对象(数组)
      文字时解开成那一项。
    - 一整格接的是上游:上游交来的已经是列表就照收;是一段 JSON 数组文字就解开(每一项是对象的,一段 JSON 对象
      文字就是那一项);是一个值就当只有这一项。**逗号分隔的文字不拆**:`"a, b"` 就是一项 —— 逗号可能本来就是
      值的一部分(一句话、一个地址),拆错了没人看得出;要几项就一行一项,或接一个数组。
    - 每一项按 `items.type` 归位(同 coerce 对单值的做法):数字 / 整数项的数字文字转成数,布尔项的 true / false
      转成布尔,字符串项收到的数 / 布尔写回文字。表单只存文字(见前端 ListField),类型只在这里按声明转一次 ——
      前端不看声明一律把「像数的」转成数,`"007"` 成了 7、一串长 id 丢了末几位。
    - 收到一个对象:每一项本来就是对象(`items.type: object`)的,它就是那一项;否则是「名字 → 值」的映射 ——
      旧版表单把数组当映射存下的写法(没被迁移到的),或上游交错了形状。报清楚,不再静默包成 `[{…}]` 交出去:
      插件收到一个装着映射的数组,只会在它自己那边莫名其妙地失败。
    转不了的原样留着,交给插件去说哪里不对。
    """
    if value is None or value == "" or value == []:
        return None
    kind = schema_type(items)
    if isinstance(value, str):
        if not value.strip():
            return None
        parsed = _json_text(value)
        value = parsed if isinstance(parsed, list) or (kind == "object" and isinstance(parsed, dict)) else [value]
    if isinstance(value, dict):
        if kind == "object":
            return [value]
        raise PluginDomainError("pluginErr_listGotMapping", field=field)
    if not isinstance(value, list):
        return [value]
    structured = kind in ("object", "array")
    flat: list[Any] = []
    for one in value:
        if isinstance(one, str):
            parsed = _json_text(one)
            if isinstance(parsed, list) or (kind == "object" and isinstance(parsed, dict)):
                one = parsed
        if isinstance(one, list) and not structured:
            flat.extend(one)
        elif one not in (None, ""):
            flat.append(one)
    return [_item(one, items) for one in flat]


def _json_text(text: str) -> Any:
    """一段 JSON 数组 / 对象文字解开;不是(或解不开)回 None。只认 `[` / `{` 开头的 —— `"123"`、`"true"` 是一项文字,
    不是 JSON。"""
    stripped = text.strip()
    if not stripped.startswith(("[", "{")):
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


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
    if schema_type(spec) == "array" and isinstance(spec.get("items"), dict):
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


__all__ = ["ASSET_FORMAT", "EXTERNAL_ID_FORMAT", "asset_fields", "coerce", "materialize", "schema_type"]
