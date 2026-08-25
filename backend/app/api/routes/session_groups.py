"""会话分组的接口。对话和生成共用这一组,由 `kind` 分开。

从 `routes/agent.py` 提上来的:分组不再只属于对话。挂在 `/api/session-groups` 而不是
`/api/agent/session-groups` —— 路径里带 agent 的话,生成那边调它就成了「生成页去请求
对话的接口」,读代码的人得先确认这不是写错了。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import SessionGroupCreate, SessionGroupOut, SessionGroupUpdate
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import SessionGroup
from app.domain import session_groups

router = APIRouter(tags=["session-groups"])


@router.get("/session-groups", response_model=list[SessionGroupOut])
def list_session_groups(workspace_id: str, db: DbSession, user: CurrentUser, kind: str = "agent") -> list[SessionGroup]:
    ensure_workspace_access(db, user, workspace_id)
    return session_groups.list_groups(db, workspace_id, kind)


@router.post("/session-groups", response_model=SessionGroupOut, status_code=201)
def create_session_group(body: SessionGroupCreate, db: DbSession, user: CurrentUser) -> SessionGroup:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    return session_groups.create_group(
        db, workspace_id=body.workspace_id, kind=body.kind, name=body.name, owner_user_id=user.id
    )


@router.patch("/session-groups/{group_id}", response_model=SessionGroupOut)
def update_session_group(group_id: str, body: SessionGroupUpdate, db: DbSession, user: CurrentUser) -> SessionGroup:
    group = require_group(db, user, group_id)
    ensure_workspace_perm(db, user, group.workspace_id, "ai")
    if body.name is not None:
        session_groups.rename_group(db, group, body.name)
    if body.sort_order is not None:
        session_groups.set_group_order(db, group, body.sort_order)
    return group


@router.delete("/session-groups/{group_id}", status_code=204)
def delete_session_group(group_id: str, db: DbSession, user: CurrentUser) -> Response:
    """删掉分组,**里面的会话留着**(退回未分组,见 domain/session_groups)。"""
    group = require_group(db, user, group_id)
    ensure_workspace_perm(db, user, group.workspace_id, "ai")
    session_groups.delete_group(db, group)
    return Response(status_code=204)


def require_group(db: DbSession, user: CurrentUser, group_id: str) -> SessionGroup:
    """取一个当前用户看得见的分组。会话路由挪会话进组时也用它 —— 别处再写一遍就会漏鉴权。"""
    group = db.get(SessionGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    ensure_workspace_access(db, user, group.workspace_id)
    return group
