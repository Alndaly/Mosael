"""一处地方现在叫什么、看的人看不看得见 —— 对话的家(ADR 0044,domain/agent/places)和生成会话的出处(ADR 0052,
domain/generation/origins)共用的那一半。

只有「按 id 批量取名字」:那样东西在不在(`deleted`)、看的人看不看得见(`hidden`,名字给空串 —— 响应里不出现他看不见的
标题)、看得见时叫什么。建家时的校验(东西在不在这个工作区、ComfyUI 连接是不是他的)只有对话用,留在 agent/places。
抽到这里是因为生成会话也要它,而生成那一层不能认识智能体那一层(智能体的工具要调生成,反过来就成环,见
tests/test_import_layering.py)。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PluginInstance, User, WorkspaceMember

#: 三种状况(对话的 `home_state`、生成会话的 `origin_state`)。
OK = "ok"
DELETED = "deleted"
HIDDEN = "hidden"

#: id → (状况, 名字)。看不见、删了的,名字是空串。
Described = dict[str, tuple[str, str]]
Describe = Callable[[Session, User, set[str]], Described]


def comfy_parts(place_id: str) -> tuple[str, str, str]:
    """ComfyUI 那一处的 id(`<连接 id>/<路径>`、`<连接 id>#<标签页 key>`、`<连接 id>`)切成(连接 id, 存过的路径,
    没存过的标签页 key):后两样至多一样不空。从左边第一个 `/` 或 `#` 切开 —— 连接 id 里没有这两个字符。"""
    marks = [index for index in (place_id.find("/"), place_id.find("#")) if index >= 0]
    if not marks:
        return place_id, "", ""
    cut = min(marks)
    connection, rest = place_id[:cut], place_id[cut + 1:]
    return (connection, rest, "") if place_id[cut] == "/" else (connection, "", rest)


def workspace_things(model: Any, name_column: Any) -> Describe:
    """剪辑项目、笔记、画板、工作流、3D 场景、资产:都是工作区里的东西,工作区的人都看得见(各自的读闸都是「它在、你是这个
    工作区的人」)。"""

    def describe(db: Session, viewer: User, ids: set[str]) -> Described:
        rows = db.execute(select(model.id, name_column, model.workspace_id).where(model.id.in_(ids))).all()
        mine = set(db.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == viewer.id)))
        found = {row[0]: ((OK, row[1] or "") if row[2] in mine else (HIDDEN, "")) for row in rows}
        return {place_id: found.get(place_id, (DELETED, "")) for place_id in ids}

    return describe


def _file_name(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[: -len(".json")] if name.lower().endswith(".json") else name


def comfy_places(db: Session, viewer: User, ids: set[str]) -> Described:
    """ComfyUI 那一处:名字取路径里的文件名(不连那台机器);画布上一张都没开的,是连接的名字。连接删了是 `deleted`,
    不是他的是 `hidden`(连接归人)。"""
    connections = {comfy_parts(place_id)[0] for place_id in ids}
    owners = dict(db.execute(
        select(PluginInstance.id, PluginInstance.owner_user_id).where(PluginInstance.id.in_(connections))
    ).all())
    names = dict(db.execute(select(PluginInstance.id, PluginInstance.name).where(PluginInstance.id.in_(connections))).all())
    described: Described = {}
    for place_id in ids:
        connection, path, key = comfy_parts(place_id)
        if connection not in owners:
            described[place_id] = (DELETED, "")
        elif owners[connection] != viewer.id:
            described[place_id] = (HIDDEN, "")
        else:
            described[place_id] = (OK, _file_name(path or key) if (path or key) else names[connection])
    return described
