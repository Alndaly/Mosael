"""删东西的确认卡工具:素材、项目。

单独成文件是因为它们共用一件事 —— **撤不回来**。这是 `destroy` 档唯一的成员组,卡上说的话
也要按这一点写:说清一共几个、都叫什么、还会连带没掉什么。

为什么要有这两个工具:用户让智能体"把这几个下载源一起删掉",而智能体只有改名、移动项目、
打标签 —— 它只能列一张清单让用户自己去界面上一个个点。清单本身它已经算得出来了,少的就是
最后那一下。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Project
from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError

#: 一张卡最多删多少个。不是性能上限,是**读得完**的上限:卡上列不下的东西,用户点批准时
#: 并不知道自己批了什么,而这一档撤不回来。要删更多就分几次,每次都看得见。
MAX_PER_CARD = 20


def _ids(payload: dict[str, Any], key: str) -> list[str]:
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        raise ConfirmationError(f"{key} 要是一个列表")
    ids = [str(one).strip() for one in raw if str(one).strip()]
    if not ids:
        raise ConfirmationError(f"{key} 是空的:没有要删的东西")
    if len(ids) > MAX_PER_CARD:
        raise ConfirmationError(f"一次最多删 {MAX_PER_CARD} 个,分几次来 —— 卡上列不下的话,批准的人并不知道自己批了什么")
    # 去重且保序:同一个 id 写两遍,第二次执行时它已经不在了,会平白报一次"找不到"。
    seen: dict[str, None] = {}
    for one in ids:
        seen.setdefault(one, None)
    return list(seen)


def _rows(db: Session, model: Any, workspace_id: str, ids: list[str], what: str) -> list[Any]:
    """这些 id 对应的行,**全都要在这个工作区里**。

    少一个就整张卡不开:删除按"这一批"给用户看,执行时却只删掉其中几个,那张卡说的话就不是
    真的了。而这一档没有第二次机会去纠正。
    """
    rows = list(db.scalars(select(model).where(model.id.in_(ids), model.workspace_id == workspace_id)))
    found = {row.id for row in rows}
    missing = [one for one in ids if one not in found]
    if missing:
        raise ConfirmationError(f"这个工作区里找不到这些{what}:{', '.join(missing[:5])}")
    # 按传入顺序排,卡上的次序就是模型说的次序 —— 用户对得上。
    order = {one: index for index, one in enumerate(ids)}
    return sorted(rows, key=lambda row: order[row.id])


def _count(db: Session, model: Any, column: Any, ids: list[str]) -> int:
    """挂在这批 id 下面的行有多少 —— 卡上要说的连带后果。"""
    return int(db.scalar(select(func.count()).select_from(model).where(column.in_(ids))) or 0)


def _names(rows: list[Any], limit: int = 4) -> str:
    names = [str(getattr(row, "name", "") or row.id[:8]) for row in rows]
    head = "、".join(names[:limit])
    return head if len(names) <= limit else f"{head} 等 {len(names)} 个"


# ---------- 素材 ----------


def _validate_delete_assets(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    rows = _rows(db, Asset, workspace_id, _ids(payload, "asset_ids"), "素材")
    # 卡上要说清连带后果,所以在这里就数出来 —— 摘要不该自己再查一遍库。
    payload["_names"] = _names(rows)
    payload["_count"] = len(rows)
    payload["_clips"] = _count(db, Clip, Clip.asset_id, [row.id for row in rows])


def _summarize_delete_assets(db: Session, payload: dict[str, Any]) -> Summary:
    clips = int(payload.get("_clips") or 0)
    return "confirm_deleteAssets", {
        "count": int(payload.get("_count") or 0),
        "names": payload.get("_names") or "",
        "tail": fragment("confirm_deleteAssetsClips", clips=clips) if clips else "",
    }


def _execute_delete_assets(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain.assets import delete_asset_with_clips

    payload = confirmation.payload or {}
    deleted: list[dict[str, Any]] = []
    offline = 0
    for asset_id in _ids(payload, "asset_ids"):
        asset = db.get(Asset, asset_id)
        # 开卡到批准之间用户可能已经自己删了。那不是失败 —— 结果就是他要的那个结果。
        if asset is None or asset.workspace_id != confirmation.workspace_id:
            continue
        result = delete_asset_with_clips(db, asset)
        offline += result.offline_clips
        deleted.append({"asset_id": result.asset_id, "name": result.name})
    return {"deleted": deleted, "offline_clips": offline}


# ---------- 项目 ----------


def _validate_delete_projects(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    rows = _rows(db, Project, workspace_id, _ids(payload, "project_ids"), "项目")
    payload["_names"] = _names(rows)
    payload["_count"] = len(rows)
    payload["_assets"] = _count(db, Asset, Asset.project_id, [row.id for row in rows])


def _summarize_delete_projects(db: Session, payload: dict[str, Any]) -> Summary:
    count = int(payload.get("_count") or 0)
    assets = int(payload.get("_assets") or 0)
    # 素材**不跟着删**(它们只是 project_id 置空,回到工作区级)。这句话一定要说:否则用户
    # 会以为批准删项目就等于把里面的素材也清了,反过来也会不敢批。
    return "confirm_deleteProjects", {
        "count": count,
        "names": payload.get("_names") or "",
        "tail": fragment("confirm_deleteProjectsAssets", assets=assets) if assets else "",
    }


def _execute_delete_projects(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload or {}
    deleted: list[dict[str, Any]] = []
    for project_id in _ids(payload, "project_ids"):
        project = db.get(Project, project_id)
        if project is None or project.workspace_id != confirmation.workspace_id:
            continue
        deleted.append({"project_id": project.id, "name": project.name})
        db.delete(project)
    db.commit()
    return {"deleted": deleted}


confirmable_tool(ConfirmableTool(
    name="delete_assets",
    permission="destroy",
    cost="none",
    summarize=_summarize_delete_assets,
    execute=_execute_delete_assets,
    validate=_validate_delete_assets,
))


confirmable_tool(ConfirmableTool(
    name="delete_projects",
    permission="destroy",
    cost="none",
    summarize=_summarize_delete_projects,
    execute=_execute_delete_projects,
    validate=_validate_delete_projects,
))
