"""飞书能力节点:发消息 / 取回附件 / 回表情 / 列群。

四个执行器都很短 —— 它们不碰飞书的地址、分页和卡片 JSON:那些在集成层
(`app/integrations/feishu`,经 `domain/feishu/gateway` 那道缝进来)。这里只做三件事:
读出节点上那几格、把它翻成**一次调用**、把交回来的东西摆成声明的输出。

## 「发到哪」和「等人确认」是同一份解析

`domain/feishu/routing.resolve` 一处说了算:两族节点各写一套的话,同一个写法迟早给出发给谁的两个
答案(而"发给谁"错一次就是一句说给错的人听的话)。收件 id、挑机器人、`raw` 那两格全在那儿解。

## 没绑机器人:失败,不是降级

「等人确认」遇到"发不出去"**降级**成站内 —— 那是对的:那个门的用处是拦住"没人看着就往下走",
而不是拦住自己。这里反过来:「发飞书消息」整个存在的意义就是把一句话送出去,送不出去却"成功"
等于让整条自动化假装做完了,而发现它没做是在很久以后。所以它当场失败,失败原因说清是缺机器人、
缺收件人,还是这个人没绑过账号。

(`feishu_take_resource` / `feishu_reaction` / `feishu_chats` 同理:它们都要一个能用的机器人。)
"""

from __future__ import annotations

import functools
from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import FeishuBot, Job
from app.domain.feishu import gateway as feishu_gateway, routing
from app.domain.jobs import current_parent_job_id
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.graph_rules import as_text
from app.domain.workflows.executors.registry import (
    PreflightNode,
    RunScope,
    register,
    register_preflight,
)
from app.domain.assets import importer
from app.domain.workflows.executors.numbers import at_least, whole_number

#: 解不出目标时,`reason` → 说给用户听的那一句。**每一种都说得出是哪件事** ——
#: 一句"发不出去"会让人挨个字段试,而这几种的修法完全不同(接机器人 / 选收件人 / 换通知方式)。
_UNRESOLVED = {
    "no-bot": "wfErr_feishuNoBot",
    "no-target": "wfErr_feishuNoTarget",
    "no-origin": "wfErr_feishuNoOrigin",
    "not-bound": "wfErr_feishuNotBound",
    "none": "wfErr_feishuStationOnly",
}

#: 「发飞书消息」的形态。文字与卡片各读各的字段(见 NODE_TYPES 的 active_when)。
TEXT_FORM = "text"
CARD_FORM = "card"
FORMS = (TEXT_FORM, CARD_FORM)


def _form_of(config: dict[str, Any]) -> str:
    value = str(config.get("format") or "").strip()
    return value if value in FORMS else TEXT_FORM


def _job(db: Session) -> Job | None:
    """这次运行那条任务(载荷里的回执是 `origin` 那一档的唯一出处)。"""
    job_id = current_parent_job_id()
    return db.get(Job, job_id) if job_id else None


class _Translated:
    """把集成层的报错转述成工作流错误,一处做。

    飞书那一侧抛的是 `LocalizedError`(`feishuErr_*`),而执行器这一层出口必须是工作流错误 ——
    否则失败原因落进任务时丢了 key,读的人拿到的只有写下它那一刻的语言(见
    WorkflowDomainError.from_error)。四个执行器各自 try/except 一遍的话,漏掉哪一条哪一条就退化成
    一句字面量,所以在这里一次包住:凡是经这道门出去的调用,报错都跟着 key 走。
    """

    def __init__(self, inner: feishu_gateway.Transport) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        call = getattr(self._inner, name)

        @functools.wraps(call)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return call(*args, **kwargs)
            except LocalizedError as exc:
                raise WorkflowDomainError.from_error(exc) from exc

        return wrapped


def _transport() -> feishu_gateway.Transport:
    try:
        return _Translated(feishu_gateway.transport())
    except feishu_gateway.FeishuUnavailable as exc:
        raise WorkflowDomainError.from_error(exc) from exc


def _bot_or_fail(db: Session, workspace_id: str, config: dict[str, Any]) -> FeishuBot:
    """这次用哪个机器人。没接机器人 = 这件事做不成,当场说清(见模块说明)。"""
    bot = routing.pick_bot(db, workspace_id, routing.bot_id_of(config))
    if bot is None:
        raise WorkflowDomainError("wfErr_feishuNoBot")
    return bot


def _required(config: dict[str, Any], key: str, error: str) -> str:
    value = as_text(config.get(key)).strip()
    if not value:
        raise WorkflowDomainError(error)
    return value


def _target_or_fail(db: Session, scope: RunScope, config: dict[str, Any], *, allowed: tuple[str, ...]):
    """解出"发到哪";解不出来(缺机器人 / 没填收件人 / 没人绑)和**写法认不出**都在这里说清。

    `routing` 是领域里的叶子模块:它不能回头 import 工作流这一层(见 tests/test_import_layering),
    所以"认不出的写法"它按 key 抛 `LocalizedError`,由这里转成工作流错误 —— key 和参数跟着走,
    落库的失败原因才不会冻在写下它的那一刻(见 WorkflowDomainError.from_error)。
    """
    try:
        channel = routing.channel_of(config, allowed=allowed, strict=True)
        #: `raw` 那一档手填的是 `raw_id`,别的档是 `to` —— 写法不同,解的地方是同一处(见 routing.resolve)。
        if channel == routing.RAW:
            target_id, raw_type = as_text(config.get("raw_id")).strip(), routing.raw_type_of(config)
        else:
            target_id, raw_type = routing.to_of(config), ""
        resolved = routing.resolve(
            db,
            workspace_id=scope.workspace_id,
            channel=channel,
            bot_id=routing.bot_id_of(config),
            to=target_id,
            raw_type=raw_type,
            job=_job(db),
        )
    except LocalizedError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if resolved.target is None:
        raise WorkflowDomainError(_UNRESOLVED.get(resolved.reason, "wfErr_feishuNoTarget"))
    return resolved.target


