"""工作流触发器的用例:按触发器所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

**读写两档**:

- 看得见:工作区里的成员都能看(它和那条工作流一样,是团队的东西),`ensure_workspace_access`;
- 改得了:要 `edit`。理由和「运行一次工作流」一样 —— 配一条触发器 = **让这张图在群里自己跑起来**,
  它会花掉触发器主人的钥匙和额度,门槛不该比点一次「运行」低(见 workflows.use_cases.editable)。

**不做"启用前一定要跑得起来"的检查**(定时任务有 `SCHEDULED_READINESS`,这里没有):定时任务的入参
是一份固定的 `payload`,启用那一刻就知道;而触发器的入参**按这一次的消息算**(`{{trigger.text}}`),
一条必填的 `asset_id` 参数在配置的时候本来就没有值。所以这里只拦"配置本身写错了"(认不了的消息
类型、认不出的占位符、工作流不在这个工作区……);"这一次跑不跑得起来"在触发那一刻判,判不过就留痕
+ 通知主人(见 dispatch,ADR 0065 §5)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import FeishuBot, User, Workflow, WorkflowTrigger, WorkflowTriggerEvent
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.triggers import dispatch, matching

#: 「最近触发」最多给多少条(最近的在前)。
EVENT_LIST_LIMIT = 30

#: 一条触发器最多认几种消息类型(就是那四档)。
MESSAGE_TYPES = matching.TRIGGER_MESSAGE_TYPES


class TriggerDomainError(LocalizedError, ValueError):
    """触发器说不行。带文案 key(`triggerErr_*`)。"""


def _trigger(db: Session, trigger_id: str) -> WorkflowTrigger:
    trigger = db.get(WorkflowTrigger, trigger_id)
    if trigger is None:
        #: 和工作流那一族同一条:取不到就是取不到,接口层翻成 404(见 main.py 的 NotVisible 出口)。
        raise NotVisible("Trigger not found")
    return trigger


# ---------------- 读 ----------------


def list_triggers(
    db: Session, user: User, workspace_id: str, *, workflow_id: str | None = None
) -> list[WorkflowTrigger]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(WorkflowTrigger).where(WorkflowTrigger.workspace_id == workspace_id)
    if workflow_id:
        stmt = stmt.where(WorkflowTrigger.workflow_id == workflow_id)
    return list(db.scalars(stmt.order_by(WorkflowTrigger.created_at.desc())))


def readable(db: Session, user: User, trigger_id: str) -> WorkflowTrigger:
    trigger = _trigger(db, trigger_id)
    ensure_workspace_access(db, user, trigger.workspace_id)
    return trigger


def list_events(db: Session, user: User, trigger_id: str, *, limit: int = EVENT_LIST_LIMIT) -> list[WorkflowTriggerEvent]:
    """这个触发器最近触发过哪些消息、起了哪几次运行 —— 「它在干活吗」的那一屏。"""
    trigger = readable(db, user, trigger_id)
    return list(
        db.scalars(
            select(WorkflowTriggerEvent)
            .where(WorkflowTriggerEvent.trigger_id == trigger.id)
            .order_by(WorkflowTriggerEvent.created_at.desc())
            .limit(max(1, min(200, limit)))
        )
    )


# ---------------- 写 ----------------


def _clean(value: Any) -> list[str]:
    """一串去空的字符串(JSON 列里的关键词 / open_id / 素材类型)。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(one).strip() for one in value if str(one).strip()]


def _check_message_types(types: Any) -> list[str]:
    cleaned = _clean(types)
    if not cleaned:
        raise TriggerDomainError("triggerErr_noMessageTypes")
    bad = [one for one in cleaned if one not in MESSAGE_TYPES]
    if bad:
        raise TriggerDomainError("triggerErr_badMessageType", kinds=" / ".join(bad), allowed=" / ".join(MESSAGE_TYPES))
    #: 去重但保序:同一档写两遍没有意义,而界面上的顺序是用户挑的顺序。
    return list(dict.fromkeys(cleaned))


def _check_params(params: Any) -> dict[str, str]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise TriggerDomainError("triggerErr_badParam")
    out: dict[str, str] = {}
    for name, template in params.items():
        key = str(name).strip()
        if not key:
            raise TriggerDomainError("triggerErr_badParam")
        out[key] = str(template)
    bad = matching.bad_placeholders(out)
    if bad:
        raise TriggerDomainError(
            "triggerErr_badPlaceholder",
            names=" / ".join(bad),
            allowed=" / ".join("trigger." + one for one in matching.TRIGGER_FIELDS),
        )
    return out


def _check_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise TriggerDomainError("triggerErr_badLimit", max=dispatch.MAX_RUNS_PER_MINUTE) from None
    if not 1 <= limit <= dispatch.MAX_RUNS_PER_MINUTE:
        raise TriggerDomainError("triggerErr_badLimit", max=dispatch.MAX_RUNS_PER_MINUTE)
    return limit


