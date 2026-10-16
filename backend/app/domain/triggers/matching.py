"""一条消息该不该叫起一条触发器、叫起来之后入参是什么 —— **纯函数,不认识数据库**(ADR 0065 §4)。

放在单独一个模块里是因为这三件事都值得被单独测:筛选(类型 / 关键词 / 发件人 / 群)、
入参映射里的占位符白名单、以及"同名直填"那条便利规则。它们不查库、不建任务、不碰飞书,
所以用例可以只喂数据、断言结论。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: 触发器能认的消息类型(界面上就这四档)。飞书的 `post`(富文本)归到 `text` —— 对用户来说
#: 它就是一段带格式的文字,和普通消息没有区别。
TRIGGER_MESSAGE_TYPES: tuple[str, ...] = ("text", "image", "file", "media")

#: 飞书送来的 `message_type` → 上面那一档。表里没有的(语音、表情、名片、文件夹……)触发器不认。
KIND_OF_MESSAGE_TYPE: dict[str, str] = {
    "text": "text",
    "post": "text",
    "image": "image",
    "file": "file",
    "media": "media",
}

#: 能写进入参映射的那几格。**白名单**:`{{trigger.x}}` 里的 x 只能是这些,保存时就校验。
TRIGGER_FIELDS: tuple[str, ...] = (
    "text",
    "message_id",
    "chat_id",
    "bot_id",
    "sender_open_id",
    "message_type",
    "file_name",
    "asset_id",
    "asset_ids",
)

#: 映射模板里的占位符。只认 `{{trigger.<字段>}}`,宽松地容忍空格。
PLACEHOLDER = re.compile(r"\{\{\s*trigger\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: 同名直填认这几样 —— 和 `TRIGGER_FIELDS` 同源。`asset_ids` 直填时交的是**列表**(工作流的
#: 素材多选字段收列表),其余是字符串;模板渲染时列表才连成逗号串(见 `render`)。
AUTO_FIELDS: tuple[str, ...] = TRIGGER_FIELDS

#: 列表值渲染成模板字符串时怎么连。
LIST_JOINER = ","


@dataclass(frozen=True)
class IncomingMessage:
    """一条**已经认得出来源**的消息 —— 触发器要看的全部事实。

    不叫 `FeishuMessage`:触发器这一层不认识飞书(见 ADR 0065 §6)。飞书那个适配器在
    `integrations/feishu/inbound.py`,它把事件削成这一个形状再交过来。
    """

    workspace_id: str
    bot_id: str
    chat_id: str
    message_id: str
    sender_open_id: str
    message_type: str
    text: str = ""
    file_name: str = ""
    #: 这一次入素材库的素材 id(图片 / 文件 / 视频),按消息里的顺序。
    asset_ids: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        """触发器认的那一档;认不出(语音、表情……)是空串。"""
        return KIND_OF_MESSAGE_TYPE.get(self.message_type, "")


def values_of(message: IncomingMessage) -> dict[str, Any]:
    """这条消息能填进模板的那几格。列表那两格:单数给第一份,复数给全部。"""
    return {
        "text": message.text,
        "message_id": message.message_id,
        "chat_id": message.chat_id,
        "bot_id": message.bot_id,
        "sender_open_id": message.sender_open_id,
        "message_type": message.message_type,
        "file_name": message.file_name,
        "asset_id": message.asset_ids[0] if message.asset_ids else "",
        "asset_ids": list(message.asset_ids),
    }


# ---------------- 筛选 ----------------


def _lowered(items: Any) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []
    return [str(one).strip().lower() for one in items if str(one).strip()]


def keyword_missing(keywords: Any, text: str) -> bool:
    """关键词非空、而消息文本里一个都没出现 → True。大小写不敏感。"""
    wanted = _lowered(keywords)
    if not wanted:
        return False
    haystack = (text or "").lower()
    return not any(word in haystack for word in wanted)


def decide(trigger: Any, message: IncomingMessage) -> str:
    """这条触发器认不认这条消息。认:空串;不认:一格短语(**给留痕用**,不是给人看的文案)。

    只判"消息本身对不对得上";开关(`enabled`)、去重、限流在调用方(见 `dispatch`)。
    机器人 / 群 / 发件人那三格**空着就是不限**。
    """
    kind = message.kind
    if not kind:
        return "message_type"
    accepted = [str(one) for one in (trigger.message_types or [])]
    if kind not in accepted:
        return "message_type"
    if trigger.bot_id and str(trigger.bot_id) != message.bot_id:
        return "bot"
    if trigger.chat_id and str(trigger.chat_id) != message.chat_id:
        return "chat"
    allowed = _lowered(trigger.only_from_open_ids)
    if allowed and (message.sender_open_id or "").lower() not in allowed:
        return "sender"
    if keyword_missing(trigger.keywords, message.text):
        return "keyword"
    return ""


# ---------------- 入参映射 ----------------


def unknown_placeholders(template: str) -> list[str]:
    """模板里认不出的 `{{trigger.x}}`(保存时就拦,不等群里真发了东西才暴露)。"""
    return sorted({name for name in PLACEHOLDER.findall(template or "") if name not in TRIGGER_FIELDS})


def bad_placeholders(params: Any) -> list[str]:
    """一整份映射里认不出的占位符,去重。"""
    found: set[str] = set()
    for template in (params or {}).values():
        found.update(unknown_placeholders(str(template)))
    return sorted(found)


def render(template: str, values: dict[str, Any]) -> str:
    """把模板里的 `{{trigger.x}}` 换成值。认不出的占位符**原样留着** —— 保存那一道已经拦过,
    走到这里说明是旧数据,留着比悄悄吃掉好(看得到它没被换)。"""

    def one(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        value = values[name]
        if isinstance(value, (list, tuple)):
            return LIST_JOINER.join(str(item) for item in value)
        return "" if value is None else str(value)

    return PLACEHOLDER.sub(one, template or "")


def render_params(mapping: Any, start_params: Any, values: dict[str, Any]) -> dict[str, Any]:
    """这一次运行的入参。

    1. **显式映射优先**:`{"prompt": "看这段:{{trigger.text}}"}` → `{"prompt": "看这段:…"}`;
    2. **同名直填**(ADR 0065 §2 那条便利):开始节点里有个参数叫 `text`、映射里没提它,就把
       `text` 的值填进去。`asset_ids` 直填时交的是**列表**(素材字段收列表),其余是字符串。
    """
    out: dict[str, Any] = {}
    for name, template in (mapping or {}).items():
        out[str(name)] = render(str(template), values)
    for name in start_params or ():
        name = str(name)
        if name in out or name not in AUTO_FIELDS:
            continue
        out[name] = values.get(name, "")
    return out


def start_param_names(graph: Any) -> list[str]:
    """这张图开始节点声明了哪些参数 —— 入参映射那张表按它列。没有开始节点就是空表。"""
    for node in (graph or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start":
            params = (node.get("config") or {}).get("params")
            if isinstance(params, dict):
                return [str(name) for name in params]
            return []
    return []


# ---------------- 留痕用的一小段文本 ----------------


def preview(text: str, limit: int = 200) -> str:
    """事件行里存的那一小段文本:够在面板上认出"是哪条消息",不存整段。"""
    flat = " ".join((text or "").split())
    return flat[:limit]
