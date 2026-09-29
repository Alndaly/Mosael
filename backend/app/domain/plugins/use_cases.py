"""插件的用例:谁能调、调了收进哪儿(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

接入归人:只能调自己接的那个。带着工作区跑的工具会读它的素材、把产出收进它的素材库,所以要那个
工作区的 `edit` —— 插件页「试一下」和智能体调一个不开卡(effects: none)的插件工具走同一道闸。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance, PluginInvocation, User
from app.domain.permissions import NotVisible, ensure_workspace_perm
from app.domain.plugins import tools


def invoke_tool(
    db: Session,
    user: User,
    instance_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    workspace_id: str | None = None,
) -> PluginInvocation:
    """「别人接的」和「不存在」对他是同一件事(404),不回 403 —— 那等于告诉他这个 id 有效。"""
    instance = db.get(PluginInstance, instance_id)
    if instance is None or instance.owner_user_id != user.id:
        raise NotVisible("routeErr_pluginConnectionNotFound")
    if workspace_id is not None:
        ensure_workspace_perm(db, user, workspace_id, "edit")
    return tools.invoke(db, instance_id, tool_name, arguments, workspace_id=workspace_id)
