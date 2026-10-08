"""3D 场景的用例:谁能做、做什么写在一起(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

场景和模型都归**工作区**:每个用例先按工作区过闸,再用 `get_scene` 确认这个场景确实在这个工作区里
(不在就是 404,不泄漏存在性)。HTTP 路由和智能体工具调同一个函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Scene3D, Scene3DModel, Scene3DRevision, User
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.scenes import operations as ops

#: 列表最多给多少个场景(按最近修改)。
LIST_LIMIT = 200


# ---------------- 读 ----------------


def list_scenes(db: Session, user: User, workspace_id: str) -> list[dict[str, Any]]:
    ensure_workspace_access(db, user, workspace_id)
    rows = db.scalars(
        select(Scene3D).where(Scene3D.workspace_id == workspace_id).order_by(Scene3D.updated_at.desc()).limit(LIST_LIMIT)
    )
    return [
        {
            "id": r.id, "name": r.name, "revision": r.revision, "updated_at": r.updated_at,
            "object_count": len(r.content.get("objects", [])), "shot_count": len(r.content.get("shots", [])),
            "preview": ops.scene_preview(r.content), "template": r.content.get("template"),
        }
        for r in rows
    ]


def read(db: Session, user: User, workspace_id: str, scene_id: str) -> Scene3D:
    ensure_workspace_access(db, user, workspace_id)
    return ops.get_scene(db, workspace_id, scene_id)


def overview_image(db: Session, user: User, workspace_id: str, scene_id: str) -> Path:
    return ops.scene_overview_image(db, read(db, user, workspace_id, scene_id))


def revisions(db: Session, user: User, workspace_id: str, scene_id: str) -> list[dict[str, Any]]:
    read(db, user, workspace_id, scene_id)
    rows = db.scalars(
        select(Scene3DRevision).where(Scene3DRevision.scene_id == scene_id).order_by(Scene3DRevision.revision.desc()).limit(100)
    )
    return [{"revision": r.revision, "name": r.snapshot["name"], "created_at": r.created_at} for r in rows]


def revision_content(db: Session, user: User, workspace_id: str, scene_id: str, revision: int) -> dict[str, Any]:
    read(db, user, workspace_id, scene_id)
    row = db.get(Scene3DRevision, (scene_id, revision))
    if row is None:
        raise NotVisible("Revision not found")
    return row.snapshot


def view(db: Session, user: User, workspace_id: str, scene_id: str, **options: Any) -> dict[str, Any]:
    """渲几张图给智能体看。不写素材库、不落盘 —— 只读。"""
    return ops.view_scene(db, read(db, user, workspace_id, scene_id), **options)


def list_models(db: Session, user: User, workspace_id: str) -> list[dict[str, Any]]:
    # 模型归**工作区**,不归某个场景:一件道具导一次、处处能摆。
    ensure_workspace_access(db, user, workspace_id)
    return [{"id": m.id, "name": m.name, "format": m.format, "size": m.size} for m in ops.list_models(db, workspace_id)]


def model_file(db: Session, user: User, workspace_id: str, model_id: str) -> tuple[Scene3DModel, Path]:
    ensure_workspace_access(db, user, workspace_id)
    model = db.get(Scene3DModel, model_id)
    if model is None or model.workspace_id != workspace_id:
        raise NotVisible("Model not found")
    return model, ops.model_file(model)


# ---------------- 写 ----------------


def create(db: Session, user: User, workspace_id: str, name: str, content: Any) -> Scene3D:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return ops.create_scene(db, workspace_id, name, content)


def save(db: Session, user: User, workspace_id: str, scene_id: str, *, base_revision: int, name: str, content: Any) -> Scene3D:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return ops.save_scene(db, ops.get_scene(db, workspace_id, scene_id), base_revision, name, content)


def apply_operations(
    db: Session,
    user: User,
    workspace_id: str,
    scene_id: str,
    *,
    base_revision: int,
    objects: list[dict],
    remove_ids: list[str],
    shots: list[dict] | None,
    name: str | None,
) -> Scene3D:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    scene = ops.get_scene(db, workspace_id, scene_id)
    return ops.apply_scene_operations(db, scene, base_revision, objects, remove_ids, shots, name)


def delete(db: Session, user: User, workspace_id: str, scene_id: str) -> None:
    """删除的**引用完整性决定**在 operations.delete_scene(还有谁在用它)。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    ops.delete_scene(db, workspace_id, scene_id)


def import_model(db: Session, user: User, workspace_id: str, *, name: str, stream: BinaryIO, declared_size: int | None) -> Scene3DModel:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return ops.import_model(db, workspace_id, name, stream, declared_size=declared_size)


def delete_model(db: Session, user: User, workspace_id: str, model_id: str) -> None:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    ops.delete_model(db, workspace_id, model_id)


def render_references(
    db: Session, user: User, workspace_id: str, scene_id: str, shot_id: str, *, render: str, project_id: str | None
) -> dict[str, Any]:
    """渲这个镜头的白模参考(首尾静帧 / 运镜视频),登记成素材。会往素材库里写东西,所以要 edit。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    scene = ops.get_scene(db, workspace_id, scene_id)
    return ops.render_shot_references(db, scene, shot_id, render=render, project_id=project_id)
