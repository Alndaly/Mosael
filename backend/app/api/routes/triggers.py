"""工作流触发器:配置的增删改查 + 「最近触发过哪些消息 / 起了哪几次运行」(ADR 0065)。

路径挂在 `/workflow-triggers` 而不是 `/workflows/{id}/triggers`:触发器是**跨工作流**被查询的东西
(面板要一次问出"这个工作区里都有哪些自动化"),而且它自己就是一等资源(id 唯一、能直接改)。
工作流那一侧只在"删工作流时停用"那一步认识它(见 routes/workflows.py)。

出参 schema 就地写在这个模块里(和 hooks.py 同一种做法):它们是这一族接口自己的形状,
不进 `api/schemas` 那张按领域切开的公共表 —— 触发器的形状还没有第二个消费者。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import Field

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.base import ApiModel, OrmModel
from app.db.models import WorkflowTrigger, WorkflowTriggerEvent
from app.domain.triggers import TriggerDomainError
from app.domain.triggers import use_cases as triggers

router = APIRouter(tags=["triggers"])


class WorkflowTriggerCreate(ApiModel):
    """配一条触发器。`name` 是回执里要点名的那个名字。"""

    workspace_id: str
    workflow_id: str
    name: str = Field(min_length=1, max_length=160)
    #: 空 = 这个工作区里任意机器人 / 任意群。
    bot_id: str = Field(default="", max_length=64)
    chat_id: str = Field(default="", max_length=120)
    #: text(含富文本)/ image / file / media。
    message_types: list[str] = Field(default_factory=lambda: ["text"])
    keywords: list[str] = Field(default_factory=list)
    only_from_open_ids: list[str] = Field(default_factory=list)
    #: {"<开始节点参数名>": "<含 trigger 占位符的模板>"}。
    params: dict[str, str] = Field(default_factory=dict)
    reply_in_chat: bool = True
    max_runs_per_minute: int = 6
    enabled: bool = True


class WorkflowTriggerUpdate(ApiModel):
    """改一条触发器。不传的字段不动(`exclude_unset` 由路由那一层给)。"""

    workflow_id: str | None = None
    name: str | None = Field(default=None, max_length=160)
    bot_id: str | None = Field(default=None, max_length=64)
    chat_id: str | None = Field(default=None, max_length=120)
    message_types: list[str] | None = None
    keywords: list[str] | None = None
    only_from_open_ids: list[str] | None = None
    params: dict[str, str] | None = None
    reply_in_chat: bool | None = None
    max_runs_per_minute: int | None = None
    enabled: bool | None = None


class WorkflowTriggerOut(OrmModel):
    id: str
    workspace_id: str
    workflow_id: str
    name: str
    bot_id: str
    chat_id: str
    message_types: list[str]
    keywords: list[str]
    only_from_open_ids: list[str]
    params: dict[str, str]
    reply_in_chat: bool
    max_runs_per_minute: int
    enabled: bool
    #: 上一次真的起跑了是什么时候(被限流、被拒的不算)。
    last_fired_at: datetime | None
    created_at: datetime


class WorkflowTriggerEventOut(OrmModel):
    """「最近触发」的一行:哪条消息、认了什么、起了哪次运行(或者为什么没起)。"""

    id: str
    message_id: str
    message_type: str
    #: 消息文本的开头一段。
    text_preview: str
    asset_ids: list[str]
    #: 起成功了才有。
    job_id: str | None
    #: started / throttled / refused / failed / skipped
    status: str
    error: str
    created_at: datetime


@router.post("/workflow-triggers", response_model=WorkflowTriggerOut)
def create_trigger(body: WorkflowTriggerCreate, db: Tx, user: CurrentUser) -> WorkflowTrigger:
    fields = body.model_dump()
    try:
        return triggers.create(db, user, fields.pop("workspace_id"), **fields)
    except TriggerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workflow-triggers", response_model=list[WorkflowTriggerOut])
def list_triggers(
    workspace_id: str, db: DbSession, user: CurrentUser, workflow_id: str | None = None
) -> list[WorkflowTrigger]:
    return triggers.list_triggers(db, user, workspace_id, workflow_id=workflow_id)


@router.get("/workflow-triggers/{trigger_id}", response_model=WorkflowTriggerOut)
def get_trigger(trigger_id: str, db: DbSession, user: CurrentUser) -> WorkflowTrigger:
    return triggers.readable(db, user, trigger_id)


@router.patch("/workflow-triggers/{trigger_id}", response_model=WorkflowTriggerOut)
def update_trigger(
    trigger_id: str, body: WorkflowTriggerUpdate, db: Tx, user: CurrentUser
) -> WorkflowTrigger:
    """改配置、开关也走这里(`{"enabled": false}` 就是关掉它)。"""
    changes = body.model_dump(exclude_unset=True)
    try:
        return triggers.update(db, user, trigger_id, changes)
    except TriggerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/workflow-triggers/{trigger_id}", status_code=204)
def delete_trigger(trigger_id: str, db: Tx, user: CurrentUser) -> Response:
    triggers.delete(db, user, trigger_id)
    return Response(status_code=204)


@router.get("/workflow-triggers/{trigger_id}/events", response_model=list[WorkflowTriggerEventOut])
def list_events(
    trigger_id: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=triggers.EVENT_LIST_LIMIT, ge=1, le=200),
) -> list[WorkflowTriggerEvent]:
    """这个触发器最近触发过哪些消息、起了哪几次运行 —— 「它在干活吗」问的就是这一条。"""
    return triggers.list_events(db, user, trigger_id, limit=limit)
