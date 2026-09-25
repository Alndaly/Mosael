"""素材挂在哪个项目下:**唯一的判断**。

素材行上的 `project_id` 有三条写入路:入库(importer._import_stream —— 上传、按路径注册、
渲染 / 配音 / 生成的产出全汇到那里)、直接建行(`POST /api/assets`)、改归档(`PATCH`)。
此前只有改归档那条拦着「项目必须在同一个工作区」,另外两条原样照收:带着别的工作区的
project_id 导入,素材就挂在了别人的项目下 —— 自己工作区的项目列表里看不见它,别人的
项目按 project_id 却查得到。

判断收在这一处,三条路都调它;HTTP 边界由 app/main 统一翻成 422,调用方不必各自 catch。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Project


class AssetProjectError(LocalizedError, ValueError):
    """素材要挂的项目不存在,或者不在这个工作区。"""

    status = 422


def asset_project(db: Session, workspace_id: str, project_id: str | None) -> str | None:
    """素材要挂的项目 id。

    没给(None / 空串)就是工作区级素材 —— 属于整个工作区,返回 None。给了就必须是这个
    工作区里真实存在的项目。
    """
    target = (project_id or "").strip()
    if not target:
        return None
    project = db.get(Project, target)
    if project is None or project.workspace_id != workspace_id:
        raise AssetProjectError("assetErr_projectNotInWorkspace")
    return project.id