@register("feishu_message")
def feishu_message(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """发一条文字或一张卡片到飞书。**发完就走** —— 不等回复、不建待批单(要等人点就用「等人确认」)。"""
    transport = _transport()
    target = _target_or_fail(db, scope, config, allowed=routing.MESSAGE_CHANNELS)
    if _form_of(config) == CARD_FORM:
        title = _required(config, "title", "wfErr_feishuEmptyTitle")
        message_id = transport.send_card(
            target.bot,
            target.receive_id,
            target.receive_type,
            transport.card(
                feishu_gateway.CardSpec(
                    title=title,
                    body=as_text(config.get("body")),
                    link=as_text(config.get("link")),
                    button_label=as_text(config.get("button_label")),
                )
            ),
        )
    else:
        text = _required(config, "text", "wfErr_feishuEmptyText")
        message_id = transport.send_text(target.bot, target.receive_id, target.receive_type, text)
    return {"sent": True, "message_id": message_id}


@register("feishu_take_resource")
def feishu_take_resource(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把飞书消息里的图片 / 文件取回来,**存成素材**。

    走素材库那条路(`import_binary_asset`)而不是"把字节直接交给下游":飞书发来的附件此后在素材库里
    也找得到、能复用、能分析 —— 和入站那条链路同一个落点。
    """

    transport = _transport()
    bot = _bot_or_fail(db, scope.workspace_id, config)
    message_id = _required(config, "message_id", "wfErr_feishuEmptyMessageId")
    file_key = _required(config, "file_key", "wfErr_feishuEmptyFileKey")
    downloaded = transport.download(bot, message_id, file_key, str(config.get("resource_type") or "image"))
    asset = importer.import_binary_asset(
        db,
        workspace_id=scope.workspace_id,
        project_id=None,
        data=downloaded.data,
        original=downloaded.filename,
        content_type=downloaded.content_type or None,
        source="feishu",
    )
    return {"asset_id": asset.id, "name": asset.name, "size_bytes": len(downloaded.data)}


@register("feishu_reaction")
def feishu_reaction(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """给一条飞书消息加一个表情。飞书拒了就算这一步失败(见模块说明:它就是要加上那个表情)。"""
    transport = _transport()
    bot = _bot_or_fail(db, scope.workspace_id, config)
    message_id = _required(config, "message_id", "wfErr_feishuEmptyMessageId")
    emoji = _required(config, "emoji_type", "wfErr_feishuEmptyEmoji")
    return {"reaction_id": transport.add_reaction(bot, message_id, emoji)}


@register("feishu_chats")
def feishu_chats(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """列出这个机器人所在的群(id 与名字)。「发到某个群」那几格的清单问的是同一份(见 field_options)。"""

    transport = _transport()
    bot = _bot_or_fail(db, scope.workspace_id, config)
    limit = whole_number(config, "limit", node_type="feishu_chats", default=200)
    #: **不再 `or 200`。** 那句会把用户写的 `0` 一起吃掉(填了 0 的人以为自己设了,跑的是默认的 200 个群)。
    #: `0` 在这里只能是"一个群都不列",而这个节点的用处就是交出群清单 —— 所以按「最少 1」当场说清,
    #: 而不是悄悄换成任何值(见 numbers.at_least 的说明)。
    limit = at_least(200 if limit is None else limit, 1, key="limit", node_type="feishu_chats")
    chats = transport.chats(bot, limit=min(limit, 1000))
    return {"chats": chats, "ids": [one["id"] for one in chats], "count": len(chats)}


@register_preflight("feishu_message")
@register_preflight("feishu_take_resource")
@register_preflight("feishu_reaction")
@register_preflight("feishu_chats")
def _needs_a_bot(db: Session, config: dict[str, Any], _actor: str | None, place: PreflightNode) -> None:
    """**开跑之前**就问一遍:这个工作区有没有机器人可用。

    不这么做的症状是:前面那些付费节点全跑完,轮到一个"发飞书"的节点才说"没接机器人" ——
    这个仓库反复修过的正是这一类。

    「发飞书消息」写了 `origin` 的那一档不问:它发得出去靠的是"这次运行从飞书会话来",
    而那本身就意味着有一个机器人;真到运行时没有,执行器会说。**认不出的通知方式**也不接着往下问:
    那件事比"有没有机器人"更该先说出来(和 `_target_or_fail` 同一个说法)。
    """
    if str(place.node.get("type") or "") == "feishu_message":
        try:
            channel = routing.channel_of(config, strict=True)
        except LocalizedError as exc:
            raise WorkflowDomainError.from_error(exc) from exc
        if channel == routing.ORIGIN:
            return
    if routing.pick_bot(db, place.workspace_id, routing.bot_id_of(config)) is None:
        raise WorkflowDomainError("wfErr_feishuNoBot")