def _workflow_in(db: Session, workspace_id: str, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.workspace_id != workspace_id:
        raise TriggerDomainError("triggerErr_workflowNotFound")
    return workflow


def _check_bot(db: Session, workspace_id: str, bot_id: str) -> str:
    """空串 = 任意机器人。给了名字就得是这个工作区里的,否则这条触发器永远不会命中。"""
    bot_id = (bot_id or "").strip()
    if not bot_id:
        return ""
    bot = db.get(FeishuBot, bot_id)
    if bot is None or bot.workspace_id != workspace_id:
        raise TriggerDomainError("triggerErr_botNotInWorkspace")
    return bot_id


def create(db: Session, user: User, workspace_id: str, **fields: Any) -> WorkflowTrigger:
    """配一条触发器。**记下它替谁跑** —— 触发的时候没有"当时的操作人"(见 ADR 0065 §1)。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    workflow = _workflow_in(db, workspace_id, str(fields.get("workflow_id") or ""))
    name = str(fields.get("name") or "").strip()
    if not name:
        raise TriggerDomainError("triggerErr_badName")
    trigger = WorkflowTrigger(
        workspace_id=workspace_id,
        workflow_id=workflow.id,
        owner_user_id=user.id,
        name=name,
        bot_id=_check_bot(db, workspace_id, str(fields.get("bot_id") or "")),
        chat_id=str(fields.get("chat_id") or "").strip(),
        message_types=_check_message_types(fields.get("message_types")),
        keywords=_clean(fields.get("keywords")),
        only_from_open_ids=_clean(fields.get("only_from_open_ids")),
        params=_check_params(fields.get("params")),
        reply_in_chat=bool(fields.get("reply_in_chat", True)),
        max_runs_per_minute=_check_limit(fields.get("max_runs_per_minute", 6)),
        enabled=bool(fields.get("enabled", True)),
    )
    db.add(trigger)
    db.flush()
    return trigger


def update(db: Session, user: User, trigger_id: str, changes: dict[str, Any]) -> WorkflowTrigger:
    """改一条触发器。`workflow_id` 可以改绑到同一工作区里的另一张图;主人不变。"""
    trigger = _trigger(db, trigger_id)
    ensure_workspace_perm(db, user, trigger.workspace_id, "edit")
    if "workflow_id" in changes and changes["workflow_id"] is not None:
        trigger.workflow_id = _workflow_in(db, trigger.workspace_id, str(changes["workflow_id"])).id
    if changes.get("name") is not None:
        name = str(changes["name"]).strip()
        if not name:
            raise TriggerDomainError("triggerErr_badName")
        trigger.name = name
    if changes.get("bot_id") is not None:
        trigger.bot_id = _check_bot(db, trigger.workspace_id, str(changes["bot_id"]))
    if changes.get("chat_id") is not None:
        trigger.chat_id = str(changes["chat_id"]).strip()
    if changes.get("message_types") is not None:
        trigger.message_types = _check_message_types(changes["message_types"])
    if changes.get("keywords") is not None:
        trigger.keywords = _clean(changes["keywords"])
    if changes.get("only_from_open_ids") is not None:
        trigger.only_from_open_ids = _clean(changes["only_from_open_ids"])
    if changes.get("params") is not None:
        trigger.params = _check_params(changes["params"])
    if changes.get("reply_in_chat") is not None:
        trigger.reply_in_chat = bool(changes["reply_in_chat"])
    if changes.get("max_runs_per_minute") is not None:
        trigger.max_runs_per_minute = _check_limit(changes["max_runs_per_minute"])
    if changes.get("enabled") is not None:
        trigger.enabled = bool(changes["enabled"])
    db.flush()
    return trigger


def delete(db: Session, user: User, trigger_id: str) -> None:
    trigger = _trigger(db, trigger_id)
    ensure_workspace_perm(db, user, trigger.workspace_id, "edit")
    db.delete(trigger)


def stop_triggers_bound_to_workflow(db: Session, workflow: Workflow) -> list[WorkflowTrigger]:
    """一张工作流要被删了:绑着它的触发器**当场停用**。不提交,由删除的那一方一起提交。

    和定时任务那一条(`scheduler.stop_tasks_bound_to_workflow`)是同一件事、同一个理由:
    触发器留着(连同它的最近触发记录),删不删由人决定 —— 但它不能再自己跑,每来一条消息就
    白试一次、喊一次主人。

    **不删行**:删了就没有"这里原本挂着一条自动化、它跑过 N 次"的痕迹了。
    """
    stopped = list(
        db.scalars(
            select(WorkflowTrigger).where(
                WorkflowTrigger.workflow_id == workflow.id,
                WorkflowTrigger.workspace_id == workflow.workspace_id,
                WorkflowTrigger.enabled.is_(True),
            )
        )
    )
    for trigger in stopped:
        trigger.enabled = False
    return stopped
