"""会话分组的接口。对话和生成共用这一组,由 `kind` 分开。

从 `routes/agent.py` 提上来的:分组不再只属于对话。挂在 `/api/session-groups` 而不是
`/api/agent/session-groups` —— 路径里带 agent 的话,生成那边调它就成了「生成页去请求
对话的接口」,读代码的人得先确认这不是写错了。
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import SessionGroupCreate, SessionGroupOut, SessionGroupUpdate
from app.db.models import SessionGroup
from app.domain.session_groups import use_cases as session_groups

router = APIRouter(tags=["session-groups"])


@router.get("/session-groups", response_model=list[SessionGroupOut])
def list_session_groups(workspace_id: str, db: DbSession, user: CurrentUser, kind: str = "agent") -> list[SessionGroup]:
    return session_groups.list_all(db, user, workspace_id, kind)


@router.post("/session-groups", response_model=SessionGroupOut, status_code=201)
def create_session_group(body: SessionGroupCreate, db: Tx, user: CurrentUser) -> SessionGroup:
    return session_groups.create(db, user, body.workspace_id, kind=body.kind, name=body.name)


@router.patch("/session-groups/{group_id}", response_model=SessionGroupOut)
def update_session_group(group_id: str, body: SessionGroupUpdate, db: Tx, user: CurrentUser) -> SessionGroup:
    return session_groups.update(db, user, group_id, name=body.name, sort_order=body.sort_order)


@router.delete("/session-groups/{group_id}", status_code=204)
def delete_session_group(group_id: str, db: Tx, user: CurrentUser) -> Response:
    """删掉分组,**里面的会话留着**(退回未分组,见 domain/session_groups)。"""
    session_groups.delete(db, user, group_id)
    return Response(status_code=204)
