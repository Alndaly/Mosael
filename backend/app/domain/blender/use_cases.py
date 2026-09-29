"""Blender 互通的用例:按工作区过闸,再交给 bridge / agent(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

连接本身按**归属**判(bridge.connection:只能用自己的那个 Blender 连接);场景按工作区判。
读(看场景里有什么、渲几张图、取历史)只要看得见;写(发送、接回、导入、拉取)点名 edit。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User
from app.domain.blender import agent as blender_agent
from app.domain.blender import bridge
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.scenes.operations import get_scene


def inspect(db: Session, user: User, workspace_id: str, instance_id: str = "") -> dict[str, Any]:
    """当前 Blender 场景里有什么。固定脚本,只读。"""
    ensure_workspace_access(db, user, workspace_id)
    return blender_agent.inspect(db, user, workspace_id, instance_id)


def look(db: Session, user: User, workspace_id: str, **options: Any) -> dict[str, Any]:
    """把当前 Blender 场景渲成几张图给智能体看。临时改渲染设置,渲完还原。"""
    ensure_workspace_access(db, user, workspace_id)
    return blender_agent.look(db, user, workspace_id, **options)


def history(db: Session, user: User, workspace_id: str, scene_id: str) -> Any:
    ensure_workspace_access(db, user, workspace_id)
    return bridge.history(get_scene(db, workspace_id, scene_id), user)


def project_file(db: Session, user: User, workspace_id: str, scene_id: str, transfer_id: str) -> Path:
    """那次互通里 Blender 存下的 .blend。只给互通目录里面的文件。"""
    ensure_workspace_access(db, user, workspace_id)
    folder, record = bridge.load(get_scene(db, workspace_id, scene_id), user, transfer_id)
    path = folder / record.get("latest_blend", "scene.blend")
    if not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
        raise bridge.BlenderNotFound("blenderErr_projectNotFound")
    return path


def send(db: Session, user: User, workspace_id: str, scene_id: str, *, instance_id: str, revision: int, shot_id: str) -> Any:
    """把场景发进 Blender。GLB 在后端生成(见 bridge.send)。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return bridge.send(db, user, get_scene(db, workspace_id, scene_id), instance_id, revision, shot_id)


def receive(db: Session, user: User, workspace_id: str, scene_id: str, transfer_id: str, *, into_current: bool) -> Any:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return bridge.receive(db, user, get_scene(db, workspace_id, scene_id), transfer_id, into_current=into_current)


def pull(db: Session, user: User, workspace_id: str, instance_id: str) -> Any:
    """把 Blender 里当前打开的场景取成一个新的 Mosael 场景。不要求先发送过。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return bridge.pull(db, user, workspace_id, instance_id)


def import_to_scene(db: Session, user: User, workspace_id: str, scene_id: str, **options: Any) -> Any:
    """把 Blender 里做好的东西作为一个模型物体加进这个场景。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return blender_agent.import_to_scene(db, user, get_scene(db, workspace_id, scene_id), **options)
